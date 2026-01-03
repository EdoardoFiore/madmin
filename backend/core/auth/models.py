"""
MADMIN Authentication Models

Defines User, Permission, and UserPermission tables for granular access control.
Superusers bypass all permission checks. Regular users need explicit permissions.
"""
from sqlmodel import SQLModel, Field, Relationship
from typing import Optional, List, TYPE_CHECKING
from datetime import datetime
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
    
    # Metadata
    created_at: datetime = Field(default_factory=datetime.utcnow)
    last_login: Optional[datetime] = Field(default=None)
    
    # Relationships
    permissions: List[Permission] = Relationship(back_populates="users", link_model=UserPermission)
    
    def has_permission(self, permission_slug: str) -> bool:
        """Check if user has a specific permission."""
        if self.is_superuser:
            return True
        return any(p.slug == permission_slug for p in self.permissions)
    
    def has_any_permission(self, permission_slugs: List[str]) -> bool:
        """Check if user has any of the given permissions."""
        if self.is_superuser:
            return True
        user_slugs = {p.slug for p in self.permissions}
        return bool(user_slugs.intersection(permission_slugs))


# --- Pydantic Schemas for API ---

class UserCreate(SQLModel):
    """Schema for creating a new user."""
    username: str = Field(min_length=3, max_length=50)
    password: str = Field(min_length=6)
    email: Optional[str] = None
    is_superuser: bool = False


class UserUpdate(SQLModel):
    """Schema for updating a user."""
    password: Optional[str] = Field(default=None, min_length=6)
    email: Optional[str] = None
    is_active: Optional[bool] = None
    is_superuser: Optional[bool] = None


class UserResponse(SQLModel):
    """Schema for user API responses (excludes password)."""
    id: uuid.UUID
    username: str
    email: Optional[str]
    is_active: bool
    is_superuser: bool
    created_at: datetime
    last_login: Optional[datetime]
    permissions: List[str] = []  # List of permission slugs


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


# Core permission definitions
CORE_PERMISSIONS = [
    {"slug": "users.view", "description": "View user list"},
    {"slug": "users.manage", "description": "Create, edit, delete users"},
    {"slug": "permissions.manage", "description": "Assign permissions to users"},
    {"slug": "firewall.view", "description": "View firewall rules"},
    {"slug": "firewall.manage", "description": "Create, edit, delete firewall rules"},
    {"slug": "settings.view", "description": "View system settings"},
    {"slug": "settings.manage", "description": "Modify system settings"},
    {"slug": "modules.view", "description": "View installed modules"},
    {"slug": "modules.manage", "description": "Install, remove, configure modules"},
    {"slug": "backup.create", "description": "Create system backups"},
    {"slug": "backup.restore", "description": "Restore system from backup"},
]
