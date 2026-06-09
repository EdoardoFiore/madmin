"""
MADMIN Provisioning Router

API for the managed LAN (interface + DHCP + NAT) auto-provisioning.
"""
import logging
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import get_session
from core.auth.dependencies import require_permission, require_superuser
from core.auth.models import User
from .models import ManagedLanSettings, ManagedLanResponse, ManagedLanUpdate
from .service import provisioning_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/provisioning", tags=["Provisioning"])


def _build_response(settings: ManagedLanSettings, detected: str | None) -> ManagedLanResponse:
    # Prefer the interface's LIVE CIDR (set externally) over the last-stored value,
    # so the UI always reflects the IP the WAN-managing software assigned.
    iface = settings.interface or detected
    live_cidr = provisioning_service.get_live_interface_cidr(iface) if iface else None
    source_cidr = live_cidr or settings.address_cidr

    network = gateway = None
    try:
        network, gateway, d_start, d_end = provisioning_service.derive_network(source_cidr)
    except Exception:
        d_start = d_end = None
    return ManagedLanResponse(
        enabled=settings.enabled,
        interface=settings.interface,
        address_cidr=source_cidr,
        network=network,
        gateway=gateway,
        dhcp_range_start=settings.dhcp_range_start or d_start,
        dhcp_range_end=settings.dhcp_range_end or d_end,
        dns_servers=settings.dns_servers,
        detected_interface=detected,
    )


@router.get("/managed-lan", response_model=ManagedLanResponse)
async def get_managed_lan(
    _user: User = Depends(require_permission("settings.view")),
    session: AsyncSession = Depends(get_session),
):
    """Current managed-LAN provisioning state."""
    settings = await provisioning_service.get_or_create_settings(session)
    await session.commit()
    detected = provisioning_service.detect_managed_interface()
    return _build_response(settings, detected)


@router.post("/managed-lan/enable", response_model=ManagedLanResponse)
async def enable_managed_lan(
    _user: User = Depends(require_superuser()),
    session: AsyncSession = Depends(get_session),
):
    """
    Enable managed-LAN provisioning and run a reconcile immediately.
    Called by the installer (--provision-lan).

    If no known LAN interface (eth1/ens19) is present, provisioning is NOT
    enabled — the response reports enabled=False so the installer can warn,
    behaving as if --provision-lan had not been passed.
    """
    settings = await provisioning_service.get_or_create_settings(session)

    detected = provisioning_service.detect_managed_interface()
    if not detected:
        logger.warning("Managed LAN: no known LAN interface present; provisioning not enabled")
        settings.enabled = False
        settings.interface = None
        session.add(settings)
        await session.commit()
        return _build_response(settings, None)

    settings.enabled = True
    session.add(settings)
    await session.flush()
    await provisioning_service.reconcile(session)
    await session.commit()
    settings = await provisioning_service.get_or_create_settings(session)
    return _build_response(settings, detected)


@router.patch("/managed-lan", response_model=ManagedLanResponse)
async def update_managed_lan(
    data: ManagedLanUpdate,
    _user: User = Depends(require_permission("network.manage")),
    session: AsyncSession = Depends(get_session),
):
    """
    Update user-editable managed-LAN DHCP parameters (DNS servers, pool range).

    The interface IP/subnet is NOT user-settable: it is assigned externally by
    the WAN-managing software, and the DHCP subnet/gateway are derived from the
    live interface IP. We only recompute and re-apply the bound DHCP config.
    """
    settings = await provisioning_service.get_or_create_settings(session)
    if not settings.enabled:
        raise HTTPException(status_code=400, detail="Managed LAN provisioning is not enabled")

    if data.dns_servers is not None:
        settings.dns_servers = data.dns_servers
    if data.dhcp_range_start is not None:
        settings.dhcp_range_start = data.dhcp_range_start
    if data.dhcp_range_end is not None:
        settings.dhcp_range_end = data.dhcp_range_end
    session.add(settings)
    await session.flush()

    # Recompute the DHCP subnet from the live interface IP and re-apply.
    await provisioning_service.resync_managed_dhcp(session)

    await session.commit()
    detected = provisioning_service.detect_managed_interface()
    settings = await provisioning_service.get_or_create_settings(session)
    return _build_response(settings, detected)
