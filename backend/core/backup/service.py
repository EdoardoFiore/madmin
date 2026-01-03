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
        db_url = os.environ.get("DATABASE_URL", "")
        if not db_url:
            logger.error("DATABASE_URL not set for backup")
            return False
        
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
            "/etc/nginx/sites-available/madmin",
            "/etc/systemd/system/madmin.service",
        ]
        
        import shutil
        for filepath in files_to_backup:
            if os.path.exists(filepath):
                dest = os.path.join(config_dir, os.path.basename(filepath))
                shutil.copy2(filepath, dest)
                logger.info(f"Backed up {filepath}")
        
        # Also backup modules directory structure
        modules_dir = "/opt/madmin/modules"
        if os.path.exists(modules_dir):
            shutil.copytree(
                modules_dir, 
                os.path.join(config_dir, "modules"),
                dirs_exist_ok=True
            )
        
        return True
        
    except Exception as e:
        logger.error(f"Config backup failed: {e}")
        return False


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
