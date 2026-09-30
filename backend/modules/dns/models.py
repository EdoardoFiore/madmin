"""
DNS Module - Database Models

SQLModel tables for DNS zones, records, forwarders, and global settings.
Pydantic schemas for API request/response validation.
"""
import re
import json
from typing import Optional, List
from datetime import datetime
from sqlmodel import Field, SQLModel, Relationship, Column, JSON
from pydantic import field_validator
import uuid

from core import validation


# --- Database Tables ---

class DnsSettings(SQLModel, table=True):
    """Global DNS server settings (singleton row)."""
    __tablename__ = "dns_settings"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    singleton_key: str = Field(default="default", max_length=10, unique=True)
    mode: str = Field(default="recursive", max_length=20)  # recursive, forward_only, non_recursive
    listen_interfaces: str = Field(default="[]", max_length=1000)  # JSON array of interface names
    system_forwarders: str = Field(default='["8.8.8.8", "1.1.1.1"]', max_length=500)  # JSON array of IPs
    allow_query: str = Field(default="localnets", max_length=200)  # "any", "localnets", CIDR list
    dnssec_validation: bool = Field(default=False)
    # Desired runtime state (persisted). True = service should be running; restored on app startup.
    service_enabled: bool = Field(default=False)


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


# --- Pydantic Schemas ---
#
# Every value below ends up in named.conf.options, named.conf.local or a zone
# file, read by the root-started named: a newline, ';', '{', '}' or '"' in any
# of them adds directives or records of the caller's choosing. So each field is
# checked against what it is (an IP, a hostname…); record values, whose grammar
# depends on the record type, are checked by DnsService.validate_record.

_ZONE_TYPES = ("master", "forward", "stub")
_MODES = ("recursive", "forward_only", "non_recursive")
_ACL_KEYWORDS = ("any", "none", "localhost", "localnets")
_RECORD_TYPES = ("A", "AAAA", "CNAME", "MX", "TXT", "SRV", "NS", "PTR")


def _ip_json_list(v, field):
    """A JSON array of IP addresses, as the UI sends forwarders."""
    if v in (None, ""):
        return v
    try:
        items = json.loads(v)
    except (TypeError, ValueError):
        raise ValueError(f"{field}: serve un array JSON di indirizzi IP")
    if not isinstance(items, list):
        raise ValueError(f"{field}: serve un array JSON di indirizzi IP")
    return json.dumps([validation.ip_address(i, field) for i in items])


def _iface_json_list(v):
    if v in (None, ""):
        return v
    try:
        items = json.loads(v)
    except (TypeError, ValueError):
        raise ValueError("listen_interfaces: serve un array JSON di interfacce")
    if not isinstance(items, list) or not all(
        isinstance(i, str) and re.fullmatch(r'[A-Za-z0-9._@-]{1,15}', i) for i in items
    ):
        raise ValueError("listen_interfaces: nome interfaccia non valido")
    return json.dumps(items)


def _acl(v):
    """allow-query: BIND keywords or IP/CIDR entries, separated by ; , or spaces."""
    if v in (None, ""):
        return v
    v = validation.no_control_chars(v, "allow_query", 1000)
    entries = [e for e in re.split(r'[;, ]+', v) if e]
    if not entries:
        raise ValueError("allow_query: vuoto")
    out = []
    for e in entries:
        out.append(e if e in _ACL_KEYWORDS else validation.ip_network(e, "allow_query"))
    return "; ".join(out)


def _zone_name(v):
    if v is None:
        return v
    return validation.hostname(str(v).rstrip("."), "nome zona")


def _seconds(v, field):
    if v is not None and not 0 <= int(v) <= 2_147_483_647:
        raise ValueError(f"{field}: valore non valido")
    return v


class _SettingsValidators(SQLModel):
    @field_validator('mode', mode='before', check_fields=False)
    @classmethod
    def v_mode(cls, v):
        return v if v is None else validation.one_of(v, _MODES, "mode")

    @field_validator('system_forwarders', mode='before', check_fields=False)
    @classmethod
    def v_forwarders(cls, v):
        return _ip_json_list(v, "system_forwarders")

    @field_validator('listen_interfaces', mode='before', check_fields=False)
    @classmethod
    def v_ifaces(cls, v):
        return _iface_json_list(v)

    @field_validator('allow_query', mode='before', check_fields=False)
    @classmethod
    def v_allow_query(cls, v):
        return _acl(v)


class _ZoneValidators(SQLModel):
    @field_validator('name', mode='before', check_fields=False)
    @classmethod
    def v_name(cls, v):
        return _zone_name(v)

    @field_validator('zone_type', mode='before', check_fields=False)
    @classmethod
    def v_type(cls, v):
        return v if v is None else validation.one_of(v, _ZONE_TYPES, "zone_type")

    @field_validator('forward_servers', mode='before', check_fields=False)
    @classmethod
    def v_forward_servers(cls, v):
        return _ip_json_list(v, "forward_servers")

    @field_validator('description', mode='before', check_fields=False)
    @classmethod
    def v_description(cls, v):
        return v if v is None else validation.no_control_chars(v, "descrizione", 500)

    @field_validator('ttl_default', 'soa_refresh', 'soa_retry', 'soa_expire', 'soa_minimum',
                     mode='before', check_fields=False)
    @classmethod
    def v_seconds(cls, v, info):
        return _seconds(v, info.field_name)


class _RecordValidators(SQLModel):
    @field_validator('record_type', mode='before', check_fields=False)
    @classmethod
    def v_type(cls, v):
        return v if v is None else validation.one_of(str(v).upper(), _RECORD_TYPES, "record_type")

    @field_validator('name', 'value', mode='before', check_fields=False)
    @classmethod
    def v_text(cls, v, info):
        return v if v is None else validation.no_control_chars(v, info.field_name, 1000)

    @field_validator('ttl', mode='before', check_fields=False)
    @classmethod
    def v_ttl(cls, v):
        return _seconds(v, "ttl")

    @field_validator('priority', 'weight', 'port', mode='before', check_fields=False)
    @classmethod
    def v_u16(cls, v, info):
        if v is not None and not 0 <= int(v) <= 65535:
            raise ValueError(f"{info.field_name}: 0-65535")
        return v


# Settings
class DnsSettingsRead(SQLModel):
    id: uuid.UUID
    mode: str
    listen_interfaces: str
    system_forwarders: str
    allow_query: str
    dnssec_validation: bool


class DnsSettingsUpdate(_SettingsValidators):
    mode: Optional[str] = None
    listen_interfaces: Optional[str] = None
    system_forwarders: Optional[str] = None
    allow_query: Optional[str] = None
    dnssec_validation: Optional[bool] = None


# Zones
class DnsZoneCreate(_ZoneValidators):
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


class DnsZoneUpdate(_ZoneValidators):
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
class DnsRecordCreate(_RecordValidators):
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


class DnsRecordUpdate(_RecordValidators):
    record_type: Optional[str] = None
    name: Optional[str] = None
    value: Optional[str] = None
    ttl: Optional[int] = None
    priority: Optional[int] = None
    weight: Optional[int] = None
    port: Optional[int] = None


# Service status
class DnsServiceStatus(SQLModel):
    """Service status response."""
    running: bool
    enabled: bool
    uptime: Optional[str] = None
    mode: str = "recursive"
    total_zones: int = 0
    total_records: int = 0
    config_valid: Optional[bool] = None
