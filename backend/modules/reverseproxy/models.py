"""
Reverse Proxy Module - Database Models

Proxy hosts (source domain → backend), access lists (HTTP basic auth + IP rules)
and Let's Encrypt certificates.
"""
from typing import Optional, List
from datetime import datetime
from sqlmodel import Field, SQLModel, Relationship, JSON, Column
from sqlalchemy import Text
import uuid


class RevproxyHost(SQLModel, table=True):
    """Single proxy host (one or more source domains → one backend)."""
    __tablename__ = "revproxy_host"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    name: str = Field(max_length=100)

    # Upstream
    forward_scheme: str = Field(default="http", max_length=10)  # "http" | "https"
    forward_host: str = Field(max_length=255)
    forward_port: int = Field()

    # Access control
    access_list_id: Optional[uuid.UUID] = Field(
        default=None, foreign_key="revproxy_access_list.id"
    )

    # Behavior toggles
    force_https: bool = Field(default=False)
    http2_support: bool = Field(default=True)
    block_exploits: bool = Field(default=True)
    caching_enabled: bool = Field(default=False)
    websockets_support: bool = Field(default=False)

    # Free-form per-host nginx snippet
    custom_nginx_config: str = Field(default="", sa_column=Column(Text))

    enabled: bool = Field(default=True)
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    # Relationships
    domains: List["RevproxyHostDomain"] = Relationship(
        back_populates="host",
        sa_relationship_kwargs={"cascade": "all, delete-orphan"},
    )
    certificate: Optional["RevproxyCertificate"] = Relationship(
        back_populates="host",
        sa_relationship_kwargs={"cascade": "all, delete-orphan", "uselist": False},
    )


class RevproxyHostDomain(SQLModel, table=True):
    """Source domain attached to a proxy host (server_name entry)."""
    __tablename__ = "revproxy_host_domain"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    host_id: uuid.UUID = Field(foreign_key="revproxy_host.id", index=True)
    domain: str = Field(unique=True, max_length=255, index=True)

    host: Optional[RevproxyHost] = Relationship(back_populates="domains")


class RevproxyAccessList(SQLModel, table=True):
    """Reusable access list — HTTP basic auth + allow/deny IP rules."""
    __tablename__ = "revproxy_access_list"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    name: str = Field(unique=True, max_length=100)

    # If True: auth OR rules satisfy (nginx `satisfy any`); else AND
    satisfy_any: bool = Field(default=False)
    # Forward Authorization header to backend
    pass_auth_to_upstream: bool = Field(default=False)

    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    auths: List["RevproxyAccessListAuth"] = Relationship(
        back_populates="access_list",
        sa_relationship_kwargs={"cascade": "all, delete-orphan"},
    )
    rules: List["RevproxyAccessListRule"] = Relationship(
        back_populates="access_list",
        sa_relationship_kwargs={"cascade": "all, delete-orphan"},
    )


class RevproxyAccessListAuth(SQLModel, table=True):
    """Single basic-auth user in an access list."""
    __tablename__ = "revproxy_access_list_auth"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    access_list_id: uuid.UUID = Field(
        foreign_key="revproxy_access_list.id", index=True
    )
    username: str = Field(max_length=100)
    # bcrypt hash compatible with `htpasswd -B` ($2y$...). Never returned in API.
    password_hash: str = Field(max_length=255)

    access_list: Optional[RevproxyAccessList] = Relationship(back_populates="auths")


class RevproxyAccessListRule(SQLModel, table=True):
    """Single allow/deny rule (IP or CIDR)."""
    __tablename__ = "revproxy_access_list_rule"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    access_list_id: uuid.UUID = Field(
        foreign_key="revproxy_access_list.id", index=True
    )
    action: str = Field(max_length=10)  # "allow" | "deny"
    subject: str = Field(max_length=50)  # IP or CIDR
    order: int = Field(default=0)

    access_list: Optional[RevproxyAccessList] = Relationship(back_populates="rules")


class RevproxyCertificate(SQLModel, table=True):
    """TLS certificate metadata for a proxy host."""
    __tablename__ = "revproxy_certificate"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    host_id: uuid.UUID = Field(
        foreign_key="revproxy_host.id", unique=True, index=True
    )

    provider: str = Field(default="letsencrypt", max_length=20)  # "letsencrypt"|"custom"
    domain: str = Field(max_length=255)  # primary domain on the cert
    san_domains: List[str] = Field(default=[], sa_column=Column(JSON))

    cert_path: str = Field(max_length=500)
    key_path: str = Field(max_length=500)

    issued_at: Optional[datetime] = None
    expires_at: Optional[datetime] = None
    last_renewal_attempt: Optional[datetime] = None
    last_renewal_status: Optional[str] = Field(default=None, max_length=255)
    auto_renew: bool = Field(default=True)

    created_at: datetime = Field(default_factory=datetime.utcnow)

    host: Optional[RevproxyHost] = Relationship(back_populates="certificate")


# --- Pydantic schemas ---


class RevproxyHostDomainRead(SQLModel):
    id: uuid.UUID
    domain: str


class RevproxyCertificateRead(SQLModel):
    id: uuid.UUID
    provider: str
    domain: str
    san_domains: List[str]
    expires_at: Optional[datetime]
    last_renewal_status: Optional[str]
    auto_renew: bool


class RevproxyHostRead(SQLModel):
    id: uuid.UUID
    name: str
    forward_scheme: str
    forward_host: str
    forward_port: int
    access_list_id: Optional[uuid.UUID]
    force_https: bool
    http2_support: bool
    block_exploits: bool
    caching_enabled: bool
    websockets_support: bool
    custom_nginx_config: str
    enabled: bool
    created_at: datetime
    updated_at: datetime
    domains: List[RevproxyHostDomainRead] = []
    certificate: Optional[RevproxyCertificateRead] = None


class RevproxyHostCreate(SQLModel):
    name: str
    domains: List[str]
    forward_scheme: str = "http"
    forward_host: str
    forward_port: int
    access_list_id: Optional[uuid.UUID] = None
    force_https: bool = False
    http2_support: bool = True
    block_exploits: bool = True
    caching_enabled: bool = False
    websockets_support: bool = False
    custom_nginx_config: str = ""


class RevproxyHostUpdate(SQLModel):
    name: Optional[str] = None
    domains: Optional[List[str]] = None
    forward_scheme: Optional[str] = None
    forward_host: Optional[str] = None
    forward_port: Optional[int] = None
    access_list_id: Optional[uuid.UUID] = None
    force_https: Optional[bool] = None
    http2_support: Optional[bool] = None
    block_exploits: Optional[bool] = None
    caching_enabled: Optional[bool] = None
    websockets_support: Optional[bool] = None
    custom_nginx_config: Optional[str] = None
    enabled: Optional[bool] = None


class RevproxyAccessListAuthRead(SQLModel):
    id: uuid.UUID
    username: str


class RevproxyAccessListAuthCreate(SQLModel):
    username: str
    password: str  # plaintext from client; never persisted


class RevproxyAccessListRuleRead(SQLModel):
    id: uuid.UUID
    action: str
    subject: str
    order: int


class RevproxyAccessListRuleCreate(SQLModel):
    action: str
    subject: str
    order: int = 0


class RevproxyAccessListRead(SQLModel):
    id: uuid.UUID
    name: str
    satisfy_any: bool
    pass_auth_to_upstream: bool
    auths: List[RevproxyAccessListAuthRead] = []
    rules: List[RevproxyAccessListRuleRead] = []
    hosts_count: int = 0


class RevproxyAccessListCreate(SQLModel):
    name: str
    satisfy_any: bool = False
    pass_auth_to_upstream: bool = False
    auths: List[RevproxyAccessListAuthCreate] = []
    rules: List[RevproxyAccessListRuleCreate] = []


class RevproxyAccessListUpdate(SQLModel):
    name: Optional[str] = None
    satisfy_any: Optional[bool] = None
    pass_auth_to_upstream: Optional[bool] = None
    # If provided, fully replaces existing rows
    auths: Optional[List[RevproxyAccessListAuthCreate]] = None
    rules: Optional[List[RevproxyAccessListRuleCreate]] = None
