"""
DHCP Module - Database Models

SQLModel tables for DHCP subnets, hosts (reservations), and options.
Pydantic schemas for API request/response validation.
"""
import re
from typing import Optional, List
from datetime import datetime
from sqlmodel import Field, SQLModel, Relationship, Column, JSON
from pydantic import field_validator, model_validator
import uuid

from core import validation


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
    managed: bool = Field(default=False)         # managed LAN subnet — protected from tampering
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


class DhcpSettings(SQLModel, table=True):
    """Global DHCP service settings (singleton row)."""
    __tablename__ = "dhcp_settings"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    singleton_key: str = Field(default="default", max_length=10, unique=True)
    # Desired runtime state (persisted). True = service should be running; restored on app startup.
    service_enabled: bool = Field(default=False)


# --- Pydantic Schemas ---

# --- Validation ---
#
# Every value below is templated into dhcpd.conf, read by the root-started
# dhcpd: a ';', brace or newline in any of them adds statements of the
# caller's choosing, and `dhcpd -t` accepts them as long as they are well
# formed. These helpers are also used by DhcpService when writing the file, for
# rows that did not come through the API.

MAC_RE = re.compile(r'([0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}')
HOST_DECL_RE = re.compile(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,62}')
IFACE_RE = re.compile(r'[A-Za-z0-9._@-]{1,15}')
OPTION_NAME_RE = re.compile(r'[a-z0-9][a-z0-9-]*(\.[a-z0-9][a-z0-9-]*)?')
# An option value is a quoted string, or a list of IPs/numbers/names/hex bytes
OPTION_VALUE_RE = re.compile(r'"[^"\\;{}]*"|[A-Za-z0-9 .,:_/-]+')


def check_ipv4_list(v, field):
    """dhcpd 'a, b' lists of IPv4 addresses, normalised."""
    items = [i for i in re.split(r'[,\s]+', str(v)) if i]
    if not items:
        raise ValueError(f"{field}: almeno un indirizzo")
    return ", ".join(validation.ip_address(i, field, version=4) for i in items)


def check_option(name, value):
    if not OPTION_NAME_RE.fullmatch(str(name)):
        raise ValueError(f"Nome opzione non valido: {name}")
    validation.no_control_chars(value, "valore opzione", 500)
    if not OPTION_VALUE_RE.fullmatch(str(value)):
        raise ValueError("Valore opzione non valido: una stringa tra virgolette o una lista di IP/numeri/nomi")
    return value


class _SubnetValidators(SQLModel):
    @field_validator('name', mode='before', check_fields=False)
    @classmethod
    def v_name(cls, v):
        return v if v is None else validation.no_control_chars(v, "nome", 100)

    @field_validator('network', mode='before', check_fields=False)
    @classmethod
    def v_network(cls, v):
        if v is None:
            return v
        validation.ip_network(v, "rete", version=4)
        return str(v).strip()

    @field_validator('range_start', 'range_end', 'gateway', mode='before', check_fields=False)
    @classmethod
    def v_ip(cls, v, info):
        return v if v is None else validation.ip_address(v, info.field_name, version=4)

    @field_validator('dns_servers', mode='before', check_fields=False)
    @classmethod
    def v_dns(cls, v):
        return v if v is None else check_ipv4_list(v, "dns_servers")

    @field_validator('domain_name', mode='before', check_fields=False)
    @classmethod
    def v_domain(cls, v):
        return v if v in (None, "") else validation.hostname(v, "domain_name")

    @field_validator('interface', mode='before', check_fields=False)
    @classmethod
    def v_iface(cls, v):
        if v is not None and not IFACE_RE.fullmatch(str(v)):
            raise ValueError(f"Interfaccia non valida: {v}")
        return v

    @field_validator('lease_time', 'max_lease_time', mode='before', check_fields=False)
    @classmethod
    def v_lease(cls, v, info):
        if v is not None and not 60 <= int(v) <= 2_147_483_647:
            raise ValueError(f"{info.field_name}: secondi non validi (min 60)")
        return v


class _HostValidators(SQLModel):
    @field_validator('hostname', mode='before', check_fields=False)
    @classmethod
    def v_hostname(cls, v):
        # Used as the name of the host { } declaration
        if v is not None and not HOST_DECL_RE.fullmatch(str(v)):
            raise ValueError("Hostname non valido: lettere, cifre, '.', '_' o '-' (max 63)")
        return v

    @field_validator('mac_address', mode='before', check_fields=False)
    @classmethod
    def v_mac(cls, v):
        if v is not None and not MAC_RE.fullmatch(str(v)):
            raise ValueError("MAC address non valido (AA:BB:CC:DD:EE:FF)")
        return v

    @field_validator('ip_address', mode='before', check_fields=False)
    @classmethod
    def v_ip(cls, v):
        return v if v is None else validation.ip_address(v, "ip_address", version=4)

    @field_validator('description', mode='before', check_fields=False)
    @classmethod
    def v_description(cls, v):
        return v if v is None else validation.no_control_chars(v, "descrizione", 255)


class DhcpSubnetCreate(_SubnetValidators):
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
    managed: bool = False
    created_at: datetime
    host_count: int = 0
    active_leases: int = 0


class DhcpSubnetUpdate(_SubnetValidators):
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


class DhcpHostCreate(_HostValidators):
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


class DhcpHostUpdate(_HostValidators):
    hostname: Optional[str] = None
    mac_address: Optional[str] = None
    ip_address: Optional[str] = None
    description: Optional[str] = None


class DhcpOptionCreate(SQLModel):
    subnet_id: Optional[uuid.UUID] = None
    option_name: str
    option_value: str

    @model_validator(mode='after')
    def _check(self):
        check_option(self.option_name, self.option_value)
        return self


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
