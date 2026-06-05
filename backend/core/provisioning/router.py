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
    network = gateway = None
    try:
        network, gateway, d_start, d_end = provisioning_service.derive_network(settings.address_cidr)
    except Exception:
        d_start = d_end = None
    return ManagedLanResponse(
        enabled=settings.enabled,
        interface=settings.interface,
        address_cidr=settings.address_cidr,
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
    """
    settings = await provisioning_service.get_or_create_settings(session)
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
    Update user-editable managed-LAN parameters. If the network (address_cidr)
    changes, the bound DHCP subnet is recomputed and the service re-applied.
    """
    settings = await provisioning_service.get_or_create_settings(session)
    if not settings.enabled:
        raise HTTPException(status_code=400, detail="Managed LAN provisioning is not enabled")

    network_changed = data.address_cidr is not None and data.address_cidr != settings.address_cidr

    if data.dns_servers is not None:
        settings.dns_servers = data.dns_servers
    if data.dhcp_range_start is not None:
        settings.dhcp_range_start = data.dhcp_range_start
    if data.dhcp_range_end is not None:
        settings.dhcp_range_end = data.dhcp_range_end
    session.add(settings)
    await session.flush()

    if network_changed:
        # Re-write the interface netplan + sync DHCP to the new network
        from core.network.service import NetplanService
        ok, msg = NetplanService.set_interface_config(
            interface=settings.interface, dhcp4=False, addresses=[data.address_cidr]
        )
        if not ok:
            raise HTTPException(status_code=500, detail=f"Netplan write failed: {msg}")
        NetplanService.apply_netplan()
        await provisioning_service.sync_dhcp_to_interface(session, data.address_cidr)
    else:
        # Pool/DNS change only — re-apply DHCP config
        await provisioning_service._apply_dhcp(session)

    await session.commit()
    detected = provisioning_service.detect_managed_interface()
    settings = await provisioning_service.get_or_create_settings(session)
    return _build_response(settings, detected)
