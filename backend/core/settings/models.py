"""
MADMIN Settings Models

Database models for system configuration.
All settings tables are singleton (only id=1 used).
"""
from sqlmodel import SQLModel, Field
from core import validation
from pydantic import BaseModel, field_validator
from sqlalchemy import Column, BigInteger, Text
from typing import List, Optional
from datetime import datetime
import re


class SystemStatsHistory(SQLModel, table=True):
    """
    Historical system statistics for dashboard graphs.
    Stores CPU, RAM, Disk usage over time.
    """
    __tablename__ = "system_stats_history"
    
    id: Optional[int] = Field(default=None, primary_key=True)
    timestamp: datetime = Field(default_factory=datetime.utcnow, index=True)
    cpu_percent: float = Field(default=0.0)
    ram_percent: float = Field(default=0.0)
    ram_used: int = Field(default=0, sa_column=Column(BigInteger))
    ram_total: int = Field(default=0, sa_column=Column(BigInteger))
    disk_percent: float = Field(default=0.0)
    disk_used: int = Field(default=0, sa_column=Column(BigInteger))
    disk_total: int = Field(default=0, sa_column=Column(BigInteger))


class NetworkTrafficHistory(SQLModel, table=True):
    """
    Historical network traffic per interface for dashboard graphs.
    Stores cumulative bytes sent/received snapshots every 60s.
    """
    __tablename__ = "network_traffic_history"
    
    id: Optional[int] = Field(default=None, primary_key=True)
    timestamp: datetime = Field(default_factory=datetime.utcnow, index=True)
    interface: str = Field(max_length=50, index=True)
    bytes_sent: int = Field(default=0, sa_column=Column(BigInteger))
    bytes_recv: int = Field(default=0, sa_column=Column(BigInteger))



class SystemSettings(SQLModel, table=True):
    """
    Portal customization settings.
    Singleton table (only id=1 used).
    """
    __tablename__ = "system_settings"
    
    id: int = Field(default=1, primary_key=True)
    company_name: str = Field(default="MADMIN", max_length=100)
    primary_color: str = Field(default="#206bc4", max_length=20)
    logo_url: Optional[str] = Field(default=None, max_length=255)
    favicon_url: Optional[str] = Field(default=None, max_length=255)
    support_url: Optional[str] = Field(default=None, max_length=255)
    default_language: str = Field(default="en", max_length=10)

    # Password policy
    password_max_age_days: int = Field(default=0)  # 0 = expiry disabled

    # WAN edit protection: when True, the WAN interface (eth0) config is read-only
    # (set via installer flag --protect-wan). Default False = WAN freely editable.
    wan_protection_enabled: bool = Field(default=False)

    updated_at: datetime = Field(default_factory=datetime.utcnow)


class SMTPSettings(SQLModel, table=True):
    """
    SMTP configuration for sending emails.
    Singleton table (only id=1 used).
    """
    __tablename__ = "smtp_settings"
    
    id: int = Field(default=1, primary_key=True)
    smtp_host: str = Field(default="", max_length=255)
    smtp_port: int = Field(default=587)
    smtp_encryption: str = Field(default="tls", max_length=10)  # none, tls, ssl
    smtp_username: Optional[str] = Field(default=None, max_length=255)
    smtp_password: Optional[str] = Field(default=None, max_length=512)  # encrypted (core.secrets)
    sender_email: str = Field(default="noreply@localhost", max_length=255)
    sender_name: str = Field(default="MADMIN", max_length=100)
    public_download_url: Optional[str] = Field(default=None, max_length=255)

    updated_at: datetime = Field(default_factory=datetime.utcnow)


class BackupSettings(SQLModel, table=True):
    """
    Backup configuration.
    Singleton table (only id=1 used).
    """
    __tablename__ = "backup_settings"
    
    id: int = Field(default=1, primary_key=True)
    enabled: bool = Field(default=False)
    frequency: str = Field(default="daily", max_length=20)  # daily, weekly
    time: str = Field(default="03:00", max_length=10)
    
    # Remote storage settings
    remote_protocol: str = Field(default="sftp", max_length=10)  # sftp, ftps
    remote_host: str = Field(default="", max_length=255)
    remote_port: int = Field(default=22)
    remote_user: str = Field(default="", max_length=100)
    remote_password: str = Field(default="", max_length=512)  # encrypted (core.secrets)
    remote_path: str = Field(default="/", max_length=255)
    # SFTP server key pinned at the first connection ("<type> SHA256:<b64>");
    # cleared when host or port change, or on request
    remote_host_key: Optional[str] = Field(default=None, max_length=255)

    # Archives are encrypted when set (encrypted at rest, never returned)
    encryption_passphrase: Optional[str] = Field(default=None, max_length=512)
    
    last_run_status: Optional[str] = Field(default=None, max_length=50)
    last_run_time: Optional[datetime] = Field(default=None)
    
    # Retention policy
    retention_days: int = Field(default=30)  # 0 = keep forever

    updated_at: datetime = Field(default_factory=datetime.utcnow)


class SyslogSettings(SQLModel, table=True):
    """
    External syslog forwarding for audit log entries (RFC 5424).
    Singleton table (only id=1 used).
    """
    __tablename__ = "syslog_settings"

    id: int = Field(default=1, primary_key=True)
    enabled: bool = Field(default=False)
    host: str = Field(default="", max_length=255)
    port: int = Field(default=514)
    protocol: str = Field(default="udp", max_length=10)      # udp | tcp | tls
    facility: int = Field(default=16)                         # 16-23 = local0-local7
    app_name: str = Field(default="madmin", max_length=48)   # RFC5424 APP-NAME

    # Event filter
    forward_reads: bool = Field(default=False)               # include GET/read entries
    min_status: int = Field(default=0)                       # 0 = all; 400 = errors only

    # TLS (transport=tls). CA cert is a PEM blob, not a secret but voluminous.
    tls_ca_cert: Optional[str] = Field(default=None, sa_column=Column(Text))
    tls_verify: bool = Field(default=True)

    # Feedback (mirrors BackupSettings.last_run_status)
    last_error: Optional[str] = Field(default=None, max_length=500)
    last_sent_at: Optional[datetime] = Field(default=None)

    updated_at: datetime = Field(default_factory=datetime.utcnow)


# --- Pydantic Schemas ---

class SystemSettingsUpdate(SQLModel):
    """Schema for updating system settings."""
    company_name: Optional[str] = None
    primary_color: Optional[str] = None
    logo_url: Optional[str] = None
    favicon_url: Optional[str] = None
    support_url: Optional[str] = None
    default_language: Optional[str] = None
    password_max_age_days: Optional[int] = None
    wan_protection_enabled: Optional[bool] = None

    @field_validator('password_max_age_days', mode='before')
    @classmethod
    def validate_max_age(cls, v):
        if v is None:
            return v
        if int(v) < 0:
            raise ValueError("password_max_age_days must be >= 0 (0 = disabled)")
        return int(v)

    @field_validator('primary_color', mode='before')
    @classmethod
    def validate_color(cls, v):
        if v is None:
            return v
        if not re.match(r'^#(?:[0-9a-fA-F]{3}){1,2}$', str(v)):
            raise ValueError("Invalid color: must be hexadecimal (#RGB or #RRGGBB)")
        return v

    @field_validator('logo_url', 'favicon_url', 'support_url', mode='before')
    @classmethod
    def validate_url(cls, v):
        if not v:  # None or empty string — router converts '' to None
            return v
        v_str = str(v)
        if v_str.startswith('//'):
            raise ValueError("Unsafe URL: protocol-relative URLs not allowed")
        if not v_str.startswith(('http://', 'https://', '/')):
            raise ValueError("Unsafe URL: only http/https allowed")
        return v


class SystemSettingsResponse(SQLModel):
    """Response schema for system settings."""
    company_name: str
    primary_color: str
    logo_url: Optional[str]
    favicon_url: Optional[str]
    support_url: Optional[str]
    default_language: str = "en"
    password_max_age_days: int = 0
    wan_protection_enabled: bool = False
    updated_at: datetime


class SMTPSettingsUpdate(SQLModel):
    """Schema for updating SMTP settings."""
    smtp_host: Optional[str] = None
    smtp_port: Optional[int] = None
    smtp_encryption: Optional[str] = None
    smtp_username: Optional[str] = None
    smtp_password: Optional[str] = None
    sender_email: Optional[str] = None
    sender_name: Optional[str] = None
    public_download_url: Optional[str] = None


class SMTPSettingsResponse(SQLModel):
    """Response schema for SMTP settings (excludes password)."""
    smtp_host: str
    smtp_port: int
    smtp_encryption: str
    smtp_username: Optional[str]
    sender_email: str
    sender_name: str
    public_download_url: Optional[str]
    updated_at: datetime


class BackupSettingsUpdate(SQLModel):
    """Schema for updating backup settings."""
    enabled: Optional[bool] = None
    frequency: Optional[str] = None
    time: Optional[str] = None
    retention_days: Optional[int] = None
    remote_protocol: Optional[str] = None
    remote_host: Optional[str] = None
    remote_port: Optional[int] = None
    remote_user: Optional[str] = None
    remote_password: Optional[str] = None
    remote_path: Optional[str] = None
    # "" removes it (new archives unencrypted); min 12 characters otherwise
    encryption_passphrase: Optional[str] = None

    @field_validator('remote_protocol', mode='before')
    @classmethod
    def _protocol(cls, v):
        # Plain FTP is gone: credentials and archives travelled in clear.
        # "ftp" (older settings, restored archives) now means FTPS.
        if v is None:
            return v
        v = "ftps" if v == "ftp" else v
        return validation.one_of(v, ("sftp", "ftps"), "remote_protocol")

    @field_validator('frequency', mode='before')
    @classmethod
    def _frequency(cls, v):
        return v if v is None else validation.one_of(v, ("daily", "weekly"), "frequency")

    @field_validator('time', mode='before')
    @classmethod
    def _time(cls, v):
        if v is not None and not re.fullmatch(r'([01]\d|2[0-3]):[0-5]\d', str(v)):
            raise ValueError("time: formato HH:MM")
        return v

    @field_validator('remote_host', mode='before')
    @classmethod
    def _host(cls, v):
        return v if v in (None, "") else validation.host(v, "remote_host")

    @field_validator('remote_port', mode='before')
    @classmethod
    def _port(cls, v):
        return v if v is None else int(validation.port(v))

    @field_validator('remote_user', 'remote_path', mode='before')
    @classmethod
    def _text(cls, v, info):
        return v if v is None else validation.no_control_chars(v, info.field_name)

    @field_validator('encryption_passphrase', mode='before')
    @classmethod
    def _passphrase(cls, v):
        if v in (None, ""):
            return v
        validation.no_control_chars(v, "passphrase", 256)
        if len(v) < 12:
            raise ValueError("La passphrase deve avere almeno 12 caratteri")
        return v


class BackupSettingsResponse(SQLModel):
    """Response schema for backup settings (excludes password)."""
    enabled: bool
    frequency: str
    time: str
    retention_days: int
    remote_protocol: str
    remote_host: str
    remote_port: int
    remote_user: str
    remote_path: str
    remote_host_key: Optional[str] = None
    encryption_enabled: bool = False
    last_run_status: Optional[str]
    last_run_time: Optional[datetime]
    updated_at: datetime


class SyslogSettingsUpdate(SQLModel):
    """Schema for updating syslog settings (partial PATCH)."""
    enabled: Optional[bool] = None
    host: Optional[str] = None
    port: Optional[int] = None
    protocol: Optional[str] = None
    facility: Optional[int] = None
    app_name: Optional[str] = None
    forward_reads: Optional[bool] = None
    min_status: Optional[int] = None
    tls_ca_cert: Optional[str] = None
    tls_verify: Optional[bool] = None

    @field_validator('protocol', mode='before')
    @classmethod
    def validate_protocol(cls, v):
        if v is None:
            return v
        if str(v).lower() not in ('udp', 'tcp', 'tls'):
            raise ValueError("protocol must be one of: udp, tcp, tls")
        return str(v).lower()

    @field_validator('port', mode='before')
    @classmethod
    def validate_port(cls, v):
        if v is None:
            return v
        if not (1 <= int(v) <= 65535):
            raise ValueError("port must be between 1 and 65535")
        return int(v)

    @field_validator('facility', mode='before')
    @classmethod
    def validate_facility(cls, v):
        if v is None:
            return v
        if not (16 <= int(v) <= 23):
            raise ValueError("facility must be between 16 (local0) and 23 (local7)")
        return int(v)

    @field_validator('host', mode='before')
    @classmethod
    def validate_host(cls, v):
        return v if v in (None, "") else validation.host(v, "host")

    @field_validator('app_name', mode='before')
    @classmethod
    def validate_app_name(cls, v):
        # RFC 5424 APP-NAME: printable US-ASCII without spaces, max 48
        if v in (None, ""):
            return v
        if not re.fullmatch(r'[!-~]{1,48}', str(v)):
            raise ValueError("app_name: 1-48 caratteri ASCII stampabili, senza spazi")
        return v

    @field_validator('tls_ca_cert', mode='before')
    @classmethod
    def validate_tls_ca_cert(cls, v):
        if v in (None, ""):
            return v
        v = str(v).strip()
        if len(v) > 20000 or "-----BEGIN CERTIFICATE-----" not in v:
            raise ValueError("tls_ca_cert: certificato PEM non valido")
        return v

    @field_validator('min_status', mode='before')
    @classmethod
    def validate_min_status(cls, v):
        if v is None:
            return v
        if int(v) < 0:
            raise ValueError("min_status must be >= 0")
        return int(v)


class SyslogSettingsResponse(SQLModel):
    """Response schema for syslog settings (CA cert replaced by a bool flag)."""
    enabled: bool
    host: str
    port: int
    protocol: str
    facility: int
    app_name: str
    forward_reads: bool
    min_status: int
    tls_ca_cert_configured: bool = False
    tls_verify: bool
    last_error: Optional[str]
    last_sent_at: Optional[datetime]
    updated_at: datetime


class CertificateInfo(BaseModel):
    """Schema for SSL certificate information."""
    issuer: str
    subject: str
    valid_from: datetime
    valid_to: datetime
    days_remaining: int
    is_self_signed: bool


class NetworkSettingsResponse(BaseModel):
    """Schema for network settings response."""
    management_port: int
    ssl_enabled: bool
    certificate: Optional[CertificateInfo]


class PortChangeRequest(BaseModel):
    """
    Schema for changing management port. INPUT ends with a DROP, so the rules
    opening the current port are cloned for the new one (clone_rule_ids, from
    the preview) or, when none names it, one rule is created (create_rule).
    old_rules: "keep" or "disable" the rules of the previous port afterwards.
    """
    port: int
    clone_rule_ids: List[str] = []
    create_rule: bool = False
    old_rules: str = "keep"

    @field_validator('old_rules')
    @classmethod
    def _old_rules(cls, v):
        if v not in ("keep", "disable"):
            raise ValueError("old_rules must be 'keep' or 'disable'")
        return v

