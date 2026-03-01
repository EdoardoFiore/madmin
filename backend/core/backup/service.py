"""
MADMIN Backup Service — Config Export/Import

Handles:
- Configuration export (JSON-based, cross-version compatible)
- Configuration import with preview
- Remote upload/download (SFTP/FTP)
- Scheduled export via APScheduler

Replaces the old pg_dump approach with declarative JSON export.
Only irrecoverable files (PKI, certs, keys) are included — everything else
is regenerated from DB by post_restore hooks.
"""
import os
import glob
import json
import shutil
import asyncio
import tarfile
import logging
import importlib.util
import subprocess
import threading
from datetime import datetime
from typing import Optional, List, Dict, Any
from pathlib import Path
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, text, delete

from config import get_settings, MADMIN_VERSION

logger = logging.getLogger(__name__)

# Backup configuration
BACKUP_DIR = os.environ.get("MADMIN_BACKUP_DIR", "/opt/madmin/backups")
IMPORTS_DIR = os.environ.get("MADMIN_IMPORTS_DIR", "/opt/madmin/data/imports")
MAX_LOCAL_BACKUPS = int(os.environ.get("MADMIN_MAX_BACKUPS", "5"))

settings = get_settings()


def ensure_backup_dir():
    """Ensure backup directory exists."""
    os.makedirs(BACKUP_DIR, exist_ok=True)
    return BACKUP_DIR


def ensure_imports_dir():
    """Ensure imports directory exists."""
    os.makedirs(IMPORTS_DIR, exist_ok=True)
    return IMPORTS_DIR


# ============== CONFIG EXPORT ==============


async def export_config(session: AsyncSession) -> str:
    """
    Export full configuration as a portable tar.gz archive.
    
    Contents:
    - config_manifest.json (version, timestamp, active modules)
    - core/users.json (users + permissions)
    - core/firewall.json (machine firewall rules)  
    - core/settings.json (SystemSettings + SMTP + Backup)
    - modules/{id}/data.json (module DB data)
    - modules/{id}/files/ (irrecoverable filesystem files)
    
    Returns path to created archive.
    """
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    export_name = f"madmin-config-{MADMIN_VERSION}-{timestamp}"
    export_path = os.path.join(ensure_backup_dir(), export_name)
    os.makedirs(export_path, exist_ok=True)
    
    try:
        # --- Config manifest ---
        active_modules = await _get_active_modules(session)
        manifest = {
            "madmin_version": MADMIN_VERSION,
            "timestamp": datetime.now().isoformat(),
            "active_modules": [m["id"] for m in active_modules]
        }
        _write_json(os.path.join(export_path, "config_manifest.json"), manifest)
        
        # --- Core data ---
        core_dir = os.path.join(export_path, "core")
        os.makedirs(core_dir, exist_ok=True)
        
        # Users + permissions
        users_data = await _export_users(session)
        _write_json(os.path.join(core_dir, "users.json"), users_data)
        logger.info(f"Exported {len(users_data)} users")
        
        # Firewall rules
        firewall_data = await _export_firewall_rules(session)
        _write_json(os.path.join(core_dir, "firewall.json"), firewall_data)
        logger.info(f"Exported {len(firewall_data)} firewall rules")
        
        # Settings
        settings_data = await _export_settings(session)
        _write_json(os.path.join(core_dir, "settings.json"), settings_data)
        logger.info("Exported system settings")
        
        # --- Module data ---
        modules_dir_path = os.path.join(export_path, "modules")
        os.makedirs(modules_dir_path, exist_ok=True)
        
        for mod_info in active_modules:
            module_id = mod_info["id"]
            module_export_dir = os.path.join(modules_dir_path, module_id)
            os.makedirs(module_export_dir, exist_ok=True)
            
            # Load manifest for config_export settings
            mod_manifest = _load_module_manifest(module_id)
            if not mod_manifest:
                continue
            
            config_export = mod_manifest.get("config_export", {})
            
            # Export DB tables
            tables = config_export.get("tables", [])
            if tables:
                table_data = await _export_module_tables(session, tables)
                _write_json(os.path.join(module_export_dir, "data.json"), table_data)
                total_rows = sum(len(rows) for rows in table_data.values())
                logger.info(f"Exported {total_rows} rows from {len(tables)} tables for {module_id}")
            
            # Copy irrecoverable files
            irrecoverable = config_export.get("irrecoverable_files", [])
            if irrecoverable:
                files_dir = os.path.join(module_export_dir, "files")
                os.makedirs(files_dir, exist_ok=True)
                _copy_irrecoverable_files(irrecoverable, files_dir)
                logger.info(f"Copied irrecoverable files for {module_id}")
        
        # --- Create archive ---
        archive_name = f"{export_name}.tar.gz"
        archive_path = os.path.join(BACKUP_DIR, archive_name)
        with tarfile.open(archive_path, "w:gz") as tar:
            tar.add(export_path, arcname=export_name)
        
        logger.info(f"Config export created: {archive_path}")
        return archive_path
    
    finally:
        # Cleanup temp directory
        shutil.rmtree(export_path, ignore_errors=True)


# ============== CONFIG PREVIEW ==============


async def preview_config(archive_path: str) -> dict:
    """
    Preview contents of a config archive without applying.
    
    Returns structured data divided into sections for the frontend:
    - source_version, timestamp
    - core: users, firewall rules count, settings
    - modules: per-module summary
    """
    if not os.path.exists(archive_path):
        return {"error": "File non trovato"}
    
    try:
        with tarfile.open(archive_path, "r:gz") as tar:
            members = tar.getnames()
            
            # Find root dir
            root_dir = members[0].split("/")[0] if members else ""
            
            # Read config_manifest.json
            manifest_data = _read_json_from_tar(tar, f"{root_dir}/config_manifest.json")
            if not manifest_data:
                return {"error": "Archivio non valido: config_manifest.json mancante"}
            
            result = {
                "source_version": manifest_data.get("madmin_version", "sconosciuta"),
                "timestamp": manifest_data.get("timestamp", ""),
                "current_version": MADMIN_VERSION,
                "core": {},
                "modules": {}
            }
            
            # Core data preview
            users_data = _read_json_from_tar(tar, f"{root_dir}/core/users.json")
            if users_data:
                result["core"]["users"] = [
                    {
                        "username": u.get("username"),
                        "is_superuser": u.get("is_superuser", False),
                        "is_active": u.get("is_active", True)
                    }
                    for u in users_data
                ]
            
            firewall_data = _read_json_from_tar(tar, f"{root_dir}/core/firewall.json")
            result["core"]["firewall_rules"] = len(firewall_data) if firewall_data else 0
            
            settings_data = _read_json_from_tar(tar, f"{root_dir}/core/settings.json")
            if settings_data:
                sys_settings = settings_data.get("system", {})
                result["core"]["settings"] = {
                    "company_name": sys_settings.get("company_name", ""),
                    "primary_color": sys_settings.get("primary_color", "")
                }
            
            # Module data preview
            for module_id in manifest_data.get("active_modules", []):
                mod_data = _read_json_from_tar(tar, f"{root_dir}/modules/{module_id}/data.json")
                if mod_data:
                    mod_summary = {}
                    for table_name, rows in mod_data.items():
                        mod_summary[table_name] = len(rows)
                    result["modules"][module_id] = {
                        "tables": mod_summary,
                        "has_files": any(
                            m.startswith(f"{root_dir}/modules/{module_id}/files/")
                            for m in members
                        )
                    }
            
            return result
    
    except Exception as e:
        logger.error(f"Preview failed: {e}")
        return {"error": f"Errore durante la preview: {str(e)}"}


# ============== CONFIG IMPORT ==============


async def import_config(session: AsyncSession, archive_path: str) -> dict:
    """
    Import configuration from a config archive.
    
    Steps:
    1. Extract and validate archive
    2. Import core data (users, firewall, settings)
    3. For each module: activate → insert DB data → restore files → post_restore hook
    
    Returns detailed result dict.
    """
    if not os.path.exists(archive_path):
        return {"success": False, "errors": ["File non trovato"]}
    
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    restore_path = os.path.join(BACKUP_DIR, f"import_temp_{timestamp}")
    os.makedirs(restore_path, exist_ok=True)
    
    result = {
        "success": False,
        "users_imported": 0,
        "firewall_rules_imported": 0,
        "settings_restored": False,
        "modules_imported": [],
        "errors": [],
        "warnings": []
    }
    
    try:
        # Extract
        with tarfile.open(archive_path, "r:gz") as tar:
            tar.extractall(restore_path)
        
        # Find root dir
        extracted = os.listdir(restore_path)
        if not extracted:
            result["errors"].append("Archivio vuoto")
            return result
        
        root_path = os.path.join(restore_path, extracted[0])
        
        # Read manifest
        manifest_path_file = os.path.join(root_path, "config_manifest.json")
        if not os.path.exists(manifest_path_file):
            result["errors"].append("config_manifest.json mancante")
            return result
        
        with open(manifest_path_file) as f:
            config_manifest = json.load(f)
        
        source_version = config_manifest.get("madmin_version", "sconosciuta")
        if source_version != MADMIN_VERSION:
            result["warnings"].append(
                f"Versione sorgente ({source_version}) diversa da quella corrente ({MADMIN_VERSION})"
            )
        
        # --- Import core ---
        core_path = os.path.join(root_path, "core")
        
        # 1. Users
        users_file = os.path.join(core_path, "users.json")
        if os.path.exists(users_file):
            count = await _import_users(session, users_file)
            result["users_imported"] = count
            logger.info(f"Imported {count} users")
        
        # 2. Firewall rules
        firewall_file = os.path.join(core_path, "firewall.json")
        if os.path.exists(firewall_file):
            count = await _import_firewall_rules(session, firewall_file)
            result["firewall_rules_imported"] = count
            logger.info(f"Imported {count} firewall rules")
        
        # 3. Settings
        settings_file = os.path.join(core_path, "settings.json")
        if os.path.exists(settings_file):
            await _import_settings(session, settings_file)
            result["settings_restored"] = True
            logger.info("Imported settings")
        
        await session.commit()
        
        # --- Import modules ---
        from core.modules.loader import module_loader
        
        modules_path = os.path.join(root_path, "modules")
        for module_id in config_manifest.get("active_modules", []):
            module_dir = os.path.join(modules_path, module_id)
            if not os.path.isdir(module_dir):
                result["warnings"].append(f"Dati modulo '{module_id}' non trovati nell'archivio")
                continue
            
            mod_result = {"id": module_id, "tables_imported": 0, "files_restored": False}
            
            try:
                # Activate module if not active (runs migrations + post_install)
                activate_result = await module_loader.activate_module(session, module_id)
                if not activate_result.get("success") and "già attivo" not in activate_result.get("message", ""):
                    result["errors"].append(
                        f"Attivazione modulo '{module_id}' fallita: {activate_result.get('error', '')}"
                    )
                    continue
                
                # Import DB data
                data_file = os.path.join(module_dir, "data.json")
                if os.path.exists(data_file):
                    rows = await _import_module_tables(session, data_file)
                    mod_result["tables_imported"] = rows
                
                # Restore irrecoverable files
                files_dir = os.path.join(module_dir, "files")
                if os.path.isdir(files_dir):
                    _restore_irrecoverable_files(files_dir)
                    mod_result["files_restored"] = True
                
                await session.commit()
                
                # Execute post_restore hook
                mod_manifest = _load_module_manifest(module_id)
                if mod_manifest:
                    config_export = mod_manifest.get("config_export", {})
                    post_restore = config_export.get("post_restore")
                    if post_restore:
                        module_path = Path(settings.modules_dir) / module_id
                        await _execute_restore_hook(post_restore, module_path, session)
                
                result["modules_imported"].append(mod_result)
                logger.info(f"Imported module: {module_id}")
                
            except Exception as e:
                logger.error(f"Failed to import module {module_id}: {e}", exc_info=True)
                result["errors"].append(f"Errore importazione modulo '{module_id}': {str(e)}")
                # Rollback to recover the session for subsequent modules
                try:
                    await session.rollback()
                except Exception:
                    pass
        
        result["success"] = len(result["errors"]) == 0
        
        # Schedule auto-restart after successful import
        if result["success"]:
            _schedule_restart()
        
    except Exception as e:
        logger.error(f"Config import failed: {e}", exc_info=True)
        result["errors"].append(f"Errore generale: {str(e)}")
    finally:
        shutil.rmtree(restore_path, ignore_errors=True)
    
    return result


def _schedule_restart():
    """Schedule MADMIN service restart after a short delay (allows HTTP response to complete)."""
    from core.system.service import SystemService
    SystemService.restart_madmin(3)


# ============== SCHEDULED BACKUP (uses export_config) ==============


async def run_backup(
    session: AsyncSession,
    remote_protocol: Optional[str] = None,
    remote_host: Optional[str] = None,
    remote_port: int = 22,
    remote_user: Optional[str] = None,
    remote_password: Optional[str] = None,
    remote_path: str = "/",
    retention_days: int = 30
) -> dict:
    """
    Run a full backup operation using config export.
    
    Returns dict with status and details.
    """
    result = {
        "success": False,
        "timestamp": datetime.now().strftime("%Y%m%d_%H%M%S"),
        "archive": None,
        "remote_uploaded": False,
        "errors": []
    }
    
    try:
        # Export config
        archive_path = await export_config(session)
        result["archive"] = archive_path
        
        # Upload to remote if configured
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
                result["errors"].append("Upload remoto fallito")
        
        # Cleanup old exports
        cleanup_old_backups(retention_days)
        
        result["success"] = len(result["errors"]) == 0
    
    except Exception as e:
        logger.error(f"Backup failed: {e}", exc_info=True)
        result["errors"].append(str(e))
    
    return result


# ============== ARCHIVE MANAGEMENT ==============


def create_archive(backup_path: str, archive_name: str) -> Optional[str]:
    """Create tar.gz archive."""
    try:
        archive_path = os.path.join(BACKUP_DIR, archive_name)
        with tarfile.open(archive_path, "w:gz") as tar:
            tar.add(backup_path, arcname=os.path.basename(backup_path))
        return archive_path
    except Exception as e:
        logger.error(f"Archive creation failed: {e}")
        return None


def cleanup_old_backups(retention_days: int = 30):
    """
    Remove old backups based on retention policy.
    retention_days=0 means keep forever.
    """
    if retention_days <= 0:
        return
    
    backup_dir = ensure_backup_dir()
    now = datetime.now()
    
    for filename in os.listdir(backup_dir):
        if not filename.endswith(".tar.gz"):
            continue
        
        filepath = os.path.join(backup_dir, filename)
        file_mtime = datetime.fromtimestamp(os.path.getmtime(filepath))
        age_days = (now - file_mtime).days
        
        if age_days > retention_days:
            os.remove(filepath)
            logger.info(f"Cleaned up old backup: {filename} ({age_days} days old)")


def list_local_backups() -> List[dict]:
    """List all local backup archives."""
    backup_dir = ensure_backup_dir()
    backups = []
    
    for filename in sorted(os.listdir(backup_dir), reverse=True):
        if not filename.endswith(".tar.gz"):
            continue
        
        filepath = os.path.join(backup_dir, filename)
        stat = os.stat(filepath)
        backups.append({
            "filename": filename,
            "size_bytes": stat.st_size,
            "created_at": datetime.fromtimestamp(stat.st_mtime).isoformat()
        })
    
    return backups


def list_import_files() -> List[dict]:
    """List tar.gz files available in the imports directory (uploaded via SCP)."""
    imports_dir = ensure_imports_dir()
    files = []
    
    for filename in sorted(os.listdir(imports_dir), reverse=True):
        if not filename.endswith(".tar.gz"):
            continue
        
        filepath = os.path.join(imports_dir, filename)
        stat = os.stat(filepath)
        files.append({
            "filename": filename,
            "path": filepath,
            "size_bytes": stat.st_size,
            "created_at": datetime.fromtimestamp(stat.st_mtime).isoformat()
        })
    
    return files


# ============== REMOTE STORAGE (SFTP/FTP) ==============


async def upload_sftp(
    archive_path: str,
    host: str,
    port: int,
    username: str,
    password: str,
    remote_path: str
) -> bool:
    """Upload backup archive via SFTP."""
    try:
        import paramiko
        
        transport = paramiko.Transport((host, port))
        transport.connect(username=username, password=password)
        sftp = paramiko.SFTPClient.from_transport(transport)
        
        filename = os.path.basename(archive_path)
        remote_file = os.path.join(remote_path, filename).replace("\\", "/")
        
        sftp.put(archive_path, remote_file)
        
        sftp.close()
        transport.close()
        
        logger.info(f"Uploaded to SFTP: {remote_file}")
        return True
        
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
    """Upload backup archive via FTP."""
    try:
        from ftplib import FTP
        
        ftp = FTP()
        ftp.connect(host, port)
        ftp.login(username, password)
        
        if remote_path and remote_path != "/":
            ftp.cwd(remote_path)
        
        filename = os.path.basename(archive_path)
        with open(archive_path, "rb") as f:
            ftp.storbinary(f"STOR {filename}", f)
        
        ftp.quit()
        
        logger.info(f"Uploaded to FTP: {filename}")
        return True
        
    except Exception as e:
        logger.error(f"FTP upload failed: {e}")
        return False


# --- Remote listing ---

def list_remote_backups_sftp(
    host: str, port: int, username: str, password: str, remote_path: str
) -> List[dict]:
    """List backup files on remote SFTP server."""
    try:
        import paramiko
        
        transport = paramiko.Transport((host, port))
        transport.connect(username=username, password=password)
        sftp = paramiko.SFTPClient.from_transport(transport)
        
        files = []
        for entry in sftp.listdir_attr(remote_path):
            if entry.filename.endswith(".tar.gz"):
                files.append({
                    "filename": entry.filename,
                    "size_bytes": entry.st_size,
                    "mtime": datetime.fromtimestamp(entry.st_mtime).isoformat() if entry.st_mtime else None
                })
        
        sftp.close()
        transport.close()
        return files
    except Exception as e:
        logger.error(f"SFTP list failed: {e}")
        return []


def list_remote_backups_ftp(
    host: str, port: int, username: str, password: str, remote_path: str
) -> List[dict]:
    """List backup files on remote FTP server."""
    try:
        from ftplib import FTP
        
        ftp = FTP()
        ftp.connect(host, port)
        ftp.login(username, password)
        if remote_path and remote_path != "/":
            ftp.cwd(remote_path)
        
        files = []
        ftp.retrlines("LIST", lambda line: files.append(line))
        
        result = []
        for line in files:
            parts = line.split()
            if parts and parts[-1].endswith(".tar.gz"):
                size = int(parts[4]) if len(parts) > 4 else 0
                result.append({
                    "filename": parts[-1],
                    "size_bytes": size,
                    "mtime": None
                })
        
        ftp.quit()
        return result
    except Exception as e:
        logger.error(f"FTP list failed: {e}")
        return []


def list_remote_backups(
    protocol: str, host: str, port: int, username: str, password: str, remote_path: str
) -> List[dict]:
    """List backup files on remote server."""
    if protocol == "sftp":
        return list_remote_backups_sftp(host, port, username, password, remote_path)
    elif protocol == "ftp":
        return list_remote_backups_ftp(host, port, username, password, remote_path)
    return []


# --- Remote download ---

def download_remote_backup_sftp(
    host: str, port: int, username: str, password: str, remote_path: str, filename: str
) -> Optional[str]:
    """Download a backup file from remote SFTP server."""
    try:
        import paramiko
        
        transport = paramiko.Transport((host, port))
        transport.connect(username=username, password=password)
        sftp = paramiko.SFTPClient.from_transport(transport)
        
        remote_file = os.path.join(remote_path, filename).replace("\\", "/")
        local_path = os.path.join(ensure_backup_dir(), filename)
        
        sftp.get(remote_file, local_path)
        
        sftp.close()
        transport.close()
        
        logger.info(f"Downloaded from SFTP: {filename}")
        return local_path
    except Exception as e:
        logger.error(f"SFTP download failed: {e}")
        return None


def download_remote_backup_ftp(
    host: str, port: int, username: str, password: str, remote_path: str, filename: str
) -> Optional[str]:
    """Download a backup file from remote FTP server."""
    try:
        from ftplib import FTP
        
        ftp = FTP()
        ftp.connect(host, port)
        ftp.login(username, password)
        if remote_path and remote_path != "/":
            ftp.cwd(remote_path)
        
        local_path = os.path.join(ensure_backup_dir(), filename)
        with open(local_path, "wb") as f:
            ftp.retrbinary(f"RETR {filename}", f.write)
        
        ftp.quit()
        logger.info(f"Downloaded from FTP: {filename}")
        return local_path
    except Exception as e:
        logger.error(f"FTP download failed: {e}")
        return None


def download_remote_backup(
    protocol: str, host: str, port: int, username: str, password: str,
    remote_path: str, filename: str
) -> Optional[str]:
    """Download a backup file from remote server."""
    if protocol == "sftp":
        return download_remote_backup_sftp(host, port, username, password, remote_path, filename)
    elif protocol == "ftp":
        return download_remote_backup_ftp(host, port, username, password, remote_path, filename)
    return None


# --- Remote delete ---

def delete_remote_backup_sftp(
    host: str, port: int, username: str, password: str, remote_path: str, filename: str
) -> bool:
    """Delete a backup file from remote SFTP server."""
    try:
        import paramiko
        
        transport = paramiko.Transport((host, port))
        transport.connect(username=username, password=password)
        sftp = paramiko.SFTPClient.from_transport(transport)
        
        remote_file = os.path.join(remote_path, filename).replace("\\", "/")
        sftp.remove(remote_file)
        
        sftp.close()
        transport.close()
        
        logger.info(f"Deleted from SFTP: {filename}")
        return True
    except Exception as e:
        logger.error(f"SFTP delete failed: {e}")
        return False


def delete_remote_backup_ftp(
    host: str, port: int, username: str, password: str, remote_path: str, filename: str
) -> bool:
    """Delete a backup file from remote FTP server."""
    try:
        from ftplib import FTP
        
        ftp = FTP()
        ftp.connect(host, port)
        ftp.login(username, password)
        if remote_path and remote_path != "/":
            ftp.cwd(remote_path)
        
        ftp.delete(filename)
        ftp.quit()
        
        logger.info(f"Deleted from FTP: {filename}")
        return True
    except Exception as e:
        logger.error(f"FTP delete failed: {e}")
        return False


def delete_remote_backup(
    protocol: str, host: str, port: int, username: str, password: str,
    remote_path: str, filename: str
) -> bool:
    """Delete a backup file from remote server."""
    if protocol == "sftp":
        return delete_remote_backup_sftp(host, port, username, password, remote_path, filename)
    elif protocol == "ftp":
        return delete_remote_backup_ftp(host, port, username, password, remote_path, filename)
    return False


def cleanup_remote_backups(
    protocol: str, host: str, port: int, username: str, password: str,
    remote_path: str, retention_days: int
) -> int:
    """Remove old backups from remote storage based on retention policy."""
    if retention_days <= 0:
        return 0
    
    files = list_remote_backups(protocol, host, port, username, password, remote_path)
    deleted = 0
    now = datetime.now()
    
    for f in files:
        if f.get("mtime"):
            try:
                mtime = datetime.fromisoformat(f["mtime"])
                age = (now - mtime).days
                if age > retention_days:
                    if delete_remote_backup(protocol, host, port, username, password, remote_path, f["filename"]):
                        deleted += 1
            except Exception:
                pass
    
    return deleted


# ============== INTERNAL HELPERS ==============


def _write_json(path: str, data: Any):
    """Write data as JSON to file."""
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, default=str, ensure_ascii=False)


def _read_json_from_tar(tar: tarfile.TarFile, member_name: str) -> Any:
    """Read a JSON file from a tar archive."""
    try:
        member = tar.getmember(member_name)
        f = tar.extractfile(member)
        if f:
            return json.loads(f.read().decode("utf-8"))
    except (KeyError, json.JSONDecodeError):
        pass
    return None


def _load_module_manifest(module_id: str) -> Optional[dict]:
    """Load a module's manifest.json as dict."""
    manifest_path = Path(settings.modules_dir) / module_id / "manifest.json"
    if not manifest_path.exists():
        return None
    try:
        with open(manifest_path) as f:
            return json.load(f)
    except Exception:
        return None


async def _get_active_modules(session: AsyncSession) -> List[dict]:
    """Get list of active modules from DB."""
    from core.modules.models import InstalledModule
    
    result = await session.execute(
        select(InstalledModule).where(InstalledModule.enabled == True)
    )
    modules = result.scalars().all()
    return [{"id": m.id, "name": m.name, "version": m.version} for m in modules]


# --- Export helpers ---


async def _export_users(session: AsyncSession) -> List[dict]:
    """Export all users with their permissions."""
    from core.auth.models import User, UserPermission
    
    result = await session.execute(select(User))
    users = result.scalars().all()
    
    users_data = []
    for user in users:
        # Get permission slugs
        perms_result = await session.execute(
            select(UserPermission.permission_slug).where(UserPermission.user_id == user.id)
        )
        permission_slugs = [row[0] for row in perms_result.all()]
        
        users_data.append({
            "username": user.username,
            "email": user.email,
            "hashed_password": user.hashed_password,
            "is_active": user.is_active,
            "is_superuser": user.is_superuser,
            "totp_secret": user.totp_secret,
            "totp_enabled": user.totp_enabled,
            "totp_enforced": user.totp_enforced,
            "backup_codes": user.backup_codes,
            "preferences": user.preferences,
            "permissions": permission_slugs
        })
    
    return users_data


async def _export_firewall_rules(session: AsyncSession) -> List[dict]:
    """Export machine firewall rules using the orchestrator."""
    from core.firewall.models import MachineFirewallRule
    
    result = await session.execute(
        select(MachineFirewallRule).order_by(MachineFirewallRule.order)
    )
    rules = result.scalars().all()
    
    return [
        {
            "chain": r.chain,
            "action": r.action,
            "protocol": r.protocol,
            "source": r.source,
            "destination": r.destination,
            "port": r.port,
            "in_interface": r.in_interface,
            "out_interface": r.out_interface,
            "state": r.state,
            "limit_rate": r.limit_rate,
            "limit_burst": r.limit_burst,
            "to_destination": r.to_destination,
            "to_source": r.to_source,
            "to_ports": r.to_ports,
            "log_prefix": r.log_prefix,
            "log_level": r.log_level,
            "reject_with": r.reject_with,
            "comment": r.comment,
            "table_name": r.table_name,
            "order": r.order,
            "enabled": r.enabled
        }
        for r in rules
    ]


async def _export_settings(session: AsyncSession) -> dict:
    """Export all singleton settings tables."""
    from core.settings.models import SystemSettings, SMTPSettings, BackupSettings
    
    result = {}
    
    # SystemSettings
    sys = await session.execute(select(SystemSettings).where(SystemSettings.id == 1))
    sys_row = sys.scalar_one_or_none()
    if sys_row:
        result["system"] = {
            "company_name": sys_row.company_name,
            "primary_color": sys_row.primary_color,
            "logo_url": sys_row.logo_url,
            "favicon_url": sys_row.favicon_url,
            "support_url": sys_row.support_url
        }
    
    # SMTPSettings
    smtp = await session.execute(select(SMTPSettings).where(SMTPSettings.id == 1))
    smtp_row = smtp.scalar_one_or_none()
    if smtp_row:
        result["smtp"] = {
            "smtp_host": smtp_row.smtp_host,
            "smtp_port": smtp_row.smtp_port,
            "smtp_encryption": smtp_row.smtp_encryption,
            "smtp_username": smtp_row.smtp_username,
            "smtp_password": smtp_row.smtp_password,
            "sender_email": smtp_row.sender_email,
            "sender_name": smtp_row.sender_name,
            "public_url": smtp_row.public_url
        }
    
    # BackupSettings
    bk = await session.execute(select(BackupSettings).where(BackupSettings.id == 1))
    bk_row = bk.scalar_one_or_none()
    if bk_row:
        result["backup"] = {
            "enabled": bk_row.enabled,
            "frequency": bk_row.frequency,
            "time": bk_row.time,
            "remote_protocol": bk_row.remote_protocol,
            "remote_host": bk_row.remote_host,
            "remote_port": bk_row.remote_port,
            "remote_user": bk_row.remote_user,
            "remote_password": bk_row.remote_password,
            "remote_path": bk_row.remote_path,
            "retention_days": bk_row.retention_days
        }
    
    return result


async def _export_module_tables(session: AsyncSession, tables: List[str]) -> dict:
    """Export module DB tables as dicts. Uses raw SQL to be schema-agnostic."""
    result = {}
    
    for table_name in tables:
        try:
            rows = await session.execute(text(f'SELECT * FROM "{table_name}"'))
            columns = rows.keys()
            data = [dict(zip(columns, row)) for row in rows.fetchall()]
            result[table_name] = data
        except Exception as e:
            logger.warning(f"Failed to export table {table_name}: {e}")
            result[table_name] = []
    
    return result


def _copy_irrecoverable_files(patterns: List[str], dest_dir: str):
    """Copy irrecoverable files matching glob patterns to dest directory."""
    for pattern in patterns:
        matched_paths = glob.glob(pattern)
        if not matched_paths:
            logger.info(f"No files matched pattern: {pattern}")
            continue
        
        for src_path in matched_paths:
            if not os.path.exists(src_path):
                continue
            
            # Preserve full path structure under dest
            # e.g., /etc/openvpn/server/inst1/pki → dest/etc/openvpn/server/inst1/pki
            rel_path = src_path.lstrip("/")
            dest_path = os.path.join(dest_dir, rel_path)
            
            if os.path.isdir(src_path):
                shutil.copytree(src_path, dest_path, dirs_exist_ok=True)
            else:
                os.makedirs(os.path.dirname(dest_path), exist_ok=True)
                shutil.copy2(src_path, dest_path)
            
            logger.info(f"Copied irrecoverable: {src_path}")


# --- Import helpers ---


async def _import_users(session: AsyncSession, users_file: str) -> int:
    """Import users from JSON. Creates if new, updates if existing (by username)."""
    from core.auth.models import User, UserPermission, Permission
    
    with open(users_file) as f:
        users_data = json.load(f)
    
    count = 0
    for u_data in users_data:
        # Check if user exists
        result = await session.execute(
            select(User).where(User.username == u_data["username"])
        )
        existing = result.scalar_one_or_none()
        
        if existing:
            # Update existing user (preserve ID)
            existing.email = u_data.get("email") or existing.email
            existing.hashed_password = u_data.get("hashed_password", existing.hashed_password)
            existing.is_active = u_data.get("is_active", existing.is_active)
            existing.is_superuser = u_data.get("is_superuser", existing.is_superuser)
            existing.totp_secret = u_data.get("totp_secret") or existing.totp_secret
            existing.totp_enabled = u_data.get("totp_enabled", existing.totp_enabled)
            existing.totp_enforced = u_data.get("totp_enforced", existing.totp_enforced)
            existing.backup_codes = u_data.get("backup_codes") or existing.backup_codes
            existing.preferences = u_data.get("preferences", existing.preferences)
            user_id = existing.id
        else:
            # Create new user
            new_user = User(
                username=u_data["username"],
                email=u_data.get("email"),
                hashed_password=u_data.get("hashed_password", ""),
                is_active=u_data.get("is_active", True),
                is_superuser=u_data.get("is_superuser", False),
                totp_secret=u_data.get("totp_secret"),
                totp_enabled=u_data.get("totp_enabled", False),
                totp_enforced=u_data.get("totp_enforced", False),
                backup_codes=u_data.get("backup_codes"),
                preferences=u_data.get("preferences", "{}")
            )
            session.add(new_user)
            await session.flush()
            user_id = new_user.id
        
        # Assign permissions (only those that exist in current system)
        for perm_slug in u_data.get("permissions", []):
            perm_exists = await session.execute(
                select(Permission).where(Permission.slug == perm_slug)
            )
            if perm_exists.scalar_one_or_none():
                # Check if assignment already exists
                existing_up = await session.execute(
                    select(UserPermission).where(
                        UserPermission.user_id == user_id,
                        UserPermission.permission_slug == perm_slug
                    )
                )
                if not existing_up.scalar_one_or_none():
                    session.add(UserPermission(user_id=user_id, permission_slug=perm_slug))
        
        count += 1
    
    return count


async def _import_firewall_rules(session: AsyncSession, firewall_file: str) -> int:
    """Import firewall rules. Replaces all existing rules."""
    from core.firewall.models import MachineFirewallRule
    
    with open(firewall_file) as f:
        rules_data = json.load(f)
    
    # Delete existing rules
    await session.execute(delete(MachineFirewallRule))
    
    count = 0
    exclude_fields = {"id", "created_at", "updated_at"}
    
    for rule_dict in rules_data:
        clean_data = {k: v for k, v in rule_dict.items() if k not in exclude_fields}
        rule = MachineFirewallRule(**clean_data)
        session.add(rule)
        count += 1
    
    return count


async def _import_settings(session: AsyncSession, settings_file: str):
    """Import settings. Merges with existing singletons."""
    from core.settings.models import SystemSettings, SMTPSettings, BackupSettings
    
    with open(settings_file) as f:
        data = json.load(f)
    
    if "system" in data:
        sys_result = await session.execute(select(SystemSettings).where(SystemSettings.id == 1))
        sys_row = sys_result.scalar_one_or_none()
        if sys_row:
            for k, v in data["system"].items():
                if hasattr(sys_row, k) and v is not None:
                    setattr(sys_row, k, v)
        else:
            session.add(SystemSettings(id=1, **data["system"]))
    
    if "smtp" in data:
        smtp_result = await session.execute(select(SMTPSettings).where(SMTPSettings.id == 1))
        smtp_row = smtp_result.scalar_one_or_none()
        if smtp_row:
            for k, v in data["smtp"].items():
                if hasattr(smtp_row, k) and v is not None:
                    setattr(smtp_row, k, v)
        else:
            session.add(SMTPSettings(id=1, **data["smtp"]))
    
    if "backup" in data:
        bk_result = await session.execute(select(BackupSettings).where(BackupSettings.id == 1))
        bk_row = bk_result.scalar_one_or_none()
        if bk_row:
            for k, v in data["backup"].items():
                if hasattr(bk_row, k) and v is not None:
                    setattr(bk_row, k, v)
        else:
            session.add(BackupSettings(id=1, **data["backup"]))


async def _import_module_tables(session: AsyncSession, data_file: str) -> int:
    """Import module DB tables from JSON. Uses raw SQL INSERT for schema flexibility.
    
    Handles foreign key ordering: deletes children first, inserts parents first.
    """
    with open(data_file) as f:
        tables_data = json.load(f)
    
    if not tables_data:
        return 0
    
    total_rows = 0
    table_names = list(tables_data.keys())
    
    # Sort tables by FK dependencies using SQLAlchemy metadata reflection
    sorted_tables = await _get_sorted_tables(session, table_names)
    
    # Delete in reverse order (children first, parents last)
    for table_name in reversed(sorted_tables):
        try:
            await session.execute(text(f'DELETE FROM "{table_name}"'))
            logger.info(f"Cleared table: {table_name}")
        except Exception as e:
            logger.error(f"Failed to clear table {table_name}: {e}")
            raise
    
    # Insert in order (parents first, children last)
    for table_name in sorted_tables:
        rows = tables_data.get(table_name, [])
        if not rows:
            continue
        
        for row in rows:
            processed_row = {k: _convert_value(v) for k, v in row.items()}
            
            columns = list(processed_row.keys())
            placeholders = [f":{col}" for col in columns]
            col_list = ", ".join(f'"{c}"' for c in columns)
            sql = f'INSERT INTO "{table_name}" ({col_list}) VALUES ({", ".join(placeholders)})'
            
            try:
                await session.execute(text(sql), processed_row)
                total_rows += 1
            except Exception as e:
                logger.error(f"Failed to insert row in {table_name}: {e}")
                logger.error(f"Row data: {processed_row}")
                raise
    
    logger.info(f"Module tables imported: {total_rows} rows across {len(sorted_tables)} tables")
    return total_rows


# Regex for datetime strings: "2026-03-01 14:52:36.077484" or "2026-03-01T14:52:36.077484"
import re
_DATETIME_RE = re.compile(r'^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}')


def _convert_value(v):
    """Convert a JSON value to a Python type suitable for asyncpg binding.
    
    Handles:
    - list/dict → json.dumps() for JSON/JSONB columns
    - datetime strings → datetime objects for TIMESTAMP columns
    - everything else passes through
    """
    if v is None:
        return v
    if isinstance(v, (list, dict)):
        return json.dumps(v)
    if isinstance(v, str) and _DATETIME_RE.match(v):
        try:
            # Handle both "2026-03-01 14:52:36" and "2026-03-01T14:52:36" formats
            return datetime.fromisoformat(v.replace(" ", "T"))
        except (ValueError, TypeError):
            return v
    return v


async def _get_sorted_tables(session: AsyncSession, table_names: list) -> list:
    """Sort table names by FK dependencies (parents before children).
    
    Uses information_schema to discover FK relationships.
    Tables with no FK on others come first.
    """
    if len(table_names) <= 1:
        return table_names
    
    # Get FK relationships between our tables
    deps = {t: set() for t in table_names}
    
    try:
        # Query FK constraints from the database
        for table_name in table_names:
            result = await session.execute(text("""
                SELECT ccu.table_name AS referenced_table
                FROM information_schema.table_constraints AS tc
                JOIN information_schema.constraint_column_usage AS ccu
                    ON tc.constraint_name = ccu.constraint_name
                WHERE tc.constraint_type = 'FOREIGN KEY'
                    AND tc.table_name = :table_name
                    AND ccu.table_name != :table_name
            """), {"table_name": table_name})
            
            for row in result:
                referenced = row[0]
                if referenced in deps:
                    deps[table_name].add(referenced)  # table_name depends on referenced
    except Exception as e:
        logger.warning(f"Could not determine FK ordering, using original order: {e}")
        return table_names
    
    # Topological sort (Kahn's algorithm)
    sorted_list = []
    no_deps = [t for t in table_names if not deps[t]]
    
    while no_deps:
        table = no_deps.pop(0)
        sorted_list.append(table)
        for t in table_names:
            if table in deps.get(t, set()):
                deps[t].discard(table)
                if not deps[t]:
                    no_deps.append(t)
    
    # Add any remaining (circular deps or unresolved)
    for t in table_names:
        if t not in sorted_list:
            sorted_list.append(t)
    
    logger.info(f"Table import order: {sorted_list}")
    return sorted_list


def _restore_irrecoverable_files(files_dir: str):
    """Restore irrecoverable files from backup to their original paths."""
    for root, dirs, files in os.walk(files_dir):
        for filename in files:
            src = os.path.join(root, filename)
            # Reconstruct original path
            rel_path = os.path.relpath(src, files_dir)
            dest = os.path.join("/", rel_path)
            
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            shutil.copy2(src, dest)
            logger.info(f"Restored irrecoverable file: {dest}")


async def _execute_restore_hook(hook_path: str, module_path: Path, session: AsyncSession):
    """Execute a module's post_restore hook."""
    full_path = module_path / hook_path
    
    if not full_path.exists():
        logger.warning(f"Post-restore hook not found: {full_path}")
        return
    
    try:
        spec = importlib.util.spec_from_file_location("hook_post_restore", full_path)
        if spec and spec.loader:
            hook_module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(hook_module)
            
            if hasattr(hook_module, "run"):
                result = hook_module.run(session)
                if asyncio.iscoroutine(result):
                    await result
                logger.info(f"Executed post_restore hook: {full_path}")
    except Exception as e:
        logger.error(f"Post-restore hook failed: {e}", exc_info=True)
