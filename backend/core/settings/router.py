"""
MADMIN Settings Router

API endpoints for system settings management.
"""
import logging
from datetime import datetime
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from core.database import get_session
from core.auth.dependencies import require_permission
from core.auth.dependencies import get_current_user
from core.auth.models import User
from .models import (
    SystemSettings, SystemSettingsUpdate, SystemSettingsResponse,
    SMTPSettings, SMTPSettingsUpdate, SMTPSettingsResponse,
    BackupSettings, BackupSettingsUpdate, BackupSettingsResponse,
    NetworkSettingsResponse, PortChangeRequest, CertificateInfo
)
from .service import network_service

logger = logging.getLogger(__name__)


async def _get_vpn_ports_in_use(session: AsyncSession) -> set:
    """Raccoglie le porte usate dalle istanze VPN attive (OpenVPN, WireGuard)."""
    from sqlalchemy import text
    ports = set()
    try:
        res = await session.execute(text("SELECT port FROM ovpn_instance WHERE port IS NOT NULL"))
        ports.update(r[0] for r in res.fetchall())
    except Exception:
        pass
    try:
        res = await session.execute(text("SELECT port FROM wg_instance WHERE port IS NOT NULL"))
        ports.update(r[0] for r in res.fetchall())
    except Exception:
        pass
    return ports

router = APIRouter(prefix="/api/settings", tags=["Settings"])


# --- System Settings ---

@router.get("/system", response_model=SystemSettingsResponse)
async def get_system_settings(
    current_user: User = Depends(get_current_user),
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
        default_language=getattr(settings, 'default_language', 'en') or 'en',
        password_max_age_days=getattr(settings, 'password_max_age_days', 0) or 0,
        wan_protection_enabled=getattr(settings, 'wan_protection_enabled', False) or False,
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
    
    # Update fields - allow setting to None for reset
    # Also convert empty strings to None for nullable fields
    update_data = data.model_dump(exclude_unset=True)

    # WAN edit protection is ONE-WAY: it can be enabled (e.g. by the installer
    # --protect-wan flag) but never disabled via the API. Disabling it would let an
    # admin reconfigure the WAN interface IP on the host infrastructure — a serious
    # security risk. Silently drop any attempt to turn it off.
    if update_data.get('wan_protection_enabled') is False:
        update_data.pop('wan_protection_enabled')

    nullable_fields = {'logo_url', 'favicon_url', 'support_url'}
    for key, value in update_data.items():
        # Convert empty strings to None for nullable fields only
        if key in nullable_fields and value == '':
            value = None
        setattr(settings, key, value)
    
    settings.updated_at = datetime.utcnow()
    session.add(settings)
    await session.commit()
    await session.refresh(settings)

    # When password policy is enabled/changed, immediately backfill users with no expiry set
    if 'password_max_age_days' in update_data:
        from core.auth.service import apply_password_expiry_policy
        updated = await apply_password_expiry_policy(session, update_data['password_max_age_days'])
        if updated:
            await session.commit()
            logger.info(f"Password expiry policy applied to {updated} existing users")

    return SystemSettingsResponse(
        company_name=settings.company_name,
        primary_color=settings.primary_color,
        logo_url=settings.logo_url,
        favicon_url=settings.favicon_url,
        support_url=settings.support_url,
        default_language=getattr(settings, 'default_language', 'en') or 'en',
        password_max_age_days=getattr(settings, 'password_max_age_days', 0) or 0,
        wan_protection_enabled=getattr(settings, 'wan_protection_enabled', False) or False,
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
        public_download_url=settings.public_download_url,
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

    old_download_url = settings.public_download_url

    update_data = data.model_dump(exclude_unset=True)
    nullable_fields = {'public_download_url', 'smtp_username', 'smtp_password'}
    for key, value in update_data.items():
        if key in nullable_fields:
            setattr(settings, key, value if value != '' else None)
        elif value is not None:
            setattr(settings, key, value)

    settings.updated_at = datetime.utcnow()
    session.add(settings)
    await session.commit()
    await session.refresh(settings)

    # Applica blocco nginx se public_download_url è cambiato
    if 'public_download_url' in update_data and settings.public_download_url != old_download_url:
        vpn_ports = await _get_vpn_ports_in_use(session)
        try:
            await network_service.update_public_download_block(
                settings.public_download_url,
                extra_reserved_ports=vpn_ports
            )
        except (ValueError, RuntimeError) as e:
            raise HTTPException(status_code=400, detail=str(e))
        except Exception as e:
            logger.error(f"Error updating public download nginx block: {e}", exc_info=True)
            raise HTTPException(status_code=500, detail="Error updating public Nginx block")

    return SMTPSettingsResponse(
        smtp_host=settings.smtp_host,
        smtp_port=settings.smtp_port,
        smtp_encryption=settings.smtp_encryption,
        smtp_username=settings.smtp_username,
        sender_email=settings.sender_email,
        sender_name=settings.sender_name,
        public_download_url=settings.public_download_url,
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
            detail="Configure SMTP settings first"
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
        retention_days=settings.retention_days,
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
        retention_days=settings.retention_days,
        remote_protocol=settings.remote_protocol,
        remote_host=settings.remote_host,
        remote_port=settings.remote_port,
        remote_user=settings.remote_user,
        remote_path=settings.remote_path,
        last_run_status=settings.last_run_status,
        last_run_time=settings.last_run_time,
        updated_at=settings.updated_at
    )


# --- Network Settings ---

@router.get("/network", response_model=NetworkSettingsResponse)
async def get_network_settings(
    current_user: User = Depends(require_permission("settings.view"))
):
    """Get network (Nginx) settings."""
    return await network_service.get_network_settings()


@router.post("/network/port")
async def update_management_port(
    data: PortChangeRequest,
    current_user: User = Depends(require_permission("settings.manage")),
    session: AsyncSession = Depends(get_session)
):
    """
    Update management port (restarts Nginx).
    WARNING: This will disconnect the current session.
    """
    try:
        # Raccogli porte in uso da VPN e dal blocco download pubblico
        extra_reserved = await _get_vpn_ports_in_use(session)

        smtp_result = await session.execute(select(SMTPSettings).where(SMTPSettings.id == 1))
        smtp = smtp_result.scalar_one_or_none()
        if smtp and smtp.public_download_url:
            extra_reserved.add(network_service.get_public_download_port(smtp.public_download_url))

        if await network_service.update_port(data.port, extra_reserved_ports=extra_reserved):
            return {"status": "success", "message": f"Port changed to {data.port}. Service reloaded."}
        else:
            raise HTTPException(status_code=500, detail="Failed to reload Nginx")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Error updating management port: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post("/network/ssl/renew", response_model=CertificateInfo)
async def renew_ssl_certificate(
    current_user: User = Depends(require_permission("settings.manage"))
):
    """
    Renew self-signed SSL certificate.
    WARNING: This will restart Nginx and drop connections.
    """
    try:
        return await network_service.renew_self_signed_cert()
    except Exception as e:
        logger.error(f"Error renewing SSL certificate: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")


@router.post("/network/ssl/upload", response_model=CertificateInfo)
async def upload_ssl_certificate(
    cert_file: UploadFile = File(...),
    key_file: UploadFile = File(...),
    ca_file: Optional[UploadFile] = File(None),
    current_user: User = Depends(require_permission("settings.manage"))
):
    """
    Upload custom SSL certificate and private key.
    Optionally upload a CA Bundle/Chain (ca_file) to append to the certificate.
    WARNING: This will restart Nginx and drop connections.
    """
    try:
        cert_content = await cert_file.read()
        key_content = await key_file.read()

        ca_content = None
        if ca_file:
            ca_content = await ca_file.read()

        info = await network_service.upload_custom_cert(cert_content, key_content, ca_content)
        return info
    except Exception as e:
        logger.error(f"Error uploading SSL certificate: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error")

