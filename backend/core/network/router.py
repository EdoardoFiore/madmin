"""
MADMIN Network Router

API endpoints for network interface information and netplan configuration.
"""
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from core.auth.dependencies import get_current_user, require_permission
from core.auth.models import User

from .service import network_service, netplan_service

router = APIRouter(prefix="/api/network", tags=["network"])


class NetplanConfig(BaseModel):
    """Schema for netplan interface configuration."""
    interface: str
    dhcp4: bool = True
    addresses: Optional[List[str]] = None  # e.g., ["192.168.1.100/24"]
    gateway: Optional[str] = None
    dns_servers: Optional[List[str]] = None
    mtu: Optional[int] = None


@router.get("/interfaces")
async def get_network_interfaces(
    _user: User = Depends(get_current_user)
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
    _user: User = Depends(get_current_user)
):
    """Get netplan configuration for a specific interface."""
    config = netplan_service.get_interface_config(interface)
    return {
        "interface": interface,
        "config": config,
        "managed": config.get("managed", False) if config else False
    }


@router.post("/interfaces/{interface}/config")
async def set_interface_config(
    interface: str,
    config: NetplanConfig,
    _user: User = Depends(require_permission("settings.manage"))
):
    """
    Set netplan configuration for an interface.
    
    Creates a new config file: /etc/netplan/99-madmin-{interface}.yaml
    Does NOT apply automatically - use /apply endpoint.
    """
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


@router.delete("/interfaces/{interface}/config")
async def delete_interface_config(
    interface: str,
    _user: User = Depends(require_permission("settings.manage"))
):
    """
    Delete MADMIN-managed netplan config for an interface.
    
    Only deletes 99-madmin-{interface}.yaml files.
    Does NOT apply automatically - use /apply endpoint.
    """
    success, message = netplan_service.delete_interface_config(interface)
    
    if not success:
        raise HTTPException(status_code=404, detail=message)
    
    return {"success": True, "message": message}


@router.post("/netplan/apply")
async def apply_netplan(
    _user: User = Depends(require_permission("settings.manage"))
):
    """
    Apply netplan configuration.
    
    WARNING: This may temporarily disrupt network connectivity.
    """
    success, message = netplan_service.apply_netplan()
    
    if not success:
        raise HTTPException(status_code=500, detail=message)
    
    return {"success": True, "message": message}

