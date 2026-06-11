"""
MADMIN Network Router

API endpoints for network interface information and netplan configuration.
"""
import ipaddress
import logging
import re
from typing import List, Optional, Set
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, field_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from core.auth.dependencies import get_current_user, require_permission
from core.auth.models import User
from core.database import get_session
from core.firewall.orchestrator import firewall_orchestrator

from .service import network_service, netplan_service
from .utils import get_default_interface

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/network", tags=["Network"])

# WAN interface fallback when the default route can't be resolved (e.g. cloud-init eth0).
WAN_INTERFACE_FALLBACK = "eth0"

# Linux interface names: letters/digits/.-_ only, max IFNAMSIZ-1 (15) chars.
# Enforced because the name is interpolated into the netplan filename
# (99-madmin-{interface}.yaml) — anything else is a path-traversal write vector.
_IFACE_NAME_RE = re.compile(r"^[A-Za-z0-9._-]{1,15}$")


def _validate_interface_name(interface: str) -> None:
    """Reject interface names that aren't a valid Linux iface token (400)."""
    if not _IFACE_NAME_RE.match(interface or ""):
        raise HTTPException(
            status_code=400,
            detail="Invalid interface name."
        )


async def _locked_interfaces(session: AsyncSession) -> Set[str]:
    """
    Interfaces that are read-only via API (config cannot be set or deleted).

    Two orthogonal sources, both externally managed (IP/subnet set elsewhere):
    - WAN: the default-route interface, only when SystemSettings.wan_protection_enabled
      is True (opt-in via installer flag --protect-wan).
    - Managed LAN: every interface listed in provisioning (the explicit lock list,
      or the single auto-detected managed interface), whose IP is assigned by the
      WAN-managing software (cannot change its subnet from MADMIN).
    """
    locked: Set[str] = set()

    from core.settings.models import SystemSettings
    result = await session.execute(select(SystemSettings).where(SystemSettings.id == 1))
    settings = result.scalar_one_or_none()
    if settings and getattr(settings, "wan_protection_enabled", False):
        locked.add(get_default_interface() or WAN_INTERFACE_FALLBACK)

    from core.provisioning.service import provisioning_service, parse_locked
    prov = await provisioning_service.get_or_create_settings(session)
    if prov.enabled:
        listed = parse_locked(prov.locked_interfaces)
        locked.update(listed or ([prov.interface] if prov.interface else []))

    return locked


class NetplanConfig(BaseModel):
    """Schema for netplan interface configuration."""
    interface: str
    dhcp4: bool = True
    addresses: Optional[List[str]] = None  # e.g., ["192.168.1.100/24"]
    gateway: Optional[str] = None
    dns_servers: Optional[List[str]] = None
    mtu: Optional[int] = None

    @field_validator('addresses', mode='before')
    @classmethod
    def validate_addresses(cls, v):
        if not v:
            return v
        for addr in v:
            try:
                iface = ipaddress.IPv4Interface(addr)
            except ValueError:
                raise ValueError(f"Invalid IP address: '{addr}'. Use CIDR format (e.g. 192.168.1.100/24)")
            net = iface.network
            if iface.ip == net.network_address:
                raise ValueError(f"'{addr}' is a network address, not a host address. Use a valid host address (e.g. 192.168.1.1/24)")
            if iface.ip == net.broadcast_address:
                raise ValueError(f"'{addr}' is the broadcast address, not a host address.")
        return v

    @field_validator('gateway', mode='before')
    @classmethod
    def validate_gateway(cls, v):
        if not v:
            return v
        try:
            ipaddress.IPv4Address(v)
        except ValueError:
            raise ValueError(f"Invalid gateway: '{v}'. Enter an IPv4 address")
        return v

    @field_validator('dns_servers', mode='before')
    @classmethod
    def validate_dns_servers(cls, v):
        if not v:
            return v
        for dns in v:
            try:
                ipaddress.IPv4Address(dns)
            except ValueError:
                raise ValueError(f"Invalid DNS server: '{dns}'. Enter an IPv4 address")
        return v

    @field_validator('mtu', mode='before')
    @classmethod
    def validate_mtu(cls, v):
        if v is None:
            return v
        if not (576 <= int(v) <= 9000):
            raise ValueError("MTU must be between 576 and 9000")
        return v


# ── Response Models ────────────────────────────────────────────────────

class NetworkActionResponse(BaseModel):
    success: bool
    message: str


@router.get("/interfaces")
async def get_network_interfaces(
    _user: User = Depends(require_permission("network.view"))
):
    """
    Get all network interfaces with their details.
    
    Returns list of interfaces with:
    - name, IPv4, IPv6, MAC address
    - Status (up/down), speed, MTU
    - Traffic stats (bytes/packets sent/received)
    - Netplan configuration (if available)
    """
    interfaces = network_service.get_interfaces()
    return {"interfaces": interfaces}


@router.get("/interfaces/{interface}/config")
async def get_interface_config(
    interface: str,
    _user: User = Depends(require_permission("network.view"))
):
    """Get netplan configuration for a specific interface."""
    _validate_interface_name(interface)
    config = netplan_service.get_interface_config(interface)
    return {
        "interface": interface,
        "config": config,
        "managed": config.get("managed", False) if config else False
    }


@router.post("/interfaces/{interface}/config", response_model=NetworkActionResponse)
async def set_interface_config(
    interface: str,
    config: NetplanConfig,
    session: AsyncSession = Depends(get_session),
    _user: User = Depends(require_permission("network.manage"))
):
    """
    Set netplan configuration for an interface.

    Creates a new config file: /etc/netplan/99-madmin-{interface}.yaml
    Does NOT apply automatically - use /apply endpoint.
    """
    _validate_interface_name(interface)
    if interface in await _locked_interfaces(session):
        raise HTTPException(
            status_code=403,
            detail=f"Interface {interface} is externally managed and not modifiable."
        )

    success, message = netplan_service.set_interface_config(
        interface=interface,
        dhcp4=config.dhcp4,
        addresses=config.addresses,
        gateway=config.gateway,
        dns_servers=config.dns_servers,
        mtu=config.mtu
    )

    if not success:
        raise HTTPException(status_code=500, detail=message)

    return {"success": True, "message": message}


@router.delete("/interfaces/{interface}/config", response_model=NetworkActionResponse)
async def delete_interface_config(
    interface: str,
    session: AsyncSession = Depends(get_session),
    _user: User = Depends(require_permission("network.manage"))
):
    """
    Delete MADMIN-managed netplan config for an interface.

    Only deletes 99-madmin-{interface}.yaml files.
    Does NOT apply automatically - use /apply endpoint.
    """
    _validate_interface_name(interface)
    if interface in await _locked_interfaces(session):
        raise HTTPException(
            status_code=403,
            detail=f"Interface {interface} is externally managed and not modifiable."
        )

    success, message = netplan_service.delete_interface_config(interface)
    
    if not success:
        raise HTTPException(status_code=404, detail=message)
    
    return {"success": True, "message": message}


@router.post("/netplan/apply", response_model=NetworkActionResponse)
async def apply_netplan(
    session: AsyncSession = Depends(get_session),
    _user: User = Depends(require_permission("network.manage"))
):
    """
    Apply netplan configuration.

    WARNING: This may temporarily disrupt network connectivity.
    After apply, the firewall gateway protection is rebuilt to reflect the
    new network topology (new/removed/changed LAN interfaces).
    """
    success, message = netplan_service.apply_netplan()

    if not success:
        raise HTTPException(status_code=500, detail=message)

    try:
        await firewall_orchestrator.apply_rules(session)
    except Exception as e:
        logger.warning(f"Firewall rebuild after netplan apply failed: {e}")

    return {"success": True, "message": message}

