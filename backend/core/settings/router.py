"""
MADMIN Settings Router

API endpoints for system settings management.
"""
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from core.database import get_session
from core.auth.dependencies import require_permission
from core.auth.models import User
from .models import (
    SystemSettings, SystemSettingsUpdate, SystemSettingsResponse,
    SMTPSettings, SMTPSettingsUpdate, SMTPSettingsResponse,
    BackupSettings, BackupSettingsUpdate, BackupSettingsResponse
)

router = APIRouter(prefix="/api/settings", tags=["Settings"])


# --- System Settings ---

@router.get("/system", response_model=SystemSettingsResponse)
async def get_system_settings(
    current_user: User = Depends(require_permission("settings.view")),
    session: AsyncSession = Depends(get_session)
):
    """Get system settings."""
    result = await session.execute(select(SystemSettings).where(SystemSettings.id == 1))
    settings = result.scalar_one_or_none()
    
    if not settings:
        # Create default settings
        settings = SystemSettings(id=1)
        session.add(settings)
        await session.commit()
        await session.refresh(settings)
    
    return SystemSettingsResponse(
        company_name=settings.company_name,
        primary_color=settings.primary_color,
        logo_url=settings.logo_url,
        favicon_url=settings.favicon_url,
        support_url=settings.support_url,
        updated_at=settings.updated_at
    )


@router.patch("/system", response_model=SystemSettingsResponse)
async def update_system_settings(
    data: SystemSettingsUpdate,
    current_user: User = Depends(require_permission("settings.manage")),
    session: AsyncSession = Depends(get_session)
):
    """Update system settings."""
    result = await session.execute(select(SystemSettings).where(SystemSettings.id == 1))
    settings = result.scalar_one_or_none()
    
    if not settings:
        settings = SystemSettings(id=1)
        session.add(settings)
    
    # Update fields
    for key, value in data.model_dump(exclude_unset=True).items():
        if value is not None:
            setattr(settings, key, value)
    
    settings.updated_at = datetime.utcnow()
    session.add(settings)
    await session.commit()
    await session.refresh(settings)
    
    return SystemSettingsResponse(
        company_name=settings.company_name,
        primary_color=settings.primary_color,
        logo_url=settings.logo_url,
        favicon_url=settings.favicon_url,
        support_url=settings.support_url,
        updated_at=settings.updated_at
    )


# --- SMTP Settings ---

@router.get("/smtp", response_model=SMTPSettingsResponse)
async def get_smtp_settings(
    current_user: User = Depends(require_permission("settings.view")),
    session: AsyncSession = Depends(get_session)
):
    """Get SMTP settings."""
    result = await session.execute(select(SMTPSettings).where(SMTPSettings.id == 1))
    settings = result.scalar_one_or_none()
    
    if not settings:
        settings = SMTPSettings(id=1)
        session.add(settings)
        await session.commit()
        await session.refresh(settings)
    
    return SMTPSettingsResponse(
        smtp_host=settings.smtp_host,
        smtp_port=settings.smtp_port,
        smtp_encryption=settings.smtp_encryption,
        smtp_username=settings.smtp_username,
        sender_email=settings.sender_email,
        sender_name=settings.sender_name,
        public_url=settings.public_url,
        updated_at=settings.updated_at
    )


@router.patch("/smtp", response_model=SMTPSettingsResponse)
async def update_smtp_settings(
    data: SMTPSettingsUpdate,
    current_user: User = Depends(require_permission("settings.manage")),
    session: AsyncSession = Depends(get_session)
):
    """Update SMTP settings."""
    result = await session.execute(select(SMTPSettings).where(SMTPSettings.id == 1))
    settings = result.scalar_one_or_none()
    
    if not settings:
        settings = SMTPSettings(id=1)
        session.add(settings)
    
    for key, value in data.model_dump(exclude_unset=True).items():
        if value is not None:
            setattr(settings, key, value)
    
    settings.updated_at = datetime.utcnow()
    session.add(settings)
    await session.commit()
    await session.refresh(settings)
    
    return SMTPSettingsResponse(
        smtp_host=settings.smtp_host,
        smtp_port=settings.smtp_port,
        smtp_encryption=settings.smtp_encryption,
        smtp_username=settings.smtp_username,
        sender_email=settings.sender_email,
        sender_name=settings.sender_name,
        public_url=settings.public_url,
        updated_at=settings.updated_at
    )


from pydantic import BaseModel, EmailStr


class SMTPTestRequest(BaseModel):
    recipient_email: EmailStr


@router.post("/smtp/test")
async def test_smtp_settings(
    data: SMTPTestRequest,
    current_user: User = Depends(require_permission("settings.manage")),
    session: AsyncSession = Depends(get_session)
):
    """
    Send a test email to verify SMTP configuration.
    Uses the saved SMTP settings from database.
    """
    # Get SMTP settings
    result = await session.execute(select(SMTPSettings).where(SMTPSettings.id == 1))
    settings = result.scalar_one_or_none()
    
    if not settings or not settings.smtp_host:
        raise HTTPException(
            status_code=400,
            detail="Configura prima le impostazioni SMTP"
        )
    
    # Send test email
    from core.email import send_test_email
    
    result = await send_test_email(
        smtp_host=settings.smtp_host,
        smtp_port=settings.smtp_port,
        smtp_encryption=settings.smtp_encryption,
        smtp_username=settings.smtp_username,
        smtp_password=settings.smtp_password,
        sender_email=settings.sender_email,
        sender_name=settings.sender_name,
        recipient_email=data.recipient_email
    )
    
    if not result["success"]:
        raise HTTPException(status_code=500, detail=result["message"])
    
    return result


# --- Backup Settings ---

@router.get("/backup", response_model=BackupSettingsResponse)
async def get_backup_settings(
    current_user: User = Depends(require_permission("settings.view")),
    session: AsyncSession = Depends(get_session)
):
    """Get backup settings."""
    result = await session.execute(select(BackupSettings).where(BackupSettings.id == 1))
    settings = result.scalar_one_or_none()
    
    if not settings:
        settings = BackupSettings(id=1)
        session.add(settings)
        await session.commit()
        await session.refresh(settings)
    
    return BackupSettingsResponse(
        enabled=settings.enabled,
        frequency=settings.frequency,
        time=settings.time,
        remote_protocol=settings.remote_protocol,
        remote_host=settings.remote_host,
        remote_port=settings.remote_port,
        remote_user=settings.remote_user,
        remote_path=settings.remote_path,
        last_run_status=settings.last_run_status,
        last_run_time=settings.last_run_time,
        updated_at=settings.updated_at
    )


@router.patch("/backup", response_model=BackupSettingsResponse)
async def update_backup_settings(
    data: BackupSettingsUpdate,
    current_user: User = Depends(require_permission("settings.manage")),
    session: AsyncSession = Depends(get_session)
):
    """Update backup settings."""
    result = await session.execute(select(BackupSettings).where(BackupSettings.id == 1))
    settings = result.scalar_one_or_none()
    
    if not settings:
        settings = BackupSettings(id=1)
        session.add(settings)
    
    for key, value in data.model_dump(exclude_unset=True).items():
        if value is not None:
            setattr(settings, key, value)
    
    settings.updated_at = datetime.utcnow()
    session.add(settings)
    await session.commit()
    await session.refresh(settings)
    
    return BackupSettingsResponse(
        enabled=settings.enabled,
        frequency=settings.frequency,
        time=settings.time,
        remote_protocol=settings.remote_protocol,
        remote_host=settings.remote_host,
        remote_port=settings.remote_port,
        remote_user=settings.remote_user,
        remote_path=settings.remote_path,
        last_run_status=settings.last_run_status,
        last_run_time=settings.last_run_time,
        updated_at=settings.updated_at
    )
