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
from .models import (
    ManagedLanSettings, ManagedLanResponse, ManagedLanUpdate, ManagedLanEnableRequest,
)
from .service import provisioning_service, parse_locked
from core.network.service import NetworkService

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
        locked_interfaces=parse_locked(settings.locked_interfaces) or (
            [settings.interface] if settings.enabled and settings.interface else []
        ),
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
    data: ManagedLanEnableRequest | None = None,
    _user: User = Depends(require_superuser()),
    session: AsyncSession = Depends(get_session),
):
    """
    Enable managed-LAN provisioning and run a reconcile immediately.
    Called by the installer (--provision-lan).

    Body (optional): `interfaces` = explicit list to lock read-only; the first
    becomes the managed LAN (DHCP/NAT). If omitted, the managed interface is
    auto-detected (eth1/ens19) and only it is locked.

    If the required interface(s) are not present, provisioning is NOT enabled —
    the response reports enabled=False so the installer can warn, behaving as if
    --provision-lan had not been passed.
    """
    settings = await provisioning_service.get_or_create_settings(session)

    def _disable_and_return():
        settings.enabled = False
        settings.interface = None
        settings.locked_interfaces = ""
        session.add(settings)

    present = {i["name"] for i in NetworkService.get_interfaces() if i.get("name")}

    requested = parse_locked(",".join(data.interfaces)) if (data and data.interfaces) else []
    if data and data.interfaces and not requested:
        raise HTTPException(status_code=400, detail="Nomi interfaccia non validi")

    if requested:
        # EXPLICIT mode: every listed interface must currently exist.
        missing = [n for n in requested if n not in present]
        if missing:
            logger.warning(f"Managed LAN: specified interfaces not found {missing}; provisioning not enabled")
            _disable_and_return()
            await session.commit()
            return _build_response(settings, None)
        settings.locked_interfaces = ",".join(requested)
        settings.interface = requested[0]
    else:
        # AUTO mode: resolve a known candidate by name.
        detected = provisioning_service.detect_managed_interface()
        if not detected:
            logger.warning("Managed LAN: no known LAN interface present; provisioning not enabled")
            _disable_and_return()
            await session.commit()
            return _build_response(settings, None)
        settings.locked_interfaces = ""
        settings.interface = detected

    settings.enabled = True
    session.add(settings)
    await session.flush()
    await provisioning_service.reconcile(session)
    await session.commit()
    detected = provisioning_service.detect_managed_interface()
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
