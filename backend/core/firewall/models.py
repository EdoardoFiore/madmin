"""
MADMIN Firewall Models

Database models for machine firewall rules and module chain registration.
"""
from sqlmodel import SQLModel, Field
from pydantic import field_validator
from typing import Optional, List
from datetime import datetime
import uuid
import re


class MachineFirewallRule(SQLModel, table=True):
    """
    Machine-level firewall rule managed by the core.
    
    Rules can target any table (filter, nat, mangle, raw) and chain.
    They are routed to the appropriate MADMIN_* chain based on table and chain.
    
    Supported chains per table:
    - filter: INPUT, OUTPUT, FORWARD
    - nat: PREROUTING, OUTPUT, POSTROUTING
    - mangle: PREROUTING, INPUT, FORWARD, OUTPUT, POSTROUTING
    - raw: PREROUTING, OUTPUT
    """
    __tablename__ = "machine_firewall_rule"
    
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    
    # Rule specification
    chain: str = Field(max_length=20, index=True)  # INPUT, OUTPUT, FORWARD, PREROUTING, POSTROUTING
    action: str = Field(max_length=20)  # ACCEPT, DROP, REJECT, MASQUERADE, SNAT, DNAT, etc.
    protocol: Optional[str] = Field(default=None, max_length=10)  # tcp, udp, icmp, all
    
    # Source/Destination
    source: Optional[str] = Field(default=None, max_length=50)  # IP or CIDR
    destination: Optional[str] = Field(default=None, max_length=50)  # IP or CIDR
    
    # Port (single or range like "80" or "80:443")
    port: Optional[str] = Field(default=None, max_length=20)
    
    # Interfaces
    in_interface: Optional[str] = Field(default=None, max_length=20)
    out_interface: Optional[str] = Field(default=None, max_length=20)
    
    # Connection state (NEW, ESTABLISHED, RELATED, INVALID)
    state: Optional[str] = Field(default=None, max_length=50)
    
    # Rate limiting (iptables -m limit)
    limit_rate: Optional[str] = Field(default=None, max_length=20)  # e.g., "10/second", "100/minute"
    limit_burst: Optional[int] = Field(default=None)  # Burst limit for rate limiting

    # Action specific fields
    to_destination: Optional[str] = Field(default=None, max_length=50)  # DNAT
    to_source: Optional[str] = Field(default=None, max_length=50)       # SNAT
    to_ports: Optional[str] = Field(default=None, max_length=50)        # REDIRECT/MASQUERADE
    log_prefix: Optional[str] = Field(default=None, max_length=50)      # LOG
    log_level: Optional[str] = Field(default=None, max_length=20)       # LOG
    reject_with: Optional[str] = Field(default=None, max_length=50)     # REJECT
    
    # Outbound NAT intent (forward policies only). When True on a filter/FORWARD
    # rule, apply_rules auto-generates a paired POSTROUTING MASQUERADE companion
    # (comment MADMIN_AUTO_NAT_<id>), mirroring the DNAT->FORWARD companion. This
    # is how navigation masquerade is owned by the policy instead of a separate
    # standalone POSTROUTING rule.
    policy_nat: bool = Field(default=False)

    # Metadata
    comment: Optional[str] = Field(default=None, max_length=255)
    table_name: str = Field(default="filter", max_length=20)  # filter, nat, mangle, raw
    order: int = Field(default=0, index=True)  # Lower = applied first
    enabled: bool = Field(default=True)
    
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class ModuleChain(SQLModel, table=True):
    """
    Tracks iptables chains registered by modules.
    
    Modules can create their own chains (e.g., MOD_WIREGUARD_FWD)
    that are jumped to from the main chains based on priority.
    Lower priority = earlier in the chain (processed first).
    """
    __tablename__ = "module_chain"
    
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    
    module_id: str = Field(foreign_key="installed_module.id", index=True)
    chain_name: str = Field(unique=True, max_length=50)  # e.g., MOD_WIREGUARD_FWD
    parent_chain: str = Field(max_length=20)  # INPUT, OUTPUT, FORWARD
    priority: int = Field(default=50)  # Lower = processed first
    table_name: str = Field(default="filter", max_length=20)
    
    created_at: datetime = Field(default_factory=datetime.utcnow)


# --- Pydantic Schemas ---

class _FirewallRuleValidators(SQLModel):
    """Mixin with shared validators for firewall rule create/update schemas."""

    @field_validator('to_destination', 'to_source', mode='before', check_fields=False)
    @classmethod
    def validate_ip_port(cls, v):
        if v is None:
            return v
        if not re.match(r'^[\d.:/-]+$', str(v)):
            raise ValueError(f"Formato IP/porta non valido: {v}")
        return v

    @field_validator('to_ports', mode='before', check_fields=False)
    @classmethod
    def validate_to_ports(cls, v):
        if v is None:
            return v
        if not re.match(r'^\d+(-\d+)?$', str(v)):
            raise ValueError(f"Formato porta non valido: {v}")
        return v

    @field_validator('source', 'destination', mode='before', check_fields=False)
    @classmethod
    def validate_source_destination(cls, v):
        if v is None or v == "":
            return v
        s = str(v).strip()
        # Only literal IP / CIDR / hostname-ish (chars allowed by iptables -s/-d).
        # Object/group references live in firewall_rule_address, not here. Legacy
        # "geo:<cc>" tokens are migrated to geo address objects at startup
        # (see backend/main.py), so they are no longer accepted on this field.
        if not re.match(r'^[\w.:/\-]+$', s):
            raise ValueError(f"Sorgente/destinazione non valida: {v}")
        return s

    @field_validator('port', mode='before', check_fields=False)
    @classmethod
    def validate_port(cls, v):
        if v is None:
            return v
        # Accept single port, range "80:443", multiport "80,443,8080"
        parts = re.split(r'[:,]', str(v))
        for p in parts:
            if not p.isdigit() or not (1 <= int(p) <= 65535):
                raise ValueError(f"Porta non valida: {p} (range 1-65535)")
        return v


class RuleAddressRef(SQLModel):
    """Object/group reference in a rule create/update payload (per direction).

    Exactly one of object_id / group_id must be set.
    """
    object_id: Optional[str] = None
    group_id: Optional[str] = None


class MachineFirewallRuleCreate(_FirewallRuleValidators):
    """Schema for creating a firewall rule."""
    chain: str
    action: str
    protocol: Optional[str] = None
    source: Optional[str] = None
    destination: Optional[str] = None
    port: Optional[str] = None
    in_interface: Optional[str] = None
    out_interface: Optional[str] = None
    state: Optional[str] = None
    limit_rate: Optional[str] = None
    limit_burst: Optional[int] = None
    to_destination: Optional[str] = None
    to_source: Optional[str] = None
    to_ports: Optional[str] = None
    log_prefix: Optional[str] = None
    log_level: Optional[str] = None
    reject_with: Optional[str] = None
    comment: Optional[str] = None
    table_name: str = "filter"
    enabled: bool = True
    policy_nat: bool = False
    # Object/group references (multi-select, OR semantics). When non-empty for a
    # direction they take precedence over the literal source/destination field.
    source_refs: Optional[List[RuleAddressRef]] = None
    destination_refs: Optional[List[RuleAddressRef]] = None


class MachineFirewallRuleUpdate(_FirewallRuleValidators):
    """Schema for updating a firewall rule."""
    chain: Optional[str] = None
    action: Optional[str] = None
    protocol: Optional[str] = None
    source: Optional[str] = None
    destination: Optional[str] = None
    port: Optional[str] = None
    in_interface: Optional[str] = None
    out_interface: Optional[str] = None
    state: Optional[str] = None
    limit_rate: Optional[str] = None
    limit_burst: Optional[int] = None
    to_destination: Optional[str] = None
    to_source: Optional[str] = None
    to_ports: Optional[str] = None
    log_prefix: Optional[str] = None
    log_level: Optional[str] = None
    reject_with: Optional[str] = None
    comment: Optional[str] = None
    table_name: Optional[str] = None
    enabled: Optional[bool] = None
    policy_nat: Optional[bool] = None
    source_refs: Optional[List[RuleAddressRef]] = None
    destination_refs: Optional[List[RuleAddressRef]] = None


class RuleAddressRefResponse(SQLModel):
    """A resolved object/group reference, for rendering rule chips in the UI."""
    object_id: Optional[str] = None
    group_id: Optional[str] = None
    name: str
    kind: str                    # "object" | "group"
    type: Optional[str] = None   # object type (cidr/range/fqdn/geo) when kind=object
    value: Optional[str] = None  # raw value (CIDR, FQDN, range, country code)
    resolved_ips: Optional[List[str]] = None  # cached resolution for fqdn/geo


class MachineFirewallRuleResponse(SQLModel):
    """Schema for firewall rule API responses."""
    id: str
    chain: str
    action: str
    protocol: Optional[str]
    source: Optional[str]
    destination: Optional[str]
    source_refs: List[RuleAddressRefResponse] = []
    destination_refs: List[RuleAddressRefResponse] = []
    port: Optional[str]
    in_interface: Optional[str]
    out_interface: Optional[str]
    state: Optional[str]
    limit_rate: Optional[str]
    limit_burst: Optional[int]
    to_destination: Optional[str]
    to_source: Optional[str]
    to_ports: Optional[str]
    log_prefix: Optional[str]
    log_level: Optional[str]
    reject_with: Optional[str]
    comment: Optional[str]
    table_name: str
    order: int
    enabled: bool
    policy_nat: bool = False  # forward policy owns an outbound MASQUERADE companion
    auto_generated: bool = False  # synthetic read-only row (e.g. DNAT/NAT companion)
    created_at: datetime
    updated_at: datetime


class RuleOrderUpdate(SQLModel):
    """Schema for updating rule order."""
    id: str
    order: int


class ModuleChainResponse(SQLModel):
    """Schema for module chain API responses."""
    id: str
    module_id: str
    chain_name: str
    parent_chain: str
    priority: int
    table_name: str


# =============================================================================
# ADDRESS OBJECTS, GROUPS & RULE REFERENCES
# =============================================================================

# Supported address object types.
ADDRESS_OBJECT_TYPES = ("cidr", "range", "fqdn", "geo")


class AddressObject(SQLModel, table=True):
    """
    Reusable address object usable in firewall policies.

    type / value:
    - cidr : "10.0.0.0/24" (a /32 host is allowed)
    - range: "10.0.0.10-10.0.0.50"
    - fqdn : "example.com" (resolved to A records, refreshed daily)
    - geo  : ISO 3166-1 alpha-2 country code (CIDR list from geoip data)

    Every object — geo included — is materialized as a hash:net ipset named
    MADMIN_AO_<ref_key> (uniform naming). resolved_ips caches the last good
    resolution for the dynamic types (fqdn, geo) so a transient failure never
    empties a live set.
    """
    __tablename__ = "firewall_address_object"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    ref_key: str = Field(max_length=12, unique=True, index=True)
    name: str = Field(max_length=64, unique=True, index=True)
    type: str = Field(max_length=10)          # cidr | range | fqdn | geo
    value: str = Field(max_length=255)
    description: Optional[str] = Field(default=None, max_length=255)
    enabled: bool = Field(default=True)
    resolved_ips: Optional[str] = Field(default=None)   # JSON list (fqdn/geo cache)
    resolved_at: Optional[datetime] = Field(default=None)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class AddressGroup(SQLModel, table=True):
    """Named aggregation of address objects, materialized as a list:set ipset
    (MADMIN_AG_<ref_key>) whose members are the leaf object hash:net sets."""
    __tablename__ = "firewall_address_group"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    ref_key: str = Field(max_length=12, unique=True, index=True)
    name: str = Field(max_length=64, unique=True, index=True)
    description: Optional[str] = Field(default=None, max_length=255)
    enabled: bool = Field(default=True)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class AddressGroupMember(SQLModel, table=True):
    """Membership of an object (or, future, a group) in an address group.
    Exactly one of member_object_id / member_group_id is set."""
    __tablename__ = "firewall_address_group_member"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    group_id: uuid.UUID = Field(foreign_key="firewall_address_group.id", index=True)
    member_object_id: Optional[uuid.UUID] = Field(
        default=None, foreign_key="firewall_address_object.id"
    )
    member_group_id: Optional[uuid.UUID] = Field(
        default=None, foreign_key="firewall_address_group.id"
    )  # reserved for nested groups (inactive in v1)


class FirewallRuleAddress(SQLModel, table=True):
    """
    Object/group reference attached to a rule's source or destination.

    Multiple rows per (rule, direction) implement multi-select with OR
    semantics. When rows exist here for a direction they are the source of
    truth and the rule's literal source/destination column is ignored for that
    direction. Exactly one of object_id / group_id is set.
    """
    __tablename__ = "firewall_rule_address"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    rule_id: uuid.UUID = Field(foreign_key="machine_firewall_rule.id", index=True)
    direction: str = Field(max_length=12)     # "source" | "destination"
    object_id: Optional[uuid.UUID] = Field(
        default=None, foreign_key="firewall_address_object.id"
    )
    group_id: Optional[uuid.UUID] = Field(
        default=None, foreign_key="firewall_address_group.id"
    )
    order: int = Field(default=0)


# --- Address object schemas ---

class AddressObjectCreate(SQLModel):
    name: str
    type: str
    value: str
    description: Optional[str] = None
    enabled: bool = True


class AddressObjectUpdate(SQLModel):
    name: Optional[str] = None
    type: Optional[str] = None
    value: Optional[str] = None
    description: Optional[str] = None
    enabled: Optional[bool] = None


class AddressObjectResponse(SQLModel):
    id: str
    ref_key: str
    name: str
    type: str
    value: str
    description: Optional[str]
    enabled: bool
    resolved_ips: Optional[List[str]] = None
    resolved_at: Optional[datetime] = None
    set_name: str             # MADMIN_AO_<ref_key>
    created_at: datetime
    updated_at: datetime


# --- Address group schemas ---

class AddressGroupMemberRef(SQLModel):
    """A member reference in a group create/update payload (object or group)."""
    object_id: Optional[str] = None
    group_id: Optional[str] = None


class AddressGroupMemberResponse(SQLModel):
    object_id: Optional[str] = None
    group_id: Optional[str] = None
    name: str                 # member display name
    kind: str                 # "object" | "group"
    type: Optional[str] = None  # object type when kind == "object"


class AddressGroupCreate(SQLModel):
    name: str
    description: Optional[str] = None
    enabled: bool = True
    members: List[AddressGroupMemberRef] = []


class AddressGroupUpdate(SQLModel):
    name: Optional[str] = None
    description: Optional[str] = None
    enabled: Optional[bool] = None
    members: Optional[List[AddressGroupMemberRef]] = None


class AddressGroupResponse(SQLModel):
    id: str
    ref_key: str
    name: str
    description: Optional[str]
    enabled: bool
    set_name: str             # MADMIN_AG_<ref_key>
    members: List[AddressGroupMemberResponse] = []
    created_at: datetime
    updated_at: datetime
