"""
MADMIN Backup Router

API endpoints for config export/import and backup management.
"""
import os
import logging
from datetime import datetime
from typing import Optional, List
from pathlib import Path
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form, Body
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from core.database import get_session
from core.auth.dependencies import require_permission
from core.auth.models import User
from core.settings.models import BackupSettings
from .service import (
    export_config, import_config, preview_config,
    run_backup, list_local_backups, list_import_files,
    BACKUP_DIR, IMPORTS_DIR, ensure_backup_dir,
    is_archive_name,
    list_remote_backups, download_remote_backup, delete_remote_backup, cleanup_remote_backups,
    RemoteNotConfigured,
)
from .remote import HostKeyMismatch

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/backup", tags=["Backup"])


class RestoreOptions(BaseModel):
    """Body of the restore/preview calls on files already on the server."""
    # In the body, never in the URL: URLs end up in access logs
    passphrase: Optional[str] = None


def _passphrase(options: Optional[RestoreOptions]) -> Optional[str]:
    return options.passphrase if options else None


def _raise_archive_error(result: dict) -> None:
    """Map a preview error to HTTP: 400, with passphrase_required for the UI."""
    raise HTTPException(status_code=400, detail={
        "message": result["error"],
        "passphrase_required": result.get("passphrase_required", False),
    })


# ============== CONFIG EXPORT ==============


@router.post("/export")
async def export_configuration(
    download: bool = False,
    current_user: User = Depends(require_permission("backup.manage")),
    session: AsyncSession = Depends(get_session)
):
    """Export full configuration as tar.gz archive.
    
    Without ?download=true: saves locally and returns JSON with filename.
    With ?download=true: returns the file for browser download.
    """
    try:
        archive_path = await export_config(session)
        
        if download:
            return FileResponse(
                path=archive_path,
                filename=os.path.basename(archive_path),
                media_type="application/octet-stream"
            )
        
        return {
            "success": True,
            "filename": os.path.basename(archive_path),
            "path": str(archive_path)
        }
    except Exception as e:
        logger.error(f"Export failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Export failed")


# ============== CONFIG IMPORT ==============


@router.post("/import/preview")
async def preview_import(
    file: UploadFile = File(...),
    passphrase: Optional[str] = Form(None),
    current_user: User = Depends(require_permission("backup.restore"))
):
    """Preview contents of a config archive without applying."""
    if not is_archive_name(file.filename or ""):
        raise HTTPException(status_code=400, detail="File must be a .tar.gz or .tar.gz.enc archive")
    
    # Save uploaded file temporarily
    temp_path = os.path.join(BACKUP_DIR, f"_preview_temp_{Path(file.filename).name}")
    try:
        ensure_backup_dir()
        with open(temp_path, "wb") as f:
            content = await file.read()
            f.write(content)
        
        result = await preview_config(temp_path, passphrase)

        if "error" in result:
            _raise_archive_error(result)

        return result
    finally:
        try:
            os.remove(temp_path)
        except FileNotFoundError:
            pass


@router.post("/import")
async def import_configuration(
    file: UploadFile = File(...),
    passphrase: Optional[str] = Form(None),
    current_user: User = Depends(require_permission("backup.restore")),
    session: AsyncSession = Depends(get_session)
):
    """Import configuration from uploaded tar.gz archive."""
    if not is_archive_name(file.filename or ""):
        raise HTTPException(status_code=400, detail="File must be a .tar.gz or .tar.gz.enc archive")
    
    # Save uploaded file
    temp_path = os.path.join(BACKUP_DIR, f"_import_{Path(file.filename).name}")
    try:
        ensure_backup_dir()
        with open(temp_path, "wb") as f:
            content = await file.read()
            f.write(content)
        
        result = await import_config(session, temp_path, passphrase)

        if not result.get("success"):
            raise HTTPException(status_code=400, detail={
                "message": "Import completed with errors",
                "result": result
            })
        
        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Import failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Import failed")
    finally:
        try:
            os.remove(temp_path)
        except FileNotFoundError:
            pass


@router.post("/import/from-file")
async def import_from_scp_file(
    filename: str,
    options: Optional[RestoreOptions] = Body(None),
    current_user: User = Depends(require_permission("backup.restore")),
    session: AsyncSession = Depends(get_session)
):
    """Import configuration from file uploaded via SCP to imports directory."""
    safe_name = Path(filename).name
    if not is_archive_name(safe_name):
        raise HTTPException(status_code=400, detail="File must be a .tar.gz or .tar.gz.enc archive")
    
    file_path = os.path.join(IMPORTS_DIR, safe_name)
    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="File not found in imports folder")
    
    result = await import_config(session, file_path, _passphrase(options))
    return result


@router.get("/import/files")
async def list_scp_import_files(
    current_user: User = Depends(require_permission("backup.view"))
):
    """List config archives available in the imports directory (uploaded via SCP)."""
    return list_import_files()


@router.post("/import/preview/from-file")
async def preview_scp_file(
    filename: str,
    options: Optional[RestoreOptions] = Body(None),
    current_user: User = Depends(require_permission("backup.view"))
):
    """Preview a config archive from the imports directory."""
    safe_name = Path(filename).name
    if not is_archive_name(safe_name):
        raise HTTPException(status_code=400, detail="File must be a .tar.gz or .tar.gz.enc archive")
    
    file_path = os.path.join(IMPORTS_DIR, safe_name)
    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="File not found")
    
    result = await preview_config(file_path, _passphrase(options))
    if "error" in result:
        _raise_archive_error(result)
    
    return result


# ============== RESTORE FROM LOCAL BACKUP ==============


@router.post("/restore/preview/{filename}")
async def preview_local_backup(
    filename: str,
    options: Optional[RestoreOptions] = Body(None),
    current_user: User = Depends(require_permission("backup.view"))
):
    """Preview a local backup file for restore."""
    safe_name = Path(filename).name
    if not is_archive_name(safe_name):
        raise HTTPException(status_code=400, detail="File must be a .tar.gz or .tar.gz.enc archive")
    
    file_path = os.path.join(BACKUP_DIR, safe_name)
    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="File not found")
    
    result = await preview_config(file_path, _passphrase(options))
    if "error" in result:
        _raise_archive_error(result)
    
    return result


@router.post("/restore/{filename}")
async def restore_local_backup(
    filename: str,
    options: Optional[RestoreOptions] = Body(None),
    current_user: User = Depends(require_permission("backup.restore")),
    session: AsyncSession = Depends(get_session)
):
    """Restore configuration from a local backup file."""
    safe_name = Path(filename).name
    if not is_archive_name(safe_name):
        raise HTTPException(status_code=400, detail="File must be a .tar.gz or .tar.gz.enc archive")
    
    file_path = os.path.join(BACKUP_DIR, safe_name)
    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="File not found in backup folder")
    
    result = await import_config(session, file_path, _passphrase(options))
    return result


# ============== SCHEDULED BACKUP(triggers export + remote upload) ==============


class BackupResult(BaseModel):
    success: bool
    timestamp: str
    archive: Optional[str] = None
    remote_uploaded: bool = False
    errors: List[str] = []


async def update_backup_status(session: AsyncSession, success: bool, errors: List[str]):
    """Update backup settings with last run status."""
    result = await session.execute(select(BackupSettings).where(BackupSettings.id == 1))
    bk_settings = result.scalar_one_or_none()
    
    if bk_settings:
        bk_settings.last_run_time = datetime.utcnow()
        bk_settings.last_run_status = "success" if success else f"failed: {', '.join(errors)}"
        session.add(bk_settings)
        await session.commit()


@router.post("/run", response_model=BackupResult)
async def trigger_backup(
    current_user: User = Depends(require_permission("backup.manage")),
    session: AsyncSession = Depends(get_session)
):
    """Trigger a manual backup (export + remote upload)."""
    result = await session.execute(select(BackupSettings).where(BackupSettings.id == 1))
    bk_settings = result.scalar_one_or_none()

    if not bk_settings or not bk_settings.remote_host or not bk_settings.remote_user:
        raise HTTPException(
            status_code=400,
            detail="Remote storage not configured. Set host and user in backup settings."
        )

    backup_result = await run_backup(session=session, retention_days=bk_settings.retention_days or 30)

    await update_backup_status(session, backup_result["success"], backup_result["errors"])

    return BackupResult(**backup_result)


# ============== LOCAL ARCHIVE MANAGEMENT ==============


@router.get("/history")
async def get_backup_history(
    current_user: User = Depends(require_permission("backup.view")),
):
    """Get list of local config export archives."""
    return list_local_backups()


@router.get("/download/{filename}")
async def download_backup(
    filename: str,
    current_user: User = Depends(require_permission("backup.manage"))
):
    """Download a config export archive."""
    safe_name = Path(filename).name
    if not is_archive_name(safe_name):
        raise HTTPException(status_code=400, detail="Invalid filename")

    file_path = Path(BACKUP_DIR) / safe_name
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="File not found")

    return FileResponse(
        path=str(file_path),
        filename=safe_name,
        media_type="application/octet-stream"
    )


@router.delete("/delete/{filename}")
async def delete_backup(
    filename: str,
    current_user: User = Depends(require_permission("backup.manage"))
):
    """Delete a config export archive."""
    safe_name = Path(filename).name
    if not is_archive_name(safe_name):
        raise HTTPException(status_code=400, detail="Invalid filename")

    file_path = Path(BACKUP_DIR) / safe_name
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="File not found")

    file_path.unlink()
    return {"status": "ok", "message": "File deleted"}


# ============== REMOTE STORAGE ==============


class RemoteBackupItem(BaseModel):
    filename: str
    size_mb: float
    mtime: Optional[datetime] = None


async def _remote_call(coro):
    """Run a remote operation and map its failures to HTTP errors."""
    try:
        return await coro
    except RemoteNotConfigured as e:
        raise HTTPException(status_code=400, detail=str(e))
    except HostKeyMismatch as e:
        raise HTTPException(status_code=409, detail=str(e))
    except Exception as e:
        logger.error(f"Remote backup operation failed: {e}")
        raise HTTPException(status_code=502, detail=f"Server remoto: {e}")


@router.get("/remote/list", response_model=List[RemoteBackupItem])
async def list_remote_backup_files(
    current_user: User = Depends(require_permission("backup.view")),
    session: AsyncSession = Depends(get_session)
):
    """List backup files on remote storage."""
    backups = await _remote_call(list_remote_backups(session))
    return [
        RemoteBackupItem(
            filename=b["filename"],
            size_mb=round((b.get("size_bytes") or 0) / (1024 * 1024), 2),
            mtime=b.get("mtime")
        )
        for b in backups
    ][:10]


@router.post("/remote/download/{filename}")
async def download_remote_backup_file(
    filename: str,
    current_user: User = Depends(require_permission("backup.manage")),
    session: AsyncSession = Depends(get_session)
):
    """Download a backup from remote storage to local."""
    safe_name = Path(filename).name
    if not is_archive_name(safe_name):
        raise HTTPException(status_code=400, detail="Invalid filename")
    local_path = await _remote_call(download_remote_backup(session, safe_name))
    return {"status": "ok", "message": "File downloaded", "local_path": local_path}


@router.delete("/remote/delete/{filename}")
async def delete_remote_backup_file(
    filename: str,
    current_user: User = Depends(require_permission("backup.manage")),
    session: AsyncSession = Depends(get_session)
):
    """Delete a backup from remote storage."""
    safe_name = Path(filename).name
    if not is_archive_name(safe_name):
        raise HTTPException(status_code=400, detail="Invalid filename")
    await _remote_call(delete_remote_backup(session, safe_name))
    return {"status": "ok", "message": "Remote file deleted"}


@router.post("/remote/cleanup")
async def cleanup_remote_storage(
    current_user: User = Depends(require_permission("backup.manage")),
    session: AsyncSession = Depends(get_session)
):
    """Apply retention policy to remote storage."""
    result = await session.execute(select(BackupSettings).where(BackupSettings.id == 1))
    bk_settings = result.scalar_one_or_none()
    retention = (bk_settings.retention_days or 30) if bk_settings else 30
    deleted = await _remote_call(cleanup_remote_backups(session, retention))
    return {"status": "ok", "deleted_count": deleted}


@router.post("/remote/host-key/forget")
async def forget_remote_host_key(
    current_user: User = Depends(require_permission("backup.manage")),
    session: AsyncSession = Depends(get_session)
):
    """
    Forget the pinned SFTP server key: the next connection pins the key the
    server presents then. For a server whose key changed for a known reason.
    """
    from core.settings.router import _backup_response
    result = await session.execute(select(BackupSettings).where(BackupSettings.id == 1))
    bk_settings = result.scalar_one_or_none()
    if not bk_settings:
        raise HTTPException(status_code=400, detail="Remote storage not configured")
    logger.warning(f"SFTP host key {bk_settings.remote_host_key} forgotten by {current_user.username}")
    bk_settings.remote_host_key = None
    session.add(bk_settings)
    await session.commit()
    await session.refresh(bk_settings)
    return _backup_response(bk_settings)
