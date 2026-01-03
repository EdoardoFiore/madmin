"""
MADMIN Backup Service

Handles:
- Database dumps (PostgreSQL)
- Configuration file backup
- Archive creation
- Remote upload (SFTP/FTP)
- Scheduled backup via APScheduler
"""
import os
import asyncio
import tarfile
import logging
from datetime import datetime
from typing import Optional
from pathlib import Path

logger = logging.getLogger(__name__)

# Backup configuration
BACKUP_DIR = os.environ.get("MADMIN_BACKUP_DIR", "/opt/madmin/backups")
MAX_LOCAL_BACKUPS = int(os.environ.get("MADMIN_MAX_BACKUPS", "5"))


def ensure_backup_dir():
    """Ensure backup directory exists."""
    os.makedirs(BACKUP_DIR, exist_ok=True)
    return BACKUP_DIR


async def dump_database(backup_path: str) -> bool:
    """
    Dump PostgreSQL database to file.
    Uses pg_dump with settings from environment.
    """
    try:
        from config import get_settings
        
        db_url = get_settings().database_url
        if not db_url:
            logger.error("DATABASE_URL not configured for backup")
            return False
        
        # Convert asyncpg URL to standard postgresql format for pg_dump
        # postgresql+asyncpg://... -> postgresql://...
        if "+asyncpg" in db_url:
            db_url = db_url.replace("+asyncpg", "")
        
        # Parse database URL
        # Format: postgresql://user:password@host:port/database
        from urllib.parse import urlparse
        parsed = urlparse(db_url)
        
        dump_file = os.path.join(backup_path, "database.sql")
        
        # Build pg_dump command
        env = os.environ.copy()
        env["PGPASSWORD"] = parsed.password or ""
        
        cmd = [
            "pg_dump",
            "-h", parsed.hostname or "localhost",
            "-p", str(parsed.port or 5432),
            "-U", parsed.username or "madmin",
            "-d", parsed.path.lstrip("/"),
            "-F", "c",  # Custom format for compression
            "-f", dump_file
        ]
        
        process = await asyncio.create_subprocess_exec(
            *cmd,
            env=env,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await process.communicate()
        
        if process.returncode != 0:
            logger.error(f"pg_dump failed: {stderr.decode()}")
            return False
        
        logger.info(f"Database dumped to {dump_file}")
        return True
        
    except Exception as e:
        logger.error(f"Database dump failed: {e}")
        return False


def backup_config_files(backup_path: str) -> bool:
    """
    Copy important configuration files to backup.
    """
    try:
        config_dir = os.path.join(backup_path, "config")
        os.makedirs(config_dir, exist_ok=True)
        
        # Files to backup
        files_to_backup = [
            "/opt/madmin/backend/.env",
            "/etc/nginx/sites-available/madmin.conf",
            "/etc/nginx/sites-enabled/madmin.conf",
            "/etc/systemd/system/madmin.service",
        ]
        
        import shutil
        for filepath in files_to_backup:
            if os.path.exists(filepath):
                dest = os.path.join(config_dir, os.path.basename(filepath))
                shutil.copy2(filepath, dest)
                logger.info(f"Backed up {filepath}")
        
        # Backup installed modules directory
        modules_dir = "/opt/madmin/backend/modules"
        if os.path.exists(modules_dir) and os.listdir(modules_dir):
            shutil.copytree(
                modules_dir, 
                os.path.join(config_dir, "modules"),
                dirs_exist_ok=True
            )
            logger.info(f"Backed up {modules_dir}")
        
        # Backup staging modules directory
        staging_dir = "/opt/madmin/backend/staging"
        if os.path.exists(staging_dir) and os.listdir(staging_dir):
            shutil.copytree(
                staging_dir, 
                os.path.join(config_dir, "staging"),
                dirs_exist_ok=True
            )
            logger.info(f"Backed up {staging_dir}")
        
        # Backup module external_paths from manifests
        backup_module_external_paths(backup_path)
        
        return True
        
    except Exception as e:
        logger.error(f"Config backup failed: {e}")
        return False


def backup_module_external_paths(backup_path: str):
    """
    Backup external paths defined in module manifests.
    """
    import shutil
    import json
    
    external_dir = os.path.join(backup_path, "external")
    os.makedirs(external_dir, exist_ok=True)
    
    # Check both modules and staging directories
    module_dirs = [
        "/opt/madmin/backend/modules",
        "/opt/madmin/backend/staging"
    ]
    
    for modules_base in module_dirs:
        if not os.path.exists(modules_base):
            continue
            
        for module_name in os.listdir(modules_base):
            manifest_path = os.path.join(modules_base, module_name, "manifest.json")
            if not os.path.exists(manifest_path):
                continue
            
            try:
                with open(manifest_path, 'r') as f:
                    manifest = json.load(f)
                
                backup_config = manifest.get("backup", {})
                external_paths = backup_config.get("external_paths", [])
                
                for ext_path in external_paths:
                    if os.path.exists(ext_path):
                        # Create module-specific subdirectory
                        dest_dir = os.path.join(external_dir, module_name)
                        os.makedirs(dest_dir, exist_ok=True)
                        
                        dest = os.path.join(dest_dir, os.path.basename(ext_path.rstrip("/")))
                        
                        if os.path.isdir(ext_path):
                            shutil.copytree(ext_path, dest, dirs_exist_ok=True)
                        else:
                            shutil.copy2(ext_path, dest)
                        
                        logger.info(f"Backed up module external path: {ext_path}")
                        
            except Exception as e:
                logger.warning(f"Failed to backup external paths for {module_name}: {e}")


def create_archive(backup_path: str, archive_name: str) -> Optional[str]:
    """
    Create tar.gz archive of backup directory.
    """
    try:
        archive_path = os.path.join(BACKUP_DIR, archive_name)
        
        with tarfile.open(archive_path, "w:gz") as tar:
            tar.add(backup_path, arcname=os.path.basename(backup_path))
        
        logger.info(f"Created archive: {archive_path}")
        return archive_path
        
    except Exception as e:
        logger.error(f"Archive creation failed: {e}")
        return None


async def upload_sftp(
    archive_path: str,
    host: str,
    port: int,
    username: str,
    password: str,
    remote_path: str
) -> bool:
    """
    Upload backup archive via SFTP.
    """
    try:
        import asyncssh
        
        async with asyncssh.connect(
            host,
            port=port,
            username=username,
            password=password,
            known_hosts=None
        ) as conn:
            async with conn.start_sftp_client() as sftp:
                remote_file = os.path.join(remote_path, os.path.basename(archive_path))
                await sftp.put(archive_path, remote_file)
                logger.info(f"Uploaded to SFTP: {remote_file}")
                return True
                
    except ImportError:
        logger.error("asyncssh not installed for SFTP upload")
        return False
    except Exception as e:
        logger.error(f"SFTP upload failed: {e}")
        return False


async def upload_ftp(
    archive_path: str,
    host: str,
    port: int,
    username: str,
    password: str,
    remote_path: str
) -> bool:
    """
    Upload backup archive via FTP.
    """
    try:
        import aioftp
        
        async with aioftp.Client.context(host, port, username, password) as client:
            await client.change_directory(remote_path)
            await client.upload(archive_path)
            logger.info(f"Uploaded to FTP: {remote_path}")
            return True
            
    except ImportError:
        logger.error("aioftp not installed for FTP upload")
        return False
    except Exception as e:
        logger.error(f"FTP upload failed: {e}")
        return False


# ============== REMOTE BACKUP MANAGEMENT ==============

async def list_remote_backups_sftp(
    host: str,
    port: int,
    username: str,
    password: str,
    remote_path: str
) -> list:
    """List backup files on remote SFTP server."""
    try:
        import asyncssh
        
        async with asyncssh.connect(
            host,
            port=port,
            username=username,
            password=password,
            known_hosts=None
        ) as conn:
            async with conn.start_sftp_client() as sftp:
                files = []
                for entry in await sftp.readdir(remote_path):
                    if entry.filename.startswith("madmin_backup_") and entry.filename.endswith(".tar.gz"):
                        files.append({
                            "filename": entry.filename,
                            "size_bytes": entry.attrs.size or 0,
                            "mtime": entry.attrs.mtime
                        })
                return sorted(files, key=lambda x: x.get("mtime", 0), reverse=True)
                
    except ImportError:
        logger.error("asyncssh not installed")
        return []
    except Exception as e:
        logger.error(f"SFTP list failed: {e}")
        return []


async def list_remote_backups_ftp(
    host: str,
    port: int,
    username: str,
    password: str,
    remote_path: str
) -> list:
    """List backup files on remote FTP server."""
    try:
        import aioftp
        
        async with aioftp.Client.context(host, port, username, password) as client:
            await client.change_directory(remote_path)
            files = []
            async for path, info in client.list():
                filename = str(path)
                if filename.startswith("madmin_backup_") and filename.endswith(".tar.gz"):
                    files.append({
                        "filename": filename,
                        "size_bytes": int(info.get("size", 0)),
                        "mtime": None  # FTP doesn't always provide mtime reliably
                    })
            return files
            
    except ImportError:
        logger.error("aioftp not installed")
        return []
    except Exception as e:
        logger.error(f"FTP list failed: {e}")
        return []


async def list_remote_backups(
    protocol: str,
    host: str,
    port: int,
    username: str,
    password: str,
    remote_path: str
) -> list:
    """List backup files on remote server."""
    if protocol == "sftp":
        return await list_remote_backups_sftp(host, port, username, password, remote_path)
    elif protocol == "ftp":
        return await list_remote_backups_ftp(host, port, username, password, remote_path)
    return []


async def download_remote_backup_sftp(
    host: str,
    port: int,
    username: str,
    password: str,
    remote_path: str,
    filename: str
) -> Optional[str]:
    """Download a backup file from remote SFTP server."""
    try:
        import asyncssh
        
        local_path = os.path.join(BACKUP_DIR, filename)
        remote_file = os.path.join(remote_path, filename)
        
        async with asyncssh.connect(
            host,
            port=port,
            username=username,
            password=password,
            known_hosts=None
        ) as conn:
            async with conn.start_sftp_client() as sftp:
                await sftp.get(remote_file, local_path)
                logger.info(f"Downloaded from SFTP: {filename}")
                return local_path
                
    except Exception as e:
        logger.error(f"SFTP download failed: {e}")
        return None


async def download_remote_backup_ftp(
    host: str,
    port: int,
    username: str,
    password: str,
    remote_path: str,
    filename: str
) -> Optional[str]:
    """Download a backup file from remote FTP server."""
    try:
        import aioftp
        
        local_path = os.path.join(BACKUP_DIR, filename)
        
        async with aioftp.Client.context(host, port, username, password) as client:
            await client.change_directory(remote_path)
            await client.download(filename, local_path)
            logger.info(f"Downloaded from FTP: {filename}")
            return local_path
            
    except Exception as e:
        logger.error(f"FTP download failed: {e}")
        return None


async def download_remote_backup(
    protocol: str,
    host: str,
    port: int,
    username: str,
    password: str,
    remote_path: str,
    filename: str
) -> Optional[str]:
    """Download a backup file from remote server."""
    if protocol == "sftp":
        return await download_remote_backup_sftp(host, port, username, password, remote_path, filename)
    elif protocol == "ftp":
        return await download_remote_backup_ftp(host, port, username, password, remote_path, filename)
    return None


async def delete_remote_backup_sftp(
    host: str,
    port: int,
    username: str,
    password: str,
    remote_path: str,
    filename: str
) -> bool:
    """Delete a backup file from remote SFTP server."""
    try:
        import asyncssh
        
        remote_file = os.path.join(remote_path, filename)
        
        async with asyncssh.connect(
            host,
            port=port,
            username=username,
            password=password,
            known_hosts=None
        ) as conn:
            async with conn.start_sftp_client() as sftp:
                await sftp.remove(remote_file)
                logger.info(f"Deleted from SFTP: {filename}")
                return True
                
    except Exception as e:
        logger.error(f"SFTP delete failed: {e}")
        return False


async def delete_remote_backup_ftp(
    host: str,
    port: int,
    username: str,
    password: str,
    remote_path: str,
    filename: str
) -> bool:
    """Delete a backup file from remote FTP server."""
    try:
        import aioftp
        
        async with aioftp.Client.context(host, port, username, password) as client:
            await client.change_directory(remote_path)
            await client.remove(filename)
            logger.info(f"Deleted from FTP: {filename}")
            return True
            
    except Exception as e:
        logger.error(f"FTP delete failed: {e}")
        return False


async def delete_remote_backup(
    protocol: str,
    host: str,
    port: int,
    username: str,
    password: str,
    remote_path: str,
    filename: str
) -> bool:
    """Delete a backup file from remote server."""
    if protocol == "sftp":
        return await delete_remote_backup_sftp(host, port, username, password, remote_path, filename)
    elif protocol == "ftp":
        return await delete_remote_backup_ftp(host, port, username, password, remote_path, filename)
    return False


async def cleanup_remote_backups(
    protocol: str,
    host: str,
    port: int,
    username: str,
    password: str,
    remote_path: str,
    retention_days: int
) -> int:
    """
    Remove old backups from remote storage based on retention policy.
    Returns count of deleted files.
    """
    if retention_days <= 0:
        return 0  # Keep forever
    
    deleted = 0
    try:
        from datetime import timedelta
        cutoff_timestamp = (datetime.now() - timedelta(days=retention_days)).timestamp()
        
        # List remote backups
        backups = await list_remote_backups(protocol, host, port, username, password, remote_path)
        
        for backup in backups:
            mtime = backup.get("mtime")
            if mtime and mtime < cutoff_timestamp:
                success = await delete_remote_backup(
                    protocol, host, port, username, password, remote_path, backup["filename"]
                )
                if success:
                    deleted += 1
                    logger.info(f"Remote cleanup: deleted {backup['filename']}")
                    
    except Exception as e:
        logger.error(f"Remote cleanup failed: {e}")
    
    return deleted


def cleanup_old_backups(retention_days: int = 30):
    """
    Remove old backups based on retention policy.
    retention_days=0 means keep forever.
    """
    if retention_days <= 0:
        return  # Keep forever
        
    try:
        from datetime import timedelta
        cutoff_date = datetime.now() - timedelta(days=retention_days)
        
        for backup_file in Path(BACKUP_DIR).glob("madmin_backup_*.tar.gz"):
            if datetime.fromtimestamp(backup_file.stat().st_mtime) < cutoff_date:
                backup_file.unlink()
                logger.info(f"Removed old backup (>{retention_days} days): {backup_file}")
            
    except Exception as e:
        logger.error(f"Cleanup failed: {e}")


async def run_backup(
    remote_protocol: Optional[str] = None,
    remote_host: Optional[str] = None,
    remote_port: int = 22,
    remote_user: Optional[str] = None,
    remote_password: Optional[str] = None,
    remote_path: str = "/",
    retention_days: int = 30
) -> dict:
    """
    Run a full backup operation.
    
    Returns dict with status and details.
    """
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_name = f"madmin_backup_{timestamp}"
    backup_path = os.path.join(ensure_backup_dir(), backup_name)
    
    os.makedirs(backup_path, exist_ok=True)
    
    result = {
        "success": False,
        "timestamp": timestamp,
        "archive": None,
        "remote_uploaded": False,
        "errors": []
    }
    
    # 1. Dump database
    if not await dump_database(backup_path):
        result["errors"].append("Database dump failed")
    
    # 2. Backup config files
    if not backup_config_files(backup_path):
        result["errors"].append("Config backup failed")
    
    # 3. Create archive
    archive_name = f"{backup_name}.tar.gz"
    archive_path = create_archive(backup_path, archive_name)
    
    if not archive_path:
        result["errors"].append("Archive creation failed")
        return result
    
    result["archive"] = archive_path
    
    # 4. Upload to remote if configured
    if remote_protocol and remote_host and remote_user:
        if remote_protocol == "sftp":
            uploaded = await upload_sftp(
                archive_path, remote_host, remote_port,
                remote_user, remote_password or "", remote_path
            )
        elif remote_protocol == "ftp":
            uploaded = await upload_ftp(
                archive_path, remote_host, remote_port or 21,
                remote_user, remote_password or "", remote_path
            )
        else:
            uploaded = False
            
        result["remote_uploaded"] = uploaded
        if not uploaded:
            result["errors"].append("Remote upload failed")
    
    # 5. Cleanup old backups
    cleanup_old_backups(retention_days)
    
    # 6. Cleanup temp directory
    import shutil
    shutil.rmtree(backup_path, ignore_errors=True)
    
    result["success"] = len(result["errors"]) == 0
    return result


# ============== RESTORE FUNCTIONS ==============

async def restore_database(backup_path: str) -> bool:
    """
    Restore PostgreSQL database from backup.
    Uses pg_restore with settings from config.
    """
    try:
        from config import get_settings
        
        db_url = get_settings().database_url
        if not db_url:
            logger.error("DATABASE_URL not configured for restore")
            return False
        
        # Convert asyncpg URL to standard postgresql format
        if "+asyncpg" in db_url:
            db_url = db_url.replace("+asyncpg", "")
        
        from urllib.parse import urlparse
        parsed = urlparse(db_url)
        
        dump_file = os.path.join(backup_path, "database.sql")
        if not os.path.exists(dump_file):
            logger.warning("No database.sql found in backup")
            return False
        
        # Build pg_restore command
        env = os.environ.copy()
        env["PGPASSWORD"] = parsed.password or ""
        
        # First, drop and recreate database connections
        # Use pg_restore with --clean to drop objects before recreating
        cmd = [
            "pg_restore",
            "-h", parsed.hostname or "localhost",
            "-p", str(parsed.port or 5432),
            "-U", parsed.username or "madmin",
            "-d", parsed.path.lstrip("/"),
            "--clean",  # Drop objects before recreating
            "--if-exists",  # Don't error if objects don't exist
            "--no-owner",  # Don't set ownership
            "-v",  # Verbose
            dump_file
        ]
        
        process = await asyncio.create_subprocess_exec(
            *cmd,
            env=env,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await process.communicate()
        
        # pg_restore may return non-zero even on success with --clean --if-exists
        # Check stderr for actual errors
        if process.returncode != 0:
            stderr_text = stderr.decode()
            # Ignore errors about objects not existing (expected with --clean)
            if "ERROR" in stderr_text and "does not exist" not in stderr_text:
                logger.error(f"pg_restore failed: {stderr_text}")
                return False
        
        logger.info(f"Database restored from {dump_file}")
        return True
        
    except Exception as e:
        logger.error(f"Database restore failed: {e}")
        return False


def restore_modules(backup_path: str) -> dict:
    """
    Restore modules from backup to their directories.
    Returns dict with counts of restored modules.
    """
    import shutil
    result = {"modules": 0, "staging": 0}
    
    config_dir = os.path.join(backup_path, "config")
    
    # Restore installed modules
    backup_modules = os.path.join(config_dir, "modules")
    if os.path.exists(backup_modules):
        dest = "/opt/madmin/backend/modules"
        os.makedirs(dest, exist_ok=True)
        for item in os.listdir(backup_modules):
            src = os.path.join(backup_modules, item)
            dst = os.path.join(dest, item)
            if os.path.isdir(src):
                shutil.copytree(src, dst, dirs_exist_ok=True)
                result["modules"] += 1
                logger.info(f"Restored module: {item}")
    
    # Restore staging modules
    backup_staging = os.path.join(config_dir, "staging")
    if os.path.exists(backup_staging):
        dest = "/opt/madmin/backend/staging"
        os.makedirs(dest, exist_ok=True)
        for item in os.listdir(backup_staging):
            src = os.path.join(backup_staging, item)
            dst = os.path.join(dest, item)
            if os.path.isdir(src):
                shutil.copytree(src, dst, dirs_exist_ok=True)
                result["staging"] += 1
                logger.info(f"Restored staging module: {item}")
    
    return result


def restore_external_paths(backup_path: str) -> int:
    """
    Restore external paths from backup using manifest info.
    Returns count of restored paths.
    """
    import shutil
    import json
    
    external_dir = os.path.join(backup_path, "external")
    if not os.path.exists(external_dir):
        logger.info("No external paths to restore")
        return 0
    
    count = 0
    config_dir = os.path.join(backup_path, "config")
    
    # Check manifests in both modules and staging from backup
    for subdir in ["modules", "staging"]:
        modules_dir = os.path.join(config_dir, subdir)
        if not os.path.exists(modules_dir):
            continue
        
        for module_name in os.listdir(modules_dir):
            manifest_path = os.path.join(modules_dir, module_name, "manifest.json")
            if not os.path.exists(manifest_path):
                continue
            
            try:
                with open(manifest_path, 'r') as f:
                    manifest = json.load(f)
                
                backup_config = manifest.get("backup", {})
                external_paths = backup_config.get("external_paths", [])
                
                # Look for this module's backed up external data
                module_external = os.path.join(external_dir, module_name)
                if not os.path.exists(module_external):
                    continue
                
                for ext_path in external_paths:
                    basename = os.path.basename(ext_path.rstrip("/"))
                    src = os.path.join(module_external, basename)
                    
                    if os.path.exists(src):
                        # Ensure parent directory exists
                        os.makedirs(os.path.dirname(ext_path), exist_ok=True)
                        
                        if os.path.isdir(src):
                            shutil.copytree(src, ext_path, dirs_exist_ok=True)
                        else:
                            shutil.copy2(src, ext_path)
                        
                        count += 1
                        logger.info(f"Restored external path: {ext_path}")
                        
            except Exception as e:
                logger.warning(f"Failed to restore external paths for {module_name}: {e}")
    
    return count


def preview_backup(archive_path: str) -> dict:
    """
    Preview contents of a backup archive without extracting.
    Returns dict with backup info.
    """
    import tarfile
    
    result = {
        "filename": os.path.basename(archive_path),
        "size_bytes": os.path.getsize(archive_path),
        "has_database": False,
        "config_files": [],
        "modules": [],
        "staging": [],
        "external_paths": []
    }
    
    try:
        with tarfile.open(archive_path, "r:gz") as tar:
            for member in tar.getnames():
                if member.endswith("database.sql"):
                    result["has_database"] = True
                elif "/config/" in member:
                    parts = member.split("/config/")
                    if len(parts) > 1:
                        sub = parts[1]
                        if sub.startswith("modules/"):
                            module = sub.split("/")[1] if "/" in sub else sub
                            if module and module not in result["modules"]:
                                result["modules"].append(module)
                        elif sub.startswith("staging/"):
                            module = sub.split("/")[1] if "/" in sub else sub.replace("staging/", "")
                            if module and module not in result["staging"]:
                                result["staging"].append(module)
                        elif not "/" in sub:
                            result["config_files"].append(sub)
                elif "/external/" in member:
                    parts = member.split("/external/")
                    if len(parts) > 1:
                        path = parts[1]
                        if "/" in path:
                            module = path.split("/")[0]
                            if module not in result["external_paths"]:
                                result["external_paths"].append(module)
                                
    except Exception as e:
        logger.error(f"Failed to preview backup: {e}")
        result["error"] = str(e)
    
    return result


async def restore_backup(archive_path: str) -> dict:
    """
    Restore from a backup archive.
    
    Steps:
    1. Extract archive to temp directory
    2. Restore database
    3. Restore modules
    4. Restore external paths
    
    Returns dict with status and details.
    """
    import shutil
    
    if not os.path.exists(archive_path):
        return {"success": False, "errors": ["Backup file not found"]}
    
    # Extract to temp directory
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    restore_path = os.path.join(BACKUP_DIR, f"restore_temp_{timestamp}")
    os.makedirs(restore_path, exist_ok=True)
    
    result = {
        "success": False,
        "database_restored": False,
        "modules_restored": 0,
        "staging_restored": 0,
        "external_restored": 0,
        "errors": []
    }
    
    try:
        # Extract archive
        with tarfile.open(archive_path, "r:gz") as tar:
            tar.extractall(restore_path)
        
        # Find the backup directory inside (it's named madmin_backup_TIMESTAMP)
        extracted_dirs = [d for d in os.listdir(restore_path) if d.startswith("madmin_backup")]
        if not extracted_dirs:
            result["errors"].append("Invalid backup archive structure")
            return result
        
        backup_path = os.path.join(restore_path, extracted_dirs[0])
        
        # 1. Restore database
        db_result = await restore_database(backup_path)
        result["database_restored"] = db_result
        if not db_result:
            result["errors"].append("Database restore failed or no database in backup")
        
        # 2. Restore modules
        modules_result = restore_modules(backup_path)
        result["modules_restored"] = modules_result["modules"]
        result["staging_restored"] = modules_result["staging"]
        
        # 3. Restore external paths
        external_count = restore_external_paths(backup_path)
        result["external_restored"] = external_count
        
        result["success"] = result["database_restored"] or result["modules_restored"] > 0
        
    except Exception as e:
        logger.error(f"Restore failed: {e}")
        result["errors"].append(str(e))
    finally:
        # Cleanup temp directory
        shutil.rmtree(restore_path, ignore_errors=True)
    
    return result
