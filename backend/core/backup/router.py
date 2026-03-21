"""
MADMIN Backup Router

API endpoints for config export/import and backup management.
"""
import os
import logging
from datetime import datetime
from typing import Optional, List
from pathlib import Path
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
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
    BACKUP_DIR, IMPORTS_DIR,
    list_remote_backups, download_remote_backup, delete_remote_backup, cleanup_remote_backups
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/backup", tags=["Backup"])


# ============== CONFIG EXPORT ==============


@router.post("/export")
async def export_configuration(
    download: bool = False,
    current_user: User = Depends(require_permission("settings.manage")),
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
                media_type="application/gzip"
            )
        
        return {
            "success": True,
            "filename": os.path.basename(archive_path),
            "path": str(archive_path)
        }
    except Exception as e:
        logger.error(f"Export failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Esportazione fallita")


# ============== CONFIG IMPORT ==============


@router.post("/import/preview")
async def preview_import(
    file: UploadFile = File(...),
    current_user: User = Depends(require_permission("settings.manage"))
):
    """Preview contents of a config archive without applying."""
    if not file.filename.endswith(".tar.gz"):
        raise HTTPException(status_code=400, detail="Il file deve essere un archivio .tar.gz")
    
    # Save uploaded file temporarily
    temp_path = os.path.join(BACKUP_DIR, f"_preview_temp_{file.filename}")
    try:
        os.makedirs(BACKUP_DIR, exist_ok=True)
        with open(temp_path, "wb") as f:
            content = await file.read()
            f.write(content)
        
        result = await preview_config(temp_path)
        
        if "error" in result:
            raise HTTPException(status_code=400, detail=result["error"])
        
        return result
    finally:
        if os.path.exists(temp_path):
            os.remove(temp_path)


@router.post("/import")
async def import_configuration(
    file: UploadFile = File(...),
    current_user: User = Depends(require_permission("settings.manage")),
    session: AsyncSession = Depends(get_session)
):
    """Import configuration from uploaded tar.gz archive."""
    if not file.filename.endswith(".tar.gz"):
        raise HTTPException(status_code=400, detail="Il file deve essere un archivio .tar.gz")
    
    # Save uploaded file
    temp_path = os.path.join(BACKUP_DIR, f"_import_{file.filename}")
    try:
        os.makedirs(BACKUP_DIR, exist_ok=True)
        with open(temp_path, "wb") as f:
            content = await file.read()
            f.write(content)
        
        result = await import_config(session, temp_path)
        
        if not result.get("success"):
            raise HTTPException(status_code=400, detail={
                "message": "Importazione completata con errori",
                "result": result
            })
        
        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Import failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Importazione fallita")
    finally:
        if os.path.exists(temp_path):
            os.remove(temp_path)


@router.post("/import/from-file")
async def import_from_scp_file(
    filename: str,
    current_user: User = Depends(require_permission("settings.manage")),
    session: AsyncSession = Depends(get_session)
):
    """Import configuration from file uploaded via SCP to imports directory."""
    safe_name = Path(filename).name
    if not safe_name.endswith(".tar.gz"):
        raise HTTPException(status_code=400, detail="Il file deve essere un archivio .tar.gz")
    
    file_path = os.path.join(IMPORTS_DIR, safe_name)
    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="File non trovato nella cartella imports")
    
    result = await import_config(session, file_path)
    return result


@router.get("/import/files")
async def list_scp_import_files(
    current_user: User = Depends(require_permission("settings.view"))
):
    """List config archives available in the imports directory (uploaded via SCP)."""
    return list_import_files()


@router.post("/import/preview/from-file")
async def preview_scp_file(
    filename: str,
    current_user: User = Depends(require_permission("settings.view"))
):
    """Preview a config archive from the imports directory."""
    safe_name = Path(filename).name
    if not safe_name.endswith(".tar.gz"):
        raise HTTPException(status_code=400, detail="Il file deve essere un archivio .tar.gz")
    
    file_path = os.path.join(IMPORTS_DIR, safe_name)
    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="File non trovato")
    
    result = await preview_config(file_path)
    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])
    
    return result


# ============== RESTORE FROM LOCAL BACKUP ==============


@router.post("/restore/preview/{filename}")
async def preview_local_backup(
    filename: str,
    current_user: User = Depends(require_permission("settings.view"))
):
    """Preview a local backup file for restore."""
    safe_name = Path(filename).name
    if not safe_name.endswith(".tar.gz"):
        raise HTTPException(status_code=400, detail="Il file deve essere un archivio .tar.gz")
    
    file_path = os.path.join(BACKUP_DIR, safe_name)
    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="File non trovato")
    
    result = await preview_config(file_path)
    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])
    
    return result


@router.post("/restore/{filename}")
async def restore_local_backup(
    filename: str,
    current_user: User = Depends(require_permission("settings.manage")),
    session: AsyncSession = Depends(get_session)
):
    """Restore configuration from a local backup file."""
    safe_name = Path(filename).name
    if not safe_name.endswith(".tar.gz"):
        raise HTTPException(status_code=400, detail="Il file deve essere un archivio .tar.gz")
    
    file_path = os.path.join(BACKUP_DIR, safe_name)
    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="File non trovato nella cartella backup")
    
    result = await import_config(session, file_path)
    return result


# ============== SCHEDULED BACKUP (triggers export + remote upload) ==============


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
    current_user: User = Depends(require_permission("settings.manage")),
    session: AsyncSession = Depends(get_session)
):
    """Trigger a manual backup (export + remote upload)."""
    result = await session.execute(select(BackupSettings).where(BackupSettings.id == 1))
    bk_settings = result.scalar_one_or_none()

    if not bk_settings or not bk_settings.remote_host or not bk_settings.remote_user:
        raise HTTPException(
            status_code=400,
            detail="Storage remoto non configurato. Imposta host e utente nelle impostazioni backup."
        )

    backup_result = await run_backup(
        session=session,
        remote_protocol=bk_settings.remote_protocol if bk_settings else None,
        remote_host=bk_settings.remote_host if bk_settings else None,
        remote_port=(bk_settings.remote_port or 22) if bk_settings else 22,
        remote_user=bk_settings.remote_user if bk_settings else None,
        remote_password=bk_settings.remote_password if bk_settings else None,
        remote_path=(bk_settings.remote_path or "/") if bk_settings else "/",
        retention_days=(bk_settings.retention_days or 30) if bk_settings else 30
    )
    
    await update_backup_status(session, backup_result["success"], backup_result["errors"])
    
    return BackupResult(**backup_result)


# ============== LOCAL ARCHIVE MANAGEMENT ==============


@router.get("/history")
async def get_backup_history(
    current_user: User = Depends(require_permission("settings.view")),
):
    """Get list of local config export archives."""
    return list_local_backups()


@router.get("/download/{filename}")
async def download_backup(
    filename: str,
    current_user: User = Depends(require_permission("settings.manage"))
):
    """Download a config export archive."""
    safe_name = Path(filename).name
    if not safe_name.endswith(".tar.gz"):
        raise HTTPException(status_code=400, detail="Nome file non valido")
    
    file_path = Path(BACKUP_DIR) / safe_name
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="File non trovato")
    
    return FileResponse(
        path=str(file_path),
        filename=safe_name,
        media_type="application/gzip"
    )


@router.delete("/delete/{filename}")
async def delete_backup(
    filename: str,
    current_user: User = Depends(require_permission("settings.manage"))
):
    """Delete a config export archive."""
    safe_name = Path(filename).name
    if not safe_name.endswith(".tar.gz"):
        raise HTTPException(status_code=400, detail="Nome file non valido")
    
    file_path = Path(BACKUP_DIR) / safe_name
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="File non trovato")
    
    file_path.unlink()
    return {"status": "ok", "message": "File eliminato"}


# ============== REMOTE STORAGE ==============


class RemoteBackupItem(BaseModel):
    filename: str
    size_mb: float
    mtime: Optional[datetime] = None


@router.get("/remote/list", response_model=List[RemoteBackupItem])
async def list_remote_backup_files(
    current_user: User = Depends(require_permission("settings.view")),
    session: AsyncSession = Depends(get_session)
):
    """List backup files on remote storage."""
    result = await session.execute(select(BackupSettings).where(BackupSettings.id == 1))
    bk_settings = result.scalar_one_or_none()
    
    if not bk_settings or not bk_settings.remote_protocol or not bk_settings.remote_host:
        raise HTTPException(status_code=400, detail="Storage remoto non configurato")
    
    backups = list_remote_backups(
        bk_settings.remote_protocol,
        bk_settings.remote_host,
        bk_settings.remote_port or 22,
        bk_settings.remote_user or "",
        bk_settings.remote_password or "",
        bk_settings.remote_path or "/"
    )
    
    return [
        RemoteBackupItem(
            filename=b["filename"],
            size_mb=b.get("size_mb", 0),
            mtime=b.get("mtime")
        )
        for b in backups
    ][:10]


@router.post("/remote/download/{filename}")
async def download_remote_backup_file(
    filename: str,
    current_user: User = Depends(require_permission("settings.manage")),
    session: AsyncSession = Depends(get_session)
):
    """Download a backup from remote storage to local."""
    safe_name = Path(filename).name
    if not safe_name.endswith(".tar.gz"):
        raise HTTPException(status_code=400, detail="Nome file non valido")
    
    result = await session.execute(select(BackupSettings).where(BackupSettings.id == 1))
    bk_settings = result.scalar_one_or_none()
    
    if not bk_settings or not bk_settings.remote_protocol:
        raise HTTPException(status_code=400, detail="Storage remoto non configurato")
    
    local_path = download_remote_backup(
        bk_settings.remote_protocol,
        bk_settings.remote_host,
        bk_settings.remote_port or 22,
        bk_settings.remote_user or "",
        bk_settings.remote_password or "",
        bk_settings.remote_path or "/",
        safe_name
    )
    
    if local_path:
        return {"status": "ok", "message": "File scaricato", "local_path": local_path}
    else:
        raise HTTPException(status_code=500, detail="Download fallito")


@router.delete("/remote/delete/{filename}")
async def delete_remote_backup_file(
    filename: str,
    current_user: User = Depends(require_permission("settings.manage")),
    session: AsyncSession = Depends(get_session)
):
    """Delete a backup from remote storage."""
    safe_name = Path(filename).name
    if not safe_name.endswith(".tar.gz"):
        raise HTTPException(status_code=400, detail="Nome file non valido")
    
    result = await session.execute(select(BackupSettings).where(BackupSettings.id == 1))
    bk_settings = result.scalar_one_or_none()
    
    if not bk_settings or not bk_settings.remote_protocol:
        raise HTTPException(status_code=400, detail="Storage remoto non configurato")
    
    success = delete_remote_backup(
        bk_settings.remote_protocol,
        bk_settings.remote_host,
        bk_settings.remote_port or 22,
        bk_settings.remote_user or "",
        bk_settings.remote_password or "",
        bk_settings.remote_path or "/",
        safe_name
    )
    
    if success:
        return {"status": "ok", "message": "File remoto eliminato"}
    else:
        raise HTTPException(status_code=500, detail="Eliminazione fallita")


@router.post("/remote/cleanup")
async def cleanup_remote_storage(
    current_user: User = Depends(require_permission("settings.manage")),
    session: AsyncSession = Depends(get_session)
):
    """Apply retention policy to remote storage."""
    result = await session.execute(select(BackupSettings).where(BackupSettings.id == 1))
    bk_settings = result.scalar_one_or_none()
    
    if not bk_settings or not bk_settings.remote_protocol:
        raise HTTPException(status_code=400, detail="Storage remoto non configurato")
    
    deleted = cleanup_remote_backups(
        bk_settings.remote_protocol,
        bk_settings.remote_host,
        bk_settings.remote_port or 22,
        bk_settings.remote_user or "",
        bk_settings.remote_password or "",
        bk_settings.remote_path or "/",
        bk_settings.retention_days or 30
    )
    
    return {"status": "ok", "deleted_count": deleted}
