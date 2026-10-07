"""
MADMIN Firewall Models

Database models for machine firewall rules and module chain registration.
"""
from sqlmodel import SQLModel, Field
from sqlalchemy import Column, BigInteger, UniqueConstraint
from pydantic import field_validator
from typing import Optional, List
from datetime import datetime
import ipaddress
import uuid
import re

from .ports import parse_port_spec


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
    
    # Port: single ("80"), range ("80:443"), or multiport/mixed list combining
    # both ("20:22,49152:50152") — iptables -m multiport allows up to 15 entries,
    # so 20 chars was too tight for anything beyond one short range.
    port: Optional[str] = Field(default=None, max_length=255)
    
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
    # Alternative to the literal `to_destination` above: a DNAT can target an
    # address object instead of a hand-typed IP (cidr /32 or range). Resolved
    # to an effective "ip[:port]"/"a-b[:port]" string at apply time by
    # orchestrator.effective_to_destination(); when set it takes precedence
    # over the literal column (mirrors source/destination refs precedence).
    to_destination_object_id: Optional[uuid.UUID] = Field(
        default=None, foreign_key="firewall_address_object.id"
    )
    to_destination_port: Optional[str] = Field(default=None, max_length=20)
    # nat/POSTROUTING SNAT: --to-source ip[-ip][:ports]. On a filter/FORWARD
    # policy with policy_nat: the single IP its NAT companion uses (SNAT)
    # instead of the interface address (MASQUERADE).
    to_source: Optional[str] = Field(default=None, max_length=50)
    # Alternative to to_source: NAT through an IP pool (same two places)
    nat_pool_id: Optional[uuid.UUID] = Field(default=None, foreign_key="firewall_nat_pool.id")
    to_ports: Optional[str] = Field(default=None, max_length=50)        # REDIRECT/MASQUERADE
    log_prefix: Optional[str] = Field(default=None, max_length=50)      # LOG
    log_level: Optional[str] = Field(default=None, max_length=20)       # LOG
    reject_with: Optional[str] = Field(default=None, max_length=50)     # REJECT
    
    # Outbound NAT intent (forward policies only). When True on a filter/FORWARD
    # rule, apply_rules auto-generates a paired POSTROUTING companion (comment
    # MADMIN_AUTO_NAT_<id>): MASQUERADE, or SNAT toward to_source when set.
    # Outbound NAT is owned by the policies, in their evaluation order;
    # nat/POSTROUTING rules (Advanced) come first as explicit overrides.
    policy_nat: bool = Field(default=False)

    # Hairpin NAT (nat/PREROUTING DNAT rules only). When True, apply_rules
    # auto-generates the companion lines (comment MADMIN_AUTO_HAIRPIN_<id>) that
    # let LAN clients reach this port forward via the WAN IP: a PREROUTING DNAT
    # scoped to each LAN subnet (no -i), a POSTROUTING MASQUERADE so the internal
    # server's reply routes back through the gateway, and a FORWARD ACCEPT for
    # the LAN-sourced flow (the original DNAT's FORWARD companion carries the
    # WAN in_interface and won't match hairpin traffic).
    hairpin: bool = Field(default=False)

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


class RuleTrafficSample(SQLModel, table=True):
    """
    Traffic of a rule over time, for the per-rule sparkline: one row per
    counter snapshot that saw traffic (every 5 minutes and at each apply),
    holding the delta since the previous one. No foreign key: rows of a
    deleted rule simply age out with the retention (7 days).
    """
    __tablename__ = "firewall_rule_traffic"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    rule_id: uuid.UUID = Field(index=True)
    ts: datetime = Field(default_factory=datetime.utcnow, index=True)
    packets: int = Field(default=0, sa_column=Column(BigInteger, nullable=False, default=0))
    bytes: int = Field(default=0, sa_column=Column(BigInteger, nullable=False, default=0))


class ForwardSection(SQLModel, table=True):
    """
    Evaluation order of the filter/FORWARD interface-pair groups.

    Every forward policy belongs to the group of its (in_interface,
    out_interface) pair; "" means any. Each group is one MFWD_* subchain and
    MADMIN_FORWARD jumps to them in `position` order, so this table — not the
    rules' global `order` — decides which group sees a packet first. Rule
    `order` only orders rules within their group.

    Kept in sync with the rules by the orchestrator (sync_forward_sections, run
    on every apply): a new pair is inserted by specificity (both interfaces,
    then one, then none), an empty group is removed, and the admin can reorder
    groups (PUT /firewall/sections/order).
    """
    __tablename__ = "firewall_forward_section"
    __table_args__ = (UniqueConstraint("in_interface", "out_interface"),)

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    in_interface: str = Field(default="", max_length=20)
    out_interface: str = Field(default="", max_length=20)
    position: int = Field(default=0)


class RuleCounter(SQLModel, table=True):
    """
    Durable hit/traffic accumulator for a firewall rule.

    Kernel iptables counters are ephemeral: apply_rules() flushes and rebuilds
    every MADMIN chain on any rule create/edit/delete/reorder (iptables-restore
    `:chain - [0:0]` + `-F`), zeroing per-rule packet/byte counters. This table
    accumulates deltas across those resets so totals — and window_start, the
    "counting since" timestamp — survive rule edits and reboots.

    One row per rule_id (comment `ID_<uuid>` / `MADMIN_AUTO_*_<uuid>` on the
    kernel side, summed across every kernel line a single rule expands to —
    see orchestrator.snapshot_counters). last_packets/last_bytes hold the most
    recent raw kernel snapshot, used only to compute the next delta and detect
    a counter reset (kernel value dropping below the last snapshot).
    """
    __tablename__ = "firewall_rule_counter"

    # No DB-level cascade (matches FirewallRuleAddress convention elsewhere in
    # this module) — delete_rule()/delete_all_rules() remove the row explicitly.
    rule_id: uuid.UUID = Field(foreign_key="machine_firewall_rule.id", primary_key=True)

    # Accumulated totals since window_start. BIGINT: cumulative byte counts on
    # a busy policy overflow a 32-bit INTEGER.
    packets: int = Field(default=0, sa_column=Column(BigInteger, nullable=False))
    bytes: int = Field(default=0, sa_column=Column(BigInteger, nullable=False))

    # Last raw kernel snapshot (not accumulated) — delta/reset baseline.
    last_packets: int = Field(default=0, sa_column=Column(BigInteger, nullable=False))
    last_bytes: int = Field(default=0, sa_column=Column(BigInteger, nullable=False))

    window_start: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


# --- Pydantic Schemas ---

_TO_SOURCE_RE = re.compile(
    r'(\d{1,3}(?:\.\d{1,3}){3})(?:-(\d{1,3}(?:\.\d{1,3}){3}))?(?::(\d{1,5})(?:-(\d{1,5}))?)?'
)


def parse_to_source(value: str):
    """
    SNAT --to-source grammar: ip[-ip][:port[-port]], IPv4 only, a range in
    ascending order. Returns (first_ip, last_ip, port_from, port_to) with None
    for absent parts, or None when the value is not valid.
    """
    m = _TO_SOURCE_RE.fullmatch(value) if value.isascii() else None
    if not m:
        return None
    try:
        first = ipaddress.IPv4Address(m.group(1))
        last = ipaddress.IPv4Address(m.group(2)) if m.group(2) else None
    except ValueError:
        return None
    if last is not None and last < first:
        return None
    p1 = int(m.group(3)) if m.group(3) else None
    p2 = int(m.group(4)) if m.group(4) else None
    if p1 is not None and not 1 <= p1 <= 65535:
        return None
    if p2 is not None and not p1 <= p2 <= 65535:
        return None
    return str(first), str(last) if last else None, p1, p2


_STATES = {"NEW", "ESTABLISHED", "RELATED", "INVALID", "UNTRACKED"}
_LOG_LEVELS = {"emerg", "alert", "crit", "error", "warning", "notice", "info", "debug",
               "0", "1", "2", "3", "4", "5", "6", "7"}
_REJECT_WITH = {
    "icmp-net-unreachable", "icmp-host-unreachable", "icmp-port-unreachable",
    "icmp-proto-unreachable", "icmp-net-prohibited", "icmp-host-prohibited",
    "icmp-admin-prohibited", "tcp-reset",
}


class _FirewallRuleValidators(SQLModel):
    """
    Mixin with shared validators for firewall rule create/update schemas.

    Every field ends up as an iptables argument and, through
    rule_to_restore_line, in the text fed to iptables-restore: a newline or a
    space there adds lines or arguments of the caller's choosing. So each
    field is checked against its own grammar with fullmatch ('$' alone lets a
    trailing newline through).
    """

    @field_validator('to_destination', mode='before', check_fields=False)
    @classmethod
    def validate_ip_port(cls, v):
        if v is None or v == "":
            return None
        if not re.fullmatch(r'[\d.:/-]+', str(v)):
            raise ValueError(f"Formato IP/porta non valido: {v}")
        return v

    @field_validator('to_source', mode='before', check_fields=False)
    @classmethod
    def validate_to_source(cls, v):
        if v is None or v == "":
            return None
        if not parse_to_source(str(v)):
            raise ValueError(f"IP di uscita non valido: {v} (IPv4, range a-b, porta facoltativa :p o :p1-p2)")
        return str(v)

    @field_validator('to_ports', mode='before', check_fields=False)
    @classmethod
    def validate_to_ports(cls, v):
        if v is None or v == "":
            return None
        if not re.fullmatch(r'\d+(-\d+)?', str(v)):
            raise ValueError(f"Formato porta non valido: {v}")
        return v

    @field_validator('source', 'destination', mode='before', check_fields=False)
    @classmethod
    def validate_source_destination(cls, v):
        if v is None or v == "":
            return v
        s = str(v).strip()
        # Literal IPv4 address or CIDR only. A hostname would be resolved by
        # iptables at restore time (at boot, possibly before DNS works) and one
        # unresolvable name fails the whole ruleset: names go in FQDN address
        # objects. Object/group references live in firewall_rule_address.
        try:
            net = ipaddress.ip_network(s, strict=False)
        except ValueError:
            raise ValueError(f"Sorgente/destinazione non valida: {v} (indirizzo IPv4 o CIDR; per i nomi usa un oggetto FQDN)")
        if net.version != 4:
            raise ValueError(f"Sorgente/destinazione non valida: {v} (solo IPv4)")
        return s

    @field_validator('port', mode='before', check_fields=False)
    @classmethod
    def validate_port(cls, v):
        if v is None or v == "":
            return None
        # Single port, range "8000:8080", list "80,443,8000:8080" (see ports.py)
        parse_port_spec(v)
        return str(v)

    @field_validator('protocol', mode='before', check_fields=False)
    @classmethod
    def validate_protocol(cls, v):
        if v is None or v == "":
            return None
        # A protocol name or number as iptables -p takes it (tcp, udp, icmp, gre, 47…)
        if not re.fullmatch(r'[a-z0-9]{1,16}', str(v).lower()):
            raise ValueError(f"Protocollo non valido: {v}")
        return str(v).lower()

    @field_validator('in_interface', 'out_interface', mode='before', check_fields=False)
    @classmethod
    def validate_interface(cls, v):
        if v is None or v == "":
            return None
        # Linux interface name (IFNAMSIZ 15), optionally iptables' "+" wildcard
        if not re.fullmatch(r'[A-Za-z0-9._@-]{1,15}\+?', str(v)):
            raise ValueError(f"Interfaccia non valida: {v}")
        return v

    @field_validator('state', mode='before', check_fields=False)
    @classmethod
    def validate_state(cls, v):
        if v is None or v == "":
            return None
        states = str(v).upper().split(",")
        if not all(s in _STATES for s in states):
            raise ValueError(f"Stato non valido: {v} (ammessi: {', '.join(sorted(_STATES))})")
        return ",".join(states)

    @field_validator('limit_rate', mode='before', check_fields=False)
    @classmethod
    def validate_limit_rate(cls, v):
        if v is None or v == "":
            return None
        if not re.fullmatch(r'\d{1,6}/(second|sec|s|minute|min|m|hour|h|day|d)', str(v)):
            raise ValueError(f"Limite non valido: {v} (es. 10/second, 100/minute)")
        return v

    @field_validator('limit_burst', mode='before', check_fields=False)
    @classmethod
    def validate_limit_burst(cls, v):
        if v is None or v == "":
            return None
        if not 1 <= int(v) <= 100000:
            raise ValueError(f"Burst non valido: {v}")
        return int(v)

    @field_validator('log_level', mode='before', check_fields=False)
    @classmethod
    def validate_log_level(cls, v):
        if v is None or v == "":
            return None
        if str(v).lower() not in _LOG_LEVELS:
            raise ValueError(f"Livello di log non valido: {v}")
        return str(v).lower()

    @field_validator('reject_with', mode='before', check_fields=False)
    @classmethod
    def validate_reject_with(cls, v):
        if v is None or v == "":
            return None
        if v not in _REJECT_WITH:
            raise ValueError(f"reject-with non valido: {v}")
        return v

    @field_validator('log_prefix', mode='before', check_fields=False)
    @classmethod
    def validate_log_prefix(cls, v):
        if v is None or v == "":
            return None
        if not re.fullmatch(r'[A-Za-z0-9_\-. \[\]:]{1,29}', str(v)):
            raise ValueError("Prefisso di log non valido: max 29 caratteri tra lettere, cifre, spazio e _-.[]:")
        return v

    @field_validator('comment', mode='before', check_fields=False)
    @classmethod
    def validate_comment(cls, v):
        if v is None:
            return v
        if len(str(v)) > 255 or any(ord(c) < 32 or ord(c) == 127 for c in str(v)):
            raise ValueError("Commento non valido: max 255 caratteri, niente caratteri di controllo")
        return v

    @field_validator('chain', 'action', 'table_name', mode='before', check_fields=False)
    @classmethod
    def validate_token(cls, v):
        # Checked against per-table allowlists by the router; here just the shape
        if v is None:
            return v
        if not re.fullmatch(r'[A-Za-z_]{1,30}', str(v)):
            raise ValueError(f"Valore non valido: {v}")
        return v

    @field_validator('to_destination_object_id', 'nat_pool_id', mode='before', check_fields=False)
    @classmethod
    def validate_to_destination_object_id(cls, v):
        # Existence is checked by the router; here only the shape
        if v is None or v == "":
            return None
        try:
            return str(uuid.UUID(str(v)))
        except ValueError:
            raise ValueError(f"Identificativo non valido: {v}")

    @field_validator('to_destination_port', mode='before', check_fields=False)
    @classmethod
    def validate_to_destination_port(cls, v):
        if v is None or v == "":
            return None
        s = str(v)
        if not s.isdigit() or not (1 <= int(s) <= 65535):
            raise ValueError(f"Porta interna non valida: {v} (range 1-65535)")
        return s


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
    to_destination_object_id: Optional[str] = None
    to_destination_port: Optional[str] = None
    to_source: Optional[str] = None
    nat_pool_id: Optional[str] = None
    to_ports: Optional[str] = None
    log_prefix: Optional[str] = None
    log_level: Optional[str] = None
    reject_with: Optional[str] = None
    comment: Optional[str] = None
    table_name: str = "filter"
    enabled: bool = True
    policy_nat: bool = False
    hairpin: bool = False
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
    to_destination_object_id: Optional[str] = None
    to_destination_port: Optional[str] = None
    to_source: Optional[str] = None
    nat_pool_id: Optional[str] = None
    to_ports: Optional[str] = None
    log_prefix: Optional[str] = None
    log_level: Optional[str] = None
    reject_with: Optional[str] = None
    comment: Optional[str] = None
    table_name: Optional[str] = None
    enabled: Optional[bool] = None
    policy_nat: Optional[bool] = None
    hairpin: Optional[bool] = None
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
    to_destination_object_id: Optional[str] = None
    to_destination_object_name: Optional[str] = None
    to_destination_port: Optional[str] = None
    to_source: Optional[str]
    nat_pool_id: Optional[str] = None
    nat_pool_name: Optional[str] = None
    to_ports: Optional[str]
    log_prefix: Optional[str]
    log_level: Optional[str]
    reject_with: Optional[str]
    comment: Optional[str]
    table_name: str
    order: int
    enabled: bool
    policy_nat: bool = False  # forward policy owns an outbound MASQUERADE companion
    hairpin: bool = False  # DNAT is reachable from the LAN via the WAN IP (NAT reflection)
    auto_generated: bool = False  # synthetic read-only row (e.g. DNAT/NAT companion)
    # filter rules only: 1-based position in evaluation order within the chain
    # (FORWARD: groups in section order), and an earlier rule that makes this
    # one useless (see shadow.py)
    seq: Optional[int] = None
    shadowed_by: Optional[str] = None
    shadowed_by_seq: Optional[int] = None
    shadow_kind: Optional[str] = None   # shadowed | shadowed_nat | duplicate | redundant
    # policy NAT toward a specific IP that is no longer on the machine
    # (removed from Network): the SNAT is still generated, replies can't return
    nat_warning: Optional[str] = None   # ip_not_local
    created_at: datetime
    updated_at: datetime


class RuleOrderUpdate(SQLModel):
    """Schema for updating rule order."""
    id: str
    order: int


class RuleCounterResponse(SQLModel):
    """Schema for GET /firewall/counters — durable hit/traffic totals per rule."""
    rule_id: str
    packets: int
    bytes: int
    window_start: datetime  # "counting since" — see RuleCounter
    updated_at: datetime    # time range covered = [window_start, updated_at]


class ForwardSectionResponse(SQLModel):
    """GET /firewall/sections: interface-pair groups in evaluation order."""
    id: str
    in_interface: str          # "" = any
    out_interface: str         # "" = any
    position: int
    rule_count: int


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


# --- Outbound NAT pools ---

NAT_POOL_TYPES = ("overload", "one_to_one")


class NatPool(SQLModel, table=True):
    """
    FortiGate-style IP pool a forward policy (or an Advanced SNAT rule) NATs to.

    - overload:   value "a" or "a-b"; SNAT --to-source a-b --persistent
    - one_to_one: value a CIDR; NETMAP --to cidr (the policy's source must be
                  a CIDR of the same size)
    arp_reply: MADMIN adds each address as a /32 on the interface whose subnet
    contains it, so the machine answers ARP for it (see natpool.py); off for
    a block the provider routes to the machine.
    """
    __tablename__ = "firewall_nat_pool"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    name: str = Field(max_length=64, unique=True, index=True)
    type: str = Field(default="overload", max_length=12)
    value: str = Field(max_length=40)
    arp_reply: bool = Field(default=True)
    description: Optional[str] = Field(default=None, max_length=255)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


class _NatPoolValidators(SQLModel):
    @field_validator('name', mode='before', check_fields=False)
    @classmethod
    def validate_name(cls, v):
        if v is None:
            return v
        if not re.fullmatch(r'[A-Za-z0-9 ._()-]{1,64}', str(v)):
            raise ValueError("Nome non valido: max 64 caratteri tra lettere, cifre, spazio e ._()-")
        return str(v).strip()

    @field_validator('type', mode='before', check_fields=False)
    @classmethod
    def validate_type(cls, v):
        if v is not None and v not in NAT_POOL_TYPES:
            raise ValueError(f"Tipo non valido: {v} (overload, one_to_one)")
        return v

    @field_validator('description', mode='before', check_fields=False)
    @classmethod
    def validate_description(cls, v):
        if v is None or v == "":
            return None
        if len(str(v)) > 255 or any(ord(c) < 32 or ord(c) == 127 for c in str(v)):
            raise ValueError("Descrizione non valida: max 255 caratteri, niente caratteri di controllo")
        return v


class NatPoolCreate(_NatPoolValidators):
    name: str
    type: str = "overload"
    value: str
    arp_reply: bool = True
    description: Optional[str] = None


class NatPoolUpdate(_NatPoolValidators):
    name: Optional[str] = None
    type: Optional[str] = None
    value: Optional[str] = None
    arp_reply: Optional[bool] = None
    description: Optional[str] = None


class NatPoolResponse(SQLModel):
    id: str
    name: str
    type: str
    value: str
    arp_reply: bool
    description: Optional[str]
    size: int
    in_use: int = 0                   # rules NATing through it
    interfaces: List[str] = []        # where its /32s go (arp_reply)
    warnings: List[str] = []          # not_on_connected_subnet | overlaps_pool | overlaps_interface_ip
    created_at: datetime
    updated_at: datetime
