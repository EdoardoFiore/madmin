"""
MADMIN Firewall Models

Database models for machine firewall rules and module chain registration.
"""
from sqlmodel import SQLModel, Field
from typing import Optional
from datetime import datetime
import uuid


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

class MachineFirewallRuleCreate(SQLModel):
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
    comment: Optional[str] = None
    table_name: str = "filter"
    enabled: bool = True


class MachineFirewallRuleUpdate(SQLModel):
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
    comment: Optional[str] = None
    table_name: Optional[str] = None
    enabled: Optional[bool] = None


class MachineFirewallRuleResponse(SQLModel):
    """Schema for firewall rule API responses."""
    id: str
    chain: str
    action: str
    protocol: Optional[str]
    source: Optional[str]
    destination: Optional[str]
    port: Optional[str]
    in_interface: Optional[str]
    out_interface: Optional[str]
    state: Optional[str]
    limit_rate: Optional[str]
    limit_burst: Optional[int]
    comment: Optional[str]
    table_name: str
    order: int
    enabled: bool
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
