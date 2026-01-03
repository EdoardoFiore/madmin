"""
MADMIN Backup Router

API endpoints for backup management.
"""
import logging
from datetime import datetime
from typing import Optional, List
from pathlib import Path
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from core.database import get_session
from core.auth.dependencies import require_permission
from core.auth.models import User
from core.settings.models import BackupSettings
from .service import (
    run_backup, restore_backup, preview_backup, BACKUP_DIR,
    list_remote_backups, download_remote_backup, delete_remote_backup, cleanup_remote_backups
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/backup", tags=["Backup"])


class BackupResult(BaseModel):
    success: bool
    timestamp: str
    archive: Optional[str] = None
    remote_uploaded: bool = False
    errors: List[str] = []


class RestoreResult(BaseModel):
    success: bool
    database_restored: bool = False
    modules_restored: int = 0
    staging_restored: int = 0
    external_restored: int = 0
    errors: List[str] = []


class BackupPreview(BaseModel):
    filename: str
    size_bytes: int
    has_database: bool
    config_files: List[str] = []
    modules: List[str] = []
    staging: List[str] = []
    external_paths: List[str] = []


class BackupHistoryItem(BaseModel):
    filename: str
    size_mb: float
    created_at: datetime


async def update_backup_status(session: AsyncSession, success: bool, errors: List[str]):
    """Update backup settings with last run status."""
    result = await session.execute(select(BackupSettings).where(BackupSettings.id == 1))
    settings = result.scalar_one_or_none()
    
    if settings:
        settings.last_run_time = datetime.utcnow()
        settings.last_run_status = "success" if success else f"failed: {', '.join(errors)}"
        session.add(settings)
        await session.commit()


@router.post("/run", response_model=BackupResult)
async def trigger_backup(
    background_tasks: BackgroundTasks,
    current_user: User = Depends(require_permission("settings.manage")),
    session: AsyncSession = Depends(get_session)
):
    """
    Trigger a manual backup.
    This runs in the background and updates status when complete.
    """
    # Get backup settings
    result = await session.execute(select(BackupSettings).where(BackupSettings.id == 1))
    settings = result.scalar_one_or_none()
    
    if not settings:
        raise HTTPException(status_code=400, detail="Configura prima le impostazioni di backup")
    
    # Run backup
    backup_result = await run_backup(
        remote_protocol=settings.remote_protocol,
        remote_host=settings.remote_host,
        remote_port=settings.remote_port or 22,
        remote_user=settings.remote_user,
        remote_password=settings.remote_password,
        remote_path=settings.remote_path or "/",
        retention_days=settings.retention_days or 30
    )
    
    # Update status
    await update_backup_status(session, backup_result["success"], backup_result["errors"])
    
    return BackupResult(**backup_result)


@router.get("/history", response_model=List[BackupHistoryItem])
async def get_backup_history(
    current_user: User = Depends(require_permission("settings.view")),
):
    """Get list of local backup archives."""
    backups = []
    
    backup_path = Path(BACKUP_DIR)
    if not backup_path.exists():
        return []
    
    for file in sorted(backup_path.glob("madmin_backup_*.tar.gz"), reverse=True):
        stat = file.stat()
        backups.append(BackupHistoryItem(
            filename=file.name,
            size_mb=round(stat.st_size / (1024 * 1024), 2),
            created_at=datetime.fromtimestamp(stat.st_mtime)
        ))
    
    return backups[:10]  # Limit to 10 most recent


@router.get("/download/{filename}")
async def download_backup(
    filename: str,
    current_user: User = Depends(require_permission("settings.manage"))
):
    """Download a backup archive."""
    # Sanitize filename
    safe_name = Path(filename).name
    if not safe_name.startswith("madmin_backup_") or not safe_name.endswith(".tar.gz"):
        raise HTTPException(status_code=400, detail="Nome file non valido")
    
    file_path = Path(BACKUP_DIR) / safe_name
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="Backup non trovato")
    
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
    """Delete a backup archive."""
    safe_name = Path(filename).name
    if not safe_name.startswith("madmin_backup_") or not safe_name.endswith(".tar.gz"):
        raise HTTPException(status_code=400, detail="Nome file non valido")
    
    file_path = Path(BACKUP_DIR) / safe_name
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="Backup non trovato")
    
    file_path.unlink()
    return {"status": "ok", "message": "Backup eliminato"}


@router.get("/preview/{filename}", response_model=BackupPreview)
async def preview_backup_contents(
    filename: str,
    current_user: User = Depends(require_permission("settings.view"))
):
    """Preview contents of a backup archive before restore."""
    safe_name = Path(filename).name
    if not safe_name.startswith("madmin_backup_") or not safe_name.endswith(".tar.gz"):
        raise HTTPException(status_code=400, detail="Nome file non valido")
    
    file_path = Path(BACKUP_DIR) / safe_name
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="Backup non trovato")
    
    preview = preview_backup(str(file_path))
    
    if "error" in preview:
        raise HTTPException(status_code=500, detail=preview["error"])
    
    return BackupPreview(**preview)


@router.post("/restore/{filename}", response_model=RestoreResult)
async def restore_from_backup(
    filename: str,
    current_user: User = Depends(require_permission("settings.manage"))
):
    """
    Restore from a backup archive.
    
    WARNING: This will overwrite current database and module files!
    """
    safe_name = Path(filename).name
    if not safe_name.startswith("madmin_backup_") or not safe_name.endswith(".tar.gz"):
        raise HTTPException(status_code=400, detail="Nome file non valido")
    
    file_path = Path(BACKUP_DIR) / safe_name
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="Backup non trovato")
    
    result = await restore_backup(str(file_path))
    
    return RestoreResult(**result)


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
    settings = result.scalar_one_or_none()
    
    if not settings or not settings.remote_protocol or not settings.remote_host:
        raise HTTPException(status_code=400, detail="Remote backup non configurato")
    
    backups = await list_remote_backups(
        settings.remote_protocol,
        settings.remote_host,
        settings.remote_port or 22,
        settings.remote_user or "",
        settings.remote_password or "",
        settings.remote_path or "/"
    )
    
    return [
        RemoteBackupItem(
            filename=b["filename"],
            size_mb=round(b.get("size_bytes", 0) / (1024 * 1024), 2),
            mtime=datetime.fromtimestamp(b["mtime"]) if b.get("mtime") else None
        )
        for b in backups
    ][:10]  # Limit to 10 most recent


@router.post("/remote/download/{filename}")
async def download_remote_backup_file(
    filename: str,
    current_user: User = Depends(require_permission("settings.manage")),
    session: AsyncSession = Depends(get_session)
):
    """Download a backup from remote storage to local."""
    safe_name = Path(filename).name
    if not safe_name.startswith("madmin_backup_") or not safe_name.endswith(".tar.gz"):
        raise HTTPException(status_code=400, detail="Nome file non valido")
    
    result = await session.execute(select(BackupSettings).where(BackupSettings.id == 1))
    settings = result.scalar_one_or_none()
    
    if not settings or not settings.remote_protocol:
        raise HTTPException(status_code=400, detail="Remote backup non configurato")
    
    local_path = await download_remote_backup(
        settings.remote_protocol,
        settings.remote_host,
        settings.remote_port or 22,
        settings.remote_user or "",
        settings.remote_password or "",
        settings.remote_path or "/",
        safe_name
    )
    
    if local_path:
        return {"status": "ok", "message": "Backup scaricato", "local_path": local_path}
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
    if not safe_name.startswith("madmin_backup_") or not safe_name.endswith(".tar.gz"):
        raise HTTPException(status_code=400, detail="Nome file non valido")
    
    result = await session.execute(select(BackupSettings).where(BackupSettings.id == 1))
    settings = result.scalar_one_or_none()
    
    if not settings or not settings.remote_protocol:
        raise HTTPException(status_code=400, detail="Remote backup non configurato")
    
    success = await delete_remote_backup(
        settings.remote_protocol,
        settings.remote_host,
        settings.remote_port or 22,
        settings.remote_user or "",
        settings.remote_password or "",
        settings.remote_path or "/",
        safe_name
    )
    
    if success:
        return {"status": "ok", "message": "Backup remoto eliminato"}
    else:
        raise HTTPException(status_code=500, detail="Eliminazione fallita")


@router.post("/remote/cleanup")
async def cleanup_remote_storage(
    current_user: User = Depends(require_permission("settings.manage")),
    session: AsyncSession = Depends(get_session)
):
    """Apply retention policy to remote storage."""
    result = await session.execute(select(BackupSettings).where(BackupSettings.id == 1))
    settings = result.scalar_one_or_none()
    
    if not settings or not settings.remote_protocol:
        raise HTTPException(status_code=400, detail="Remote backup non configurato")
    
    deleted = await cleanup_remote_backups(
        settings.remote_protocol,
        settings.remote_host,
        settings.remote_port or 22,
        settings.remote_user or "",
        settings.remote_password or "",
        settings.remote_path or "/",
        settings.retention_days or 30
    )
    
    return {"status": "ok", "deleted_count": deleted}

