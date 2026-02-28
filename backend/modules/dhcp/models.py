"""
DHCP Module - Database Models

SQLModel tables for DHCP subnets, hosts (reservations), and options.
Pydantic schemas for API request/response validation.
"""
from typing import Optional, List
from datetime import datetime
from sqlmodel import Field, SQLModel, Relationship, Column, JSON
import uuid


# --- Database Tables ---

class DhcpSubnet(SQLModel, table=True):
    """DHCP subnet/scope definition."""
    __tablename__ = "dhcp_subnet"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    name: str = Field(max_length=100)
    network: str = Field(max_length=50)          # e.g. "192.168.1.0/24"
    range_start: str = Field(max_length=50)      # e.g. "192.168.1.100"
    range_end: str = Field(max_length=50)        # e.g. "192.168.1.200"
    gateway: str = Field(max_length=50)          # option routers
    dns_servers: str = Field(max_length=255, default="8.8.8.8, 1.1.1.1")  # option domain-name-servers
    domain_name: Optional[str] = Field(default=None, max_length=255)
    interface: str = Field(max_length=50)        # NIC to bind (e.g. "eth0")
    lease_time: int = Field(default=86400)       # default-lease-time in seconds
    max_lease_time: int = Field(default=172800)  # max-lease-time
    enabled: bool = Field(default=True)
    created_at: datetime = Field(default_factory=datetime.utcnow)

    # Relationships
    hosts: List["DhcpHost"] = Relationship(
        back_populates="subnet",
        sa_relationship_kwargs={"cascade": "all, delete-orphan"}
    )
    options: List["DhcpOption"] = Relationship(
        back_populates="subnet",
        sa_relationship_kwargs={"cascade": "all, delete-orphan"}
    )


class DhcpHost(SQLModel, table=True):
    """Static reservation (MAC → IP)."""
    __tablename__ = "dhcp_host"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    subnet_id: uuid.UUID = Field(foreign_key="dhcp_subnet.id", index=True)
    hostname: str = Field(max_length=100)
    mac_address: str = Field(max_length=17)      # AA:BB:CC:DD:EE:FF
    ip_address: str = Field(max_length=50)
    description: str = Field(default="", max_length=255)
    created_at: datetime = Field(default_factory=datetime.utcnow)

    # Relationship
    subnet: "DhcpSubnet" = Relationship(back_populates="hosts")


class DhcpOption(SQLModel, table=True):
    """Custom DHCP option (global or per-subnet)."""
    __tablename__ = "dhcp_option"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    subnet_id: Optional[uuid.UUID] = Field(
        default=None, foreign_key="dhcp_subnet.id", index=True
    )  # NULL = global option
    option_name: str = Field(max_length=100)     # e.g. "ntp-servers"
    option_value: str = Field(max_length=500)    # e.g. "pool.ntp.org"

    # Relationship
    subnet: Optional["DhcpSubnet"] = Relationship(back_populates="options")


# --- Pydantic Schemas ---

class DhcpSubnetCreate(SQLModel):
    name: str
    network: str
    range_start: str
    range_end: str
    gateway: str
    dns_servers: str = "8.8.8.8, 1.1.1.1"
    domain_name: Optional[str] = None
    interface: str
    lease_time: int = 86400
    max_lease_time: int = 172800
    enabled: bool = True


class DhcpSubnetRead(SQLModel):
    id: uuid.UUID
    name: str
    network: str
    range_start: str
    range_end: str
    gateway: str
    dns_servers: str
    domain_name: Optional[str]
    interface: str
    lease_time: int
    max_lease_time: int
    enabled: bool
    created_at: datetime
    host_count: int = 0
    active_leases: int = 0


class DhcpSubnetUpdate(SQLModel):
    name: Optional[str] = None
    range_start: Optional[str] = None
    range_end: Optional[str] = None
    gateway: Optional[str] = None
    dns_servers: Optional[str] = None
    domain_name: Optional[str] = None
    interface: Optional[str] = None
    lease_time: Optional[int] = None
    max_lease_time: Optional[int] = None
    enabled: Optional[bool] = None


class DhcpHostCreate(SQLModel):
    hostname: str
    mac_address: str
    ip_address: str
    description: str = ""


class DhcpHostRead(SQLModel):
    id: uuid.UUID
    subnet_id: uuid.UUID
    hostname: str
    mac_address: str
    ip_address: str
    description: str
    created_at: datetime


class DhcpHostUpdate(SQLModel):
    hostname: Optional[str] = None
    mac_address: Optional[str] = None
    ip_address: Optional[str] = None
    description: Optional[str] = None


class DhcpOptionCreate(SQLModel):
    subnet_id: Optional[uuid.UUID] = None
    option_name: str
    option_value: str


class DhcpOptionRead(SQLModel):
    id: uuid.UUID
    subnet_id: Optional[uuid.UUID]
    option_name: str
    option_value: str


class DhcpLeaseInfo(SQLModel):
    """Parsed lease from dhcpd.leases (not stored in DB)."""
    ip_address: str
    mac_address: Optional[str] = None
    hostname: Optional[str] = None
    starts: Optional[str] = None
    ends: Optional[str] = None
    state: str = "active"       # active, free, expired
    subnet_name: Optional[str] = None


class DhcpServiceStatus(SQLModel):
    """Service status response."""
    running: bool
    enabled: bool
    uptime: Optional[str] = None
    total_subnets: int = 0
    total_hosts: int = 0
    total_leases: int = 0
    config_valid: Optional[bool] = None
