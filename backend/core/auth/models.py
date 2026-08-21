"""
MADMIN Authentication Models

Defines User, Permission, and UserPermission tables for granular access control.
Superusers bypass all permission checks. Regular users need explicit permissions.
"""
from sqlmodel import SQLModel, Field, Relationship
from pydantic import field_validator
from typing import Optional, List, Set, TYPE_CHECKING
from datetime import datetime
import re
import uuid

if TYPE_CHECKING:
    from core.modules.models import InstalledModule


class UserPermission(SQLModel, table=True):
    """
    Junction table linking Users to Permissions.
    Enables many-to-many relationship for granular access control.
    """
    __tablename__ = "user_permission"

    user_id: uuid.UUID = Field(foreign_key="user.id", primary_key=True)
    permission_slug: str = Field(foreign_key="permission.slug", primary_key=True)


class Permission(SQLModel, table=True):
    """
    Permission definition.

    Permissions are identified by a slug (e.g., "users.manage", "firewall.edit").
    Core permissions have module_id=None. Module permissions reference their module.
    """
    __tablename__ = "permission"

    slug: str = Field(primary_key=True, max_length=100)
    description: str = Field(max_length=255)
    module_id: Optional[str] = Field(default=None, foreign_key="installed_module.id", index=True)

    # Relationships
    users: List["User"] = Relationship(back_populates="permissions", link_model=UserPermission)


class User(SQLModel, table=True):
    """
    System user with authentication and authorization data.

    Superusers have all permissions implicitly.
    Regular users must have permissions explicitly assigned.
    """
    __tablename__ = "user"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    username: str = Field(unique=True, index=True, max_length=50)
    email: Optional[str] = Field(default=None, max_length=255)
    hashed_password: str = Field(max_length=255)

    # Status
    is_active: bool = Field(default=True)
    is_superuser: bool = Field(default=False)
    is_protected: bool = Field(default=False)  # First setup user — cannot be modified or deleted by others

    # 2FA Fields
    totp_secret: Optional[str] = Field(default=None, max_length=512)  # encrypted, longer than plain
    totp_enabled: bool = Field(default=False)
    totp_enforced: bool = Field(default=False)  # 2FA required by admin
    totp_locked: bool = Field(default=False)    # Locked after too many failed 2FA attempts
    backup_codes: Optional[str] = Field(default=None)  # JSON array of hashed backup codes

    # Password lifecycle
    must_change_password: bool = Field(default=False)  # Force change at next login
    password_changed_at: Optional[datetime] = Field(default=None)
    password_expires_at: Optional[datetime] = Field(default=None)  # None = no expiry

    # Metadata
    created_at: datetime = Field(default_factory=datetime.utcnow)
    last_login: Optional[datetime] = Field(default=None)

    # Preferences (JSON string)
    preferences: str = Field(default="{}")

    # Relationships
    permissions: List[Permission] = Relationship(back_populates="users", link_model=UserPermission)

    def has_permission(self, permission_slug: str) -> bool:
        """Check if user has a specific permission."""
        if self.is_superuser:
            return True
        return permission_slug in self.effective_permission_slugs()

    def has_any_permission(self, permission_slugs: List[str]) -> bool:
        """Check if user has any of the given permissions."""
        if self.is_superuser:
            return True
        return bool(self.effective_permission_slugs().intersection(permission_slugs))

    def has_all_permissions(self, permission_slugs: List[str]) -> bool:
        """Check if user has every one of the given permissions."""
        if self.is_superuser:
            return True
        return self.effective_permission_slugs().issuperset(permission_slugs)

    def permission_slugs(self) -> Set[str]:
        """
        Slugs explicitly granted to this user (empty for superusers, who bypass
        checks). This is what the permission editor reads and writes — the
        implied ones must not leak into it, or saving would persist them.
        """
        return {p.slug for p in self.permissions}

    def effective_permission_slugs(self) -> Set[str]:
        """
        Granted slugs plus the ones they imply.

        Managing an area necessarily means seeing it, so `<area>.manage` implies
        `<area>.view`. Without this, granting only `settings.manage` hid the very
        page it was meant to unlock.
        """
        granted = self.permission_slugs()
        implied = {
            f"{slug.rsplit('.', 1)[0]}.view"
            for slug in granted if slug.endswith('.manage')
        }
        return granted | implied


class RevokedToken(SQLModel, table=True):
    """
    Persistent store for revoked user tokens.
    Survives application restarts, ensuring disabled users cannot re-authenticate.
    No FK to User — records persist even after user deletion.
    """
    __tablename__ = "revoked_token"

    user_id: uuid.UUID = Field(primary_key=True)
    revoked_at: datetime = Field(default_factory=datetime.utcnow)
    expires_at: datetime


class LoginAttempt(SQLModel, table=True):
    """
    Persistent rate limiting state per client IP.
    Survives application restarts, preventing brute-force reset via restart.
    """
    __tablename__ = "login_attempt"

    ip: str = Field(primary_key=True, max_length=45)  # max IPv6 length
    attempts: int = Field(default=0)
    block_count: int = Field(default=0)
    blocked_until: Optional[datetime] = Field(default=None)
    last_attempt: datetime = Field(default_factory=datetime.utcnow)


# --- Pydantic Schemas for API ---

class UserCreate(SQLModel):
    """Schema for creating a new user."""
    username: str = Field(min_length=3, max_length=50)

    @field_validator("username")
    @classmethod
    def _validate_username_charset(cls, v: str) -> str:
        # Defense in depth: charset is also enforced in the auth service layer.
        # Restricts username to chars safe in HTML text/attribute contexts.
        if not re.match(r'^[a-zA-Z0-9._-]+$', v or ""):
            raise ValueError("Username non valido: usa solo lettere, numeri, '.', '_' o '-'")
        return v
    password: str  # strength validated in service layer
    email: Optional[str] = None
    is_superuser: bool = False


class UserUpdate(SQLModel):
    """Schema for updating a user."""
    password: Optional[str] = None  # strength validated in service layer
    email: Optional[str] = None
    is_active: Optional[bool] = None
    is_superuser: Optional[bool] = None
    totp_enforced: Optional[bool] = None  # Force 2FA on user
    must_change_password: Optional[bool] = None  # Force password change at next login
    password_expires_at: Optional[datetime] = None  # Manual per-user expiry override


class UserPreferencesUpdate(SQLModel):
    """Schema for updating user preferences."""
    preferences: str


class UserProfileUpdate(SQLModel):
    """Schema for the current user editing their own profile (self-service)."""
    email: Optional[str] = Field(default=None, max_length=255)


class UserResponse(SQLModel):
    """Schema for user API responses (excludes password)."""
    id: uuid.UUID
    username: str
    email: Optional[str]
    is_active: bool
    is_superuser: bool
    is_protected: bool = False
    totp_enabled: bool = False
    totp_enforced: bool = False
    totp_locked: bool = False
    must_change_password: bool = False
    password_expires_at: Optional[datetime] = None
    created_at: datetime
    last_login: Optional[datetime]
    permissions: List[str] = []  # List of permission slugs
    preferences: str = "{}"


class PermissionResponse(SQLModel):
    """Schema for permission API responses."""
    slug: str
    description: str
    module_id: Optional[str]


class Token(SQLModel):
    """JWT token response."""
    access_token: str
    token_type: str = "bearer"


class TokenData(SQLModel):
    """Data extracted from JWT token."""
    username: Optional[str] = None
    user_id: Optional[uuid.UUID] = None


# Core permission definitions.
#
# One slug per subsystem, so an operator can be given exactly one area without
# handing over the machine. Deliberately absent: a "cron.manage" slug — writing
# the root crontab schedules arbitrary commands as root, so it is superuser-only
# and cannot be delegated (see core/cron/router.py).
CORE_PERMISSIONS = [
    {"slug": "users.view", "description": "View user list"},
    {"slug": "users.manage", "description": "Create, edit, delete users"},
    {"slug": "permissions.manage", "description": "Assign permissions to users (requires users.manage)"},
    {"slug": "firewall.view", "description": "View firewall rules"},
    {"slug": "firewall.manage", "description": "Create, edit, delete firewall rules"},
    {"slug": "network.view", "description": "View network interfaces"},
    {"slug": "network.manage", "description": "Configure network interfaces"},
    {"slug": "settings.view", "description": "View branding, management port and SSL settings"},
    {"slug": "settings.manage", "description": "Modify branding, management port and SSL settings"},
    {"slug": "smtp.view", "description": "View SMTP configuration"},
    {"slug": "smtp.manage", "description": "Modify SMTP configuration and send test emails"},
    {"slug": "backup.view", "description": "View backup settings, history and archives"},
    {"slug": "backup.manage", "description": "Configure backups, export, download and delete archives"},
    {"slug": "backup.restore", "description": "Import/restore a configuration archive — includes user accounts and password hashes, so it grants effective superuser access"},
    {"slug": "cron.view", "description": "View scheduled jobs and available scripts"},
    {"slug": "services.manage", "description": "Start, stop and restart system services"},
    {"slug": "modules.view", "description": "View installed modules"},
    {"slug": "modules.manage", "description": "Install, remove, configure modules"},
    {"slug": "logs.view", "description": "View audit logs and system logs"},
]
