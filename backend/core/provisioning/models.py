"""
MADMIN Provisioning Models

Singleton settings for the managed LAN (interface + DHCP + NAT).
"""
from typing import Optional
from datetime import datetime
from sqlmodel import SQLModel, Field
from pydantic import BaseModel


class ManagedLanSettings(SQLModel, table=True):
    """
    Managed LAN provisioning state (singleton row, id=1).

    When `enabled`, the boot-time reconciler keeps a single LAN interface
    configured with a static IP, a bound DHCP subnet, and a NAT MASQUERADE
    rule, so VMs behind it always navigate.
    """
    __tablename__ = "managed_lan_settings"

    id: int = Field(default=1, primary_key=True)
    enabled: bool = Field(default=False)            # provisioning active (set by installer flag)
    interface: Optional[str] = Field(default=None, max_length=32)  # resolved at runtime, NOT assumed "eth1"
    address_cidr: str = Field(default="172.25.1.1/24")  # host IP on the iface == gateway pushed by DHCP
    dhcp_range_start: Optional[str] = Field(default=None, max_length=50)
    dhcp_range_end: Optional[str] = Field(default=None, max_length=50)
    dns_servers: str = Field(default="8.8.8.8, 1.1.1.1", max_length=255)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


# --- Pydantic Schemas ---

class ManagedLanResponse(BaseModel):
    """Current managed-LAN provisioning state."""
    enabled: bool
    interface: Optional[str]
    address_cidr: str
    network: Optional[str] = None
    gateway: Optional[str] = None
    dhcp_range_start: Optional[str] = None
    dhcp_range_end: Optional[str] = None
    dns_servers: str
    detected_interface: Optional[str] = None  # what the system currently sees, for the UI


class ManagedLanUpdate(BaseModel):
    """User-editable managed-LAN parameters (network stays user-configurable)."""
    address_cidr: Optional[str] = None
    dhcp_range_start: Optional[str] = None
    dhcp_range_end: Optional[str] = None
    dns_servers: Optional[str] = None
