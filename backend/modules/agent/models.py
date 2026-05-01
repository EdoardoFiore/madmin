"""
Agent module models.
HubConfig: singleton row tracking enrollment state and agent token (encrypted).
AgentLog: recent event log for UI display.
PushedSSHKey: tracks SSH keys pushed by Hub (for cleanup on revoke/disable).
"""
from typing import Optional
from datetime import datetime
from sqlmodel import SQLModel, Field


class HubConfig(SQLModel, table=True):
    __tablename__ = "agent_hub_config"

    id: int = Field(default=1, primary_key=True)

    # Hub connection
    hub_url: Optional[str] = Field(default=None, max_length=512)
    instance_id: Optional[str] = Field(default=None, max_length=64)
    instance_name: Optional[str] = Field(default=None, max_length=255)

    # Agent token — 256-bit random, stored Fernet-encrypted
    agent_token_enc: Optional[str] = Field(default=None)

    # Enrollment state
    enrollment_status: str = Field(default="not_enrolled", max_length=32)
    # not_enrolled | enrolled | revoked

    # Runtime state (not persisted across restarts — reset on startup)
    ws_connected: bool = Field(default=False)
    last_heartbeat_at: Optional[datetime] = Field(default=None)

    # TLS
    hub_ca_fingerprint: Optional[str] = Field(default=None, max_length=128)

    # Setup defaults — pre-fill enrollment form (cleared after successful enrollment)
    setup_hub_url: Optional[str] = Field(default=None, max_length=512)
    setup_enrollment_token_enc: Optional[str] = Field(default=None)  # Fernet-encrypted
    setup_instance_name: Optional[str] = Field(default=None, max_length=255)

    enrolled_at: Optional[datetime] = Field(default=None)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    last_telemetry_ts: Optional[datetime] = Field(default=None)


class AgentLog(SQLModel, table=True):
    __tablename__ = "agent_log"

    id: Optional[int] = Field(default=None, primary_key=True)
    ts: datetime = Field(default_factory=datetime.utcnow, index=True)
    level: str = Field(default="info", max_length=16)  # info | warning | error
    event: str = Field(max_length=128)
    detail: Optional[str] = Field(default=None, max_length=1024)


class PushedSSHKey(SQLModel, table=True):
    __tablename__ = "agent_pushed_ssh_key"

    id: Optional[int] = Field(default=None, primary_key=True)
    assignment_id: str = Field(max_length=64, index=True)
    target_user: str = Field(max_length=128, default="madmin")
    public_key: str = Field()
    allow_source_ips: Optional[str] = Field(default=None)  # JSON list
    iptables_rule_added: bool = Field(default=False)
    pushed_at: datetime = Field(default_factory=datetime.utcnow)
    expires_at: Optional[datetime] = Field(default=None)
    revoked_at: Optional[datetime] = Field(default=None)
    active: bool = Field(default=True)
