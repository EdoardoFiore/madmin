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

    When `enabled`, the boot-time reconciler keeps a bound DHCP subnet and a NAT
    MASQUERADE rule aligned to the managed LAN interface, so VMs behind it always
    navigate. The interface IP itself is assigned externally (by the WAN-managing
    software); MADMIN does not set it.
    """
    __tablename__ = "managed_lan_settings"

    id: int = Field(default=1, primary_key=True)
    enabled: bool = Field(default=False)            # provisioning active (set by installer flag)
    interface: Optional[str] = Field(default=None, max_length=32)  # resolved at runtime, NOT assumed "eth1"
    # Last OBSERVED live host CIDR of the interface (informational/display only).
    # The DHCP subnet + gateway are derived from the live IP, not from this field.
    address_cidr: str = Field(default="172.25.1.1/24")
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
    """
    User-editable managed-LAN DHCP parameters. The interface IP/subnet is NOT
    here: it is externally assigned and the subnet is derived from the live IP.
    """
    dhcp_range_start: Optional[str] = None
    dhcp_range_end: Optional[str] = None
    dns_servers: Optional[str] = None
