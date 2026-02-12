"""
MADMIN Settings Models

Database models for system configuration.
All settings tables are singleton (only id=1 used).
"""
from sqlmodel import SQLModel, Field
from pydantic import BaseModel
from sqlalchemy import Column, BigInteger
from typing import Optional
from datetime import datetime


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
    smtp_password: Optional[str] = Field(default=None, max_length=255)
    sender_email: str = Field(default="noreply@localhost", max_length=255)
    sender_name: str = Field(default="MADMIN", max_length=100)
    public_url: Optional[str] = Field(default=None, max_length=255)
    
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
    remote_protocol: str = Field(default="sftp", max_length=10)  # ftp, sftp
    remote_host: str = Field(default="", max_length=255)
    remote_port: int = Field(default=22)
    remote_user: str = Field(default="", max_length=100)
    remote_password: str = Field(default="", max_length=255)
    remote_path: str = Field(default="/", max_length=255)
    
    last_run_status: Optional[str] = Field(default=None, max_length=50)
    last_run_time: Optional[datetime] = Field(default=None)
    
    # Retention policy
    retention_days: int = Field(default=30)  # 0 = keep forever
    
    updated_at: datetime = Field(default_factory=datetime.utcnow)


# --- Pydantic Schemas ---

class SystemSettingsUpdate(SQLModel):
    """Schema for updating system settings."""
    company_name: Optional[str] = None
    primary_color: Optional[str] = None
    logo_url: Optional[str] = None
    favicon_url: Optional[str] = None
    support_url: Optional[str] = None


class SystemSettingsResponse(SQLModel):
    """Response schema for system settings."""
    company_name: str
    primary_color: str
    logo_url: Optional[str]
    favicon_url: Optional[str]
    support_url: Optional[str]
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
    public_url: Optional[str] = None


class SMTPSettingsResponse(SQLModel):
    """Response schema for SMTP settings (excludes password)."""
    smtp_host: str
    smtp_port: int
    smtp_encryption: str
    smtp_username: Optional[str]
    sender_email: str
    sender_name: str
    public_url: Optional[str]
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
    last_run_status: Optional[str]
    last_run_time: Optional[datetime]
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
    """Schema for changing management port."""
    port: int

