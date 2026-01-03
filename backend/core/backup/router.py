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
from .service import run_backup, BACKUP_DIR

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/backup", tags=["Backup"])


class BackupResult(BaseModel):
    success: bool
    timestamp: str
    archive: Optional[str] = None
    remote_uploaded: bool = False
    errors: List[str] = []


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
