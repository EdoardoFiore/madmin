"""
IPsec VPN Module - Database Models

SQLModel tables for IPsec tunnels (IKE SA) and Child SAs (Phase 2).
Supports multiple tunnels and multiple Child SAs per tunnel.
"""
import re
from typing import Optional, List
from datetime import datetime
from sqlmodel import Field, SQLModel, Relationship
from core.validation import ModuleRuleValidators
from sqlalchemy import Column, BigInteger
from pydantic import computed_field, field_validator
import uuid
import ipaddress


def validate_cidr(value: str) -> str:
    """Validate CIDR notation for traffic selectors."""
    if not value:
        raise ValueError("CIDR value cannot be empty")
    
    try:
        # Support both single IP and network notation
        if '/' in value:
            ipaddress.ip_network(value, strict=False)
        else:
            # Single IP - treat as /32 or /128
            ipaddress.ip_address(value)
    except ValueError as e:
        raise ValueError(f"Invalid CIDR notation '{value}': {str(e)}")
    
    return value


class IpsecTunnel(SQLModel, table=True):
    """
    IPsec tunnel (Phase 1 - IKE SA).
    
    Represents a site-to-site IPsec connection with IKE negotiation parameters.
    A tunnel can have multiple Child SAs (Phase 2) for different traffic selectors.
    """
    __tablename__ = "ipsec_tunnel"
    
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    name: str = Field(unique=True, max_length=64, index=True)
    enabled: bool = Field(default=True)
    
    # IKE Version and Mode
    ike_version: str = Field(default="2")  # "1" or "2"
    mode: str = Field(default="main")  # "main" or "aggressive" (IKEv1 only)
    
    # Addresses
    local_address: str = Field(default="", max_length=255)  # Local gateway IP (empty = %any)
    remote_address: str = Field(max_length=255)  # Remote peer IP or FQDN
    
    # Identity (optional)
    local_id: Optional[str] = Field(default=None, max_length=255)
    remote_id: Optional[str] = Field(default=None, max_length=255)
    
    # Authentication
    auth_method: str = Field(default="psk")  # "psk" or "pubkey"
    psk: str = Field(default="")  # Pre-Shared Key (stored in secrets)
    
    # IKE Proposal (encryption-integrity-dhgroup)
    ike_proposal: str = Field(default="aes256-sha256-modp2048")
    ike_lifetime: int = Field(default=28800)  # Seconds
    
    # Dead Peer Detection
    dpd_action: str = Field(default="restart")  # "restart", "clear", "none"
    dpd_delay: int = Field(default=30)  # Seconds
    
    # NAT Traversal
    nat_traversal: bool = Field(default=True)
    
    # Status
    status: str = Field(default="disconnected")  # disconnected, connecting, established
    
    # Timestamps
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    
    # Relationships
    child_sas: List["IpsecChildSa"] = Relationship(
        back_populates="tunnel",
        sa_relationship_kwargs={"cascade": "all, delete-orphan"}
    )
    traffic_stats: List["IpsecTrafficStats"] = Relationship(
        back_populates="tunnel",
        sa_relationship_kwargs={"cascade": "all, delete-orphan"}
    )


class IpsecChildSa(SQLModel, table=True):
    """
    IPsec Child SA (Phase 2).
    
    Defines traffic selectors and ESP parameters for encrypted traffic.
    Multiple Child SAs can exist per tunnel for different subnets.
    """
    __tablename__ = "ipsec_child_sa"
    
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    tunnel_id: uuid.UUID = Field(foreign_key="ipsec_tunnel.id", index=True)
    name: str = Field(max_length=64)
    
    # Traffic Selectors (CIDR notation)
    local_ts: str = Field(max_length=100)  # e.g., "192.168.1.0/24"
    remote_ts: str = Field(max_length=100)  # e.g., "10.0.0.0/24"
    
    # ESP Proposal
    esp_proposal: str = Field(default="aes256-sha256-modp2048")
    esp_lifetime: int = Field(default=3600)  # Seconds
    
    # Perfect Forward Secrecy
    pfs_group: Optional[str] = Field(default="modp2048")  # DH group or None
    
    # Actions
    start_action: str = Field(default="trap")  # "none", "start", "trap"
    close_action: str = Field(default="restart")  # "none", "restart", "clear"
    
    enabled: bool = Field(default=True)
    
    # Firewall
    firewall_policy_in: str = Field(default="ACCEPT")  # "ACCEPT" or "DROP"
    firewall_policy_out: str = Field(default="ACCEPT")  # "ACCEPT" or "DROP"
    
    # Relationships
    tunnel: "IpsecTunnel" = Relationship(back_populates="child_sas")
    firewall_rules: List["IpsecTunnelFirewallRule"] = Relationship(
        back_populates="child_sa",
        sa_relationship_kwargs={"cascade": "all, delete-orphan"}
    )


class IpsecTrafficStats(SQLModel, table=True):
    """
    Historical traffic statistics for IPsec tunnels.
    
    Collected periodically to enable historical traffic charts.
    Data is aggregated from all Child SAs of a tunnel.
    """
    __tablename__ = "ipsec_traffic_stats"
    
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    tunnel_id: uuid.UUID = Field(foreign_key="ipsec_tunnel.id", index=True)
    
    # Traffic counters (cumulative values at collection time).
    # BIGINT: cumulative byte counters overflow a 32-bit INTEGER (max ~2.1 GB)
    # on any busy tunnel, which crashes the whole stats INSERT batch.
    bytes_in: int = Field(default=0, sa_column=Column(BigInteger))
    bytes_out: int = Field(default=0, sa_column=Column(BigInteger))
    packets_in: int = Field(default=0, sa_column=Column(BigInteger))
    packets_out: int = Field(default=0, sa_column=Column(BigInteger))

    # Delta values (difference from previous collection)
    bytes_in_delta: int = Field(default=0, sa_column=Column(BigInteger))
    bytes_out_delta: int = Field(default=0, sa_column=Column(BigInteger))
    
    # Timestamp for this data point
    timestamp: datetime = Field(default_factory=datetime.utcnow, index=True)
    
    # Relationship
    tunnel: "IpsecTunnel" = Relationship(back_populates="traffic_stats")


class IpsecTunnelFirewallRule(SQLModel, table=True):
    """
    Firewall rule for IPsec Child SA.
    
    Enables granular traffic control per Child SA with directional rules.
    Rules are applied in order within dedicated iptables chains per Child SA.
    """
    __tablename__ = "ipsec_tunnel_firewall_rule"
    
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    child_sa_id: uuid.UUID = Field(foreign_key="ipsec_child_sa.id", index=True)
    
    # Rule parameters
    direction: str = Field(default="out")  # "in", "out", "both"
    action: str  # "ACCEPT", "DROP"
    protocol: str  # "tcp", "udp", "icmp", "all"
    source: Optional[str] = None  # Optional CIDR override
    destination: Optional[str] = None  # Optional CIDR override
    port: Optional[str] = None  # Single port or range (e.g., "80" or "8000-8100")
    description: str = Field(default="", max_length=255)
    
    # Priority and state
    order: int = Field(default=0, index=True)
    enabled: bool = Field(default=True)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    
    # Relationship
    child_sa: "IpsecChildSa" = Relationship(back_populates="firewall_rules")


# --- Pydantic Schemas for API ---

_NAME_RE = re.compile(r'[a-zA-Z0-9._-]{1,64}')
# One proposal is dash-joined algorithm keywords; several are comma-separated
_PROPOSALS_RE = re.compile(r'[a-z0-9]+(-[a-z0-9]+)*(,[a-z0-9]+(-[a-z0-9]+)*)*')
# IKE identities: IP, FQDN, @fqdn, user@fqdn, keyid:…, or a DN ("C=IT, O=Acme")
_IDENTITY_RE = re.compile(r'[A-Za-z0-9@._:=,+/*%\- ]{1,255}')


def _check_name(v):
    if v is not None and not _NAME_RE.fullmatch(v):
        raise ValueError('Il nome può contenere solo lettere, numeri, punto, trattino e underscore (max 64)')
    return v


def _check_addresses(v, field):
    """swanctl local_addrs/remote_addrs: comma-separated IP, CIDR, FQDN or %any."""
    from core.validation import ip_network, hostname
    if v in (None, ""):
        return v
    for item in str(v).split(","):
        item = item.strip()
        if item == "%any":
            continue
        try:
            ip_network(item, field)
        except ValueError:
            hostname(item, field)
    return str(v).strip()


class _TunnelValidators(SQLModel):
    """
    Every field is written into swanctl.conf or the secrets file, both loaded
    by the root charon daemon: a newline, quote or brace in any of them would
    add configuration of the caller's choosing (another connection, an id
    matching another tunnel's PSK).
    """

    @field_validator('name', mode='before', check_fields=False)
    @classmethod
    def validate_name(cls, v):
        return _check_name(v)

    @field_validator('ike_version', mode='before', check_fields=False)
    @classmethod
    def validate_ike_version(cls, v):
        if v is not None and str(v) not in ("0", "1", "2"):
            raise ValueError("ike_version: 0, 1 o 2")
        return v if v is None else str(v)

    @field_validator('mode', mode='before', check_fields=False)
    @classmethod
    def validate_mode(cls, v):
        if v is not None and v not in ("main", "aggressive"):
            raise ValueError("mode: main o aggressive")
        return v

    @field_validator('auth_method', mode='before', check_fields=False)
    @classmethod
    def validate_auth_method(cls, v):
        if v is not None and v not in ("psk", "pubkey"):
            raise ValueError("auth_method: psk o pubkey")
        return v

    @field_validator('dpd_action', mode='before', check_fields=False)
    @classmethod
    def validate_dpd_action(cls, v):
        if v is not None and v not in ("restart", "clear", "none", "trap", "hold", "start"):
            raise ValueError("dpd_action non valida")
        return v

    @field_validator('local_address', 'remote_address', mode='before', check_fields=False)
    @classmethod
    def validate_addresses(cls, v, info):
        return _check_addresses(v, info.field_name)

    @field_validator('local_id', 'remote_id', mode='before', check_fields=False)
    @classmethod
    def validate_identity(cls, v, info):
        if v in (None, ""):
            return v
        if not _IDENTITY_RE.fullmatch(str(v)):
            raise ValueError(f"{info.field_name}: identità non valida")
        return str(v).strip()

    @field_validator('ike_proposal', mode='before', check_fields=False)
    @classmethod
    def validate_ike_proposal(cls, v):
        if v is not None and not _PROPOSALS_RE.fullmatch(str(v)):
            raise ValueError("Proposal IKE non valida (es. aes256-sha256-modp2048)")
        return v

    @field_validator('psk', mode='before', check_fields=False)
    @classmethod
    def validate_psk(cls, v):
        # Written as secret = "<psk>": a quote or backslash ends the string
        if v in (None, ""):
            return v
        if len(v) > 256 or any(ord(c) < 32 or ord(c) == 127 or c in ('"', '\\') for c in v):
            raise ValueError('La PSK non può contenere virgolette, backslash o caratteri di controllo (max 256)')
        return v

    @field_validator('ike_lifetime', 'dpd_delay', mode='before', check_fields=False)
    @classmethod
    def validate_seconds(cls, v, info):
        if v is not None and not 0 <= int(v) <= 31_536_000:
            raise ValueError(f"{info.field_name}: secondi non validi")
        return v


class IpsecTunnelCreate(_TunnelValidators):
    """Schema for creating a new tunnel."""
    name: str
    ike_version: str = "2"
    mode: str = "main"
    local_address: Optional[str] = ""
    remote_address: str
    local_id: Optional[str] = None
    remote_id: Optional[str] = None
    auth_method: str = "psk"
    psk: str = ""
    ike_proposal: str = "aes256-sha256-modp2048"
    ike_lifetime: int = 28800
    dpd_action: str = "restart"
    dpd_delay: int = 30
    nat_traversal: bool = True


class IpsecTunnelUpdate(_TunnelValidators):
    """Schema for updating a tunnel."""
    name: Optional[str] = None
    enabled: Optional[bool] = None
    ike_version: Optional[str] = None
    mode: Optional[str] = None
    local_address: Optional[str] = None
    remote_address: Optional[str] = None
    local_id: Optional[str] = None
    remote_id: Optional[str] = None
    auth_method: Optional[str] = None
    psk: Optional[str] = None
    ike_proposal: Optional[str] = None
    ike_lifetime: Optional[int] = None
    dpd_action: Optional[str] = None
    dpd_delay: Optional[int] = None
    nat_traversal: Optional[bool] = None


class IpsecTunnelRead(SQLModel):
    """Schema for reading a tunnel."""
    id: uuid.UUID
    name: str
    enabled: bool
    ike_version: str
    mode: str
    local_address: str
    remote_address: str
    local_id: Optional[str]
    remote_id: Optional[str]
    auth_method: str
    ike_proposal: str
    ike_lifetime: int
    dpd_action: str
    dpd_delay: int
    nat_traversal: bool
    status: str
    created_at: datetime
    updated_at: datetime
    child_sa_count: int = 0
    child_sas: List["IpsecChildSaRead"] = []

    @computed_field
    @property
    def conn_name(self) -> str:
        """Name of the connection in charon, derived from the tunnel id.

        Surfaced to the UI because it is the only handle that appears in
        `swanctl` output and in the charon log — the user-facing name never
        does, precisely so that renaming a tunnel cannot orphan anything.
        """
        from modules.strongswan.service import conn_name

        return conn_name(self.id)


class _ChildSaValidators(SQLModel):
    """Child SA fields: written into the children { } block of swanctl.conf."""

    @field_validator('name', mode='before', check_fields=False)
    @classmethod
    def validate_name(cls, v):
        return _check_name(v)

    @field_validator('esp_proposal', mode='before', check_fields=False)
    @classmethod
    def validate_esp_proposal(cls, v):
        if v is not None and not _PROPOSALS_RE.fullmatch(str(v)):
            raise ValueError("Proposal ESP non valida (es. aes256-sha256-modp2048)")
        return v

    @field_validator('pfs_group', mode='before', check_fields=False)
    @classmethod
    def validate_pfs_group(cls, v):
        if v not in (None, "") and not _PROPOSALS_RE.fullmatch(str(v)):
            raise ValueError("Gruppo PFS non valido (es. modp2048)")
        return v

    @field_validator('start_action', mode='before', check_fields=False)
    @classmethod
    def validate_start_action(cls, v):
        if v is not None and v not in ("start", "trap", "none"):
            raise ValueError("start_action: start, trap o none")
        return v

    @field_validator('close_action', mode='before', check_fields=False)
    @classmethod
    def validate_close_action(cls, v):
        if v is not None and v not in ("restart", "trap", "start", "none"):
            raise ValueError("close_action: restart, trap, start o none")
        return v

    @field_validator('esp_lifetime', mode='before', check_fields=False)
    @classmethod
    def validate_esp_lifetime(cls, v):
        if v is not None and not 0 <= int(v) <= 31_536_000:
            raise ValueError("esp_lifetime: secondi non validi")
        return v


class IpsecChildSaCreate(_ChildSaValidators):
    """Schema for creating a Child SA."""
    name: str
    local_ts: str
    remote_ts: str
    esp_proposal: str = "aes256-sha256-modp2048"
    esp_lifetime: int = 3600
    pfs_group: Optional[str] = "modp2048"
    start_action: str = "trap"
    close_action: str = "restart"
    
    @field_validator('local_ts', 'remote_ts')
    @classmethod
    def validate_traffic_selector(cls, v):
        return validate_cidr(v)


class IpsecChildSaUpdate(_ChildSaValidators):
    """Schema for updating a Child SA."""
    name: Optional[str] = None
    local_ts: Optional[str] = None
    remote_ts: Optional[str] = None
    esp_proposal: Optional[str] = None
    esp_lifetime: Optional[int] = None
    pfs_group: Optional[str] = None
    start_action: Optional[str] = None
    close_action: Optional[str] = None
    enabled: Optional[bool] = None
    
    @field_validator('local_ts', 'remote_ts')
    @classmethod
    def validate_traffic_selector(cls, v):
        if v is not None:
            return validate_cidr(v)
        return v


class IpsecChildSaRead(SQLModel):
    """Schema for reading a Child SA."""
    id: uuid.UUID
    tunnel_id: uuid.UUID
    name: str
    local_ts: str
    remote_ts: str
    esp_proposal: str
    esp_lifetime: int
    pfs_group: Optional[str]
    start_action: str
    close_action: str
    enabled: bool
    is_up: bool = False
    firewall_policy_in: str = "ACCEPT"
    firewall_policy_out: str = "ACCEPT"


class IpsecTunnelStatus(SQLModel):
    """Schema for tunnel status from VICI."""
    tunnel_id: uuid.UUID
    ike_state: str  # ESTABLISHED, CONNECTING, DISCONNECTED
    local_host: Optional[str] = None
    remote_host: Optional[str] = None
    initiator: bool = False
    established_time: Optional[int] = None  # Seconds
    rekey_time: Optional[int] = None  # Seconds until rekey
    child_sas: List[dict] = []  # Child SA status


class IpsecFirewallRuleCreate(ModuleRuleValidators):
    """Schema for creating a firewall rule."""
    child_sa_id: uuid.UUID
    direction: str = "out"  # "in", "out", "both"
    action: str  # "ACCEPT", "DROP"
    protocol: str  # "tcp", "udp", "icmp", "all"
    source: Optional[str] = None
    destination: Optional[str] = None
    port: Optional[str] = None
    description: str = ""


class IpsecFirewallRuleRead(SQLModel):
    """Schema for reading a firewall rule."""
    id: uuid.UUID
    child_sa_id: uuid.UUID
    direction: str
    action: str
    protocol: str
    source: Optional[str]
    destination: Optional[str]
    port: Optional[str]
    description: str
    order: int
    enabled: bool
    created_at: datetime


class IpsecFirewallRuleUpdate(ModuleRuleValidators):
    """Schema for updating a firewall rule."""
    direction: Optional[str] = None
    action: Optional[str] = None
    protocol: Optional[str] = None
    source: Optional[str] = None
    destination: Optional[str] = None
    port: Optional[str] = None
    description: Optional[str] = None
    enabled: Optional[bool] = None


class IpsecChildSaFirewallPolicyUpdate(SQLModel):
    """Schema for updating Child SA default firewall policy.
    
    Can update one or both policies.
    """
    policy_in: Optional[str] = None
    policy_out: Optional[str] = None


class IpsecFirewallRulesOrderUpdate(SQLModel):
    """Schema for reordering firewall rules."""
    rules: List[dict]  # [{"id": uuid, "order": int}, ...]
