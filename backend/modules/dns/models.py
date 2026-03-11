"""
DNS Module - Database Models

SQLModel tables for DNS zones, records, forwarders, and global settings.
Pydantic schemas for API request/response validation.
"""
from typing import Optional, List
from datetime import datetime
from sqlmodel import Field, SQLModel, Relationship, Column, JSON
import uuid


# --- Database Tables ---

class DnsSettings(SQLModel, table=True):
    """Global DNS server settings (singleton row)."""
    __tablename__ = "dns_settings"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    mode: str = Field(default="recursive", max_length=20)  # recursive, forward_only, non_recursive
    listen_interfaces: str = Field(default="[]", max_length=1000)  # JSON array of interface names
    system_forwarders: str = Field(default='["8.8.8.8", "1.1.1.1"]', max_length=500)  # JSON array of IPs
    allow_query: str = Field(default="localnets", max_length=200)  # "any", "localnets", CIDR list
    dnssec_validation: bool = Field(default=False)


class DnsZone(SQLModel, table=True):
    """DNS zone definition."""
    __tablename__ = "dns_zone"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    name: str = Field(max_length=255, index=True)       # e.g. "lab.local"
    zone_type: str = Field(default="master", max_length=20)  # master, forward, stub
    enabled: bool = Field(default=True)
    ttl_default: int = Field(default=3600)               # Default TTL in seconds
    soa_refresh: int = Field(default=3600)
    soa_retry: int = Field(default=600)
    soa_expire: int = Field(default=604800)
    soa_minimum: int = Field(default=86400)
    forward_servers: Optional[str] = Field(default=None, max_length=500)  # JSON array for forward zones
    description: str = Field(default="", max_length=500)
    created_at: datetime = Field(default_factory=datetime.utcnow)

    # Relationships
    records: List["DnsRecord"] = Relationship(
        back_populates="zone",
        sa_relationship_kwargs={"cascade": "all, delete-orphan"}
    )


class DnsRecord(SQLModel, table=True):
    """DNS record within a zone."""
    __tablename__ = "dns_record"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    zone_id: uuid.UUID = Field(foreign_key="dns_zone.id", index=True)
    record_type: str = Field(max_length=10)    # A, AAAA, CNAME, MX, TXT, SRV, NS, PTR
    name: str = Field(max_length=255)          # "@", "www", "mail", etc.
    value: str = Field(max_length=1000)        # IP, hostname, text value
    ttl: Optional[int] = Field(default=None)   # Override zone default TTL
    priority: Optional[int] = Field(default=None)  # MX priority / SRV priority
    weight: Optional[int] = Field(default=None)    # SRV weight
    port: Optional[int] = Field(default=None)      # SRV port
    created_at: datetime = Field(default_factory=datetime.utcnow)

    # Relationship
    zone: "DnsZone" = Relationship(back_populates="records")


class DnsForwarder(SQLModel, table=True):
    """Conditional DNS forwarder (domain → specific DNS servers)."""
    __tablename__ = "dns_forwarder"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    domain: str = Field(max_length=255, index=True)     # e.g. "corp.internal"
    servers: str = Field(max_length=500)                 # JSON array of DNS IPs
    enabled: bool = Field(default=True)
    description: str = Field(default="", max_length=500)
    created_at: datetime = Field(default_factory=datetime.utcnow)


# --- Pydantic Schemas ---

# Settings
class DnsSettingsRead(SQLModel):
    id: uuid.UUID
    mode: str
    listen_interfaces: str
    system_forwarders: str
    allow_query: str
    dnssec_validation: bool


class DnsSettingsUpdate(SQLModel):
    mode: Optional[str] = None
    listen_interfaces: Optional[str] = None
    system_forwarders: Optional[str] = None
    allow_query: Optional[str] = None
    dnssec_validation: Optional[bool] = None


# Zones
class DnsZoneCreate(SQLModel):
    name: str
    zone_type: str = "master"
    enabled: bool = True
    ttl_default: int = 3600
    soa_refresh: int = 3600
    soa_retry: int = 600
    soa_expire: int = 604800
    soa_minimum: int = 86400
    forward_servers: Optional[str] = None
    description: str = ""


class DnsZoneRead(SQLModel):
    id: uuid.UUID
    name: str
    zone_type: str
    enabled: bool
    ttl_default: int
    soa_refresh: int
    soa_retry: int
    soa_expire: int
    soa_minimum: int
    forward_servers: Optional[str]
    description: str
    created_at: datetime
    record_count: int = 0


class DnsZoneUpdate(SQLModel):
    name: Optional[str] = None
    zone_type: Optional[str] = None
    enabled: Optional[bool] = None
    ttl_default: Optional[int] = None
    soa_refresh: Optional[int] = None
    soa_retry: Optional[int] = None
    soa_expire: Optional[int] = None
    soa_minimum: Optional[int] = None
    forward_servers: Optional[str] = None
    description: Optional[str] = None


# Records
class DnsRecordCreate(SQLModel):
    record_type: str
    name: str
    value: str
    ttl: Optional[int] = None
    priority: Optional[int] = None
    weight: Optional[int] = None
    port: Optional[int] = None


class DnsRecordRead(SQLModel):
    id: uuid.UUID
    zone_id: uuid.UUID
    record_type: str
    name: str
    value: str
    ttl: Optional[int]
    priority: Optional[int]
    weight: Optional[int]
    port: Optional[int]
    created_at: datetime


class DnsRecordUpdate(SQLModel):
    record_type: Optional[str] = None
    name: Optional[str] = None
    value: Optional[str] = None
    ttl: Optional[int] = None
    priority: Optional[int] = None
    weight: Optional[int] = None
    port: Optional[int] = None


# Forwarders
class DnsForwarderCreate(SQLModel):
    domain: str
    servers: str  # JSON array
    enabled: bool = True
    description: str = ""


class DnsForwarderRead(SQLModel):
    id: uuid.UUID
    domain: str
    servers: str
    enabled: bool
    description: str
    created_at: datetime


class DnsForwarderUpdate(SQLModel):
    domain: Optional[str] = None
    servers: Optional[str] = None
    enabled: Optional[bool] = None
    description: Optional[str] = None


# Service status
class DnsServiceStatus(SQLModel):
    """Service status response."""
    running: bool
    enabled: bool
    uptime: Optional[str] = None
    mode: str = "recursive"
    total_zones: int = 0
    total_records: int = 0
    total_forwarders: int = 0
    config_valid: Optional[bool] = None
