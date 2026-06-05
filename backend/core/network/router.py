"""
MADMIN Network Router

API endpoints for network interface information and netplan configuration.
"""
import ipaddress
import logging
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, field_validator
from sqlalchemy.ext.asyncio import AsyncSession
from core.auth.dependencies import get_current_user, require_permission
from core.auth.models import User
from core.database import get_session
from core.firewall.orchestrator import firewall_orchestrator

from .service import network_service, netplan_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/network", tags=["Network"])

# Interfaces managed externally (e.g. cloud-init) — read-only via API
PROTECTED_INTERFACES = {"eth0"}


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
    if interface in PROTECTED_INTERFACES:
        raise HTTPException(
            status_code=403,
            detail=f"Interface {interface} (WAN) is not modifiable."
        )

    # Managed LAN interface: must stay static; the bound DHCP follows the IP change
    from core.provisioning.service import provisioning_service
    is_managed = await provisioning_service.is_managed_interface(session, interface)
    if is_managed:
        if config.dhcp4:
            raise HTTPException(
                status_code=403,
                detail="Interfaccia LAN gestita: deve restare statica (no DHCP client)."
            )
        if not config.addresses:
            raise HTTPException(
                status_code=400,
                detail="Interfaccia LAN gestita: indirizzo statico obbligatorio."
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

    # Managed interface: apply netplan immediately (so the IP exists) THEN sync the
    # bound DHCP subnet. Otherwise the DHCP pre-flight (subnet must match the live
    # interface IP) would fail because the new IP isn't applied yet.
    if is_managed:
        applied, apply_msg = netplan_service.apply_netplan()
        if not applied:
            raise HTTPException(status_code=500, detail=f"Netplan apply failed: {apply_msg}")
        try:
            await firewall_orchestrator.apply_rules(session)
        except Exception as e:
            logger.warning(f"Firewall rebuild after managed-iface change failed: {e}")
        try:
            await provisioning_service.sync_dhcp_to_interface(session, config.addresses[0])
            await session.commit()
        except Exception as e:
            logger.error(f"Managed LAN DHCP sync failed for {interface}: {e}", exc_info=True)
        return {"success": True, "message": f"{message} (applicato e DHCP sincronizzato)"}

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
    if interface in PROTECTED_INTERFACES:
        raise HTTPException(
            status_code=403,
            detail=f"Interface {interface} (WAN) is not modifiable."
        )

    from core.provisioning.service import provisioning_service
    if await provisioning_service.is_managed_interface(session, interface):
        raise HTTPException(
            status_code=403,
            detail="Interfaccia LAN gestita: configurazione non eliminabile."
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

