"""
MADMIN Module Models

Database models and schemas for installed modules.
"""
from sqlmodel import SQLModel, Field, Relationship
from typing import Optional, List, Dict
from datetime import datetime
import uuid


class InstalledModule(SQLModel, table=True):
    """
    Tracks installed modules and their metadata.
    """
    __tablename__ = "installed_module"
    
    id: str = Field(primary_key=True, max_length=50)  # e.g., "wireguard"
    name: str = Field(max_length=100)  # Human-readable name
    version: str = Field(max_length=20)
    description: Optional[str] = Field(default=None, max_length=500)
    author: Optional[str] = Field(default=None, max_length=100)
    
    # Installation info
    installed_at: datetime = Field(default_factory=datetime.utcnow)
    enabled: bool = Field(default=True)
    
    # Path to module directory
    install_path: str = Field(max_length=255)
    
    # Cached manifest (JSON string)
    manifest_json: Optional[str] = Field(default=None)


# --- Pydantic Schemas ---

class ModulePermission(SQLModel):
    """Permission defined by a module."""
    slug: str
    description: str


class ModuleMenuItem(SQLModel):
    """Menu item defined by a module."""
    label: str
    icon: Optional[str] = None
    route: str  # e.g., "#wireguard"


class ModuleFirewallChain(SQLModel):
    """Firewall chain definition from a module."""
    name: str  # e.g., "MOD_WG_FORWARD"
    parent: str  # INPUT, OUTPUT, FORWARD, or MADMIN_ chains
    table: str = "filter"  # filter, nat, mangle
    priority: int = 50


class ModuleSystemDependencies(SQLModel):
    """System package dependencies for a module."""
    apt: List[str] = []  # e.g., ["wireguard", "wireguard-tools"]
    pip: List[str] = []  # Additional Python packages


class ModuleInstallHooks(SQLModel):
    """Lifecycle hooks for module installation."""
    pre_install: Optional[str] = None   # e.g., "hooks/pre_install.py"
    post_install: Optional[str] = None  # e.g., "hooks/post_install.py"
    pre_uninstall: Optional[str] = None # e.g., "hooks/pre_uninstall.py"
    post_uninstall: Optional[str] = None # e.g., "hooks/post_uninstall.py"
    pre_update: Optional[str] = None    # e.g., "hooks/pre_update.py"
    post_update: Optional[str] = None   # e.g., "hooks/post_update.py"


class ModuleBackupConfig(SQLModel):
    """Backup configuration for a module."""
    external_paths: List[str] = []  # Paths outside /opt/madmin to backup (e.g., /etc/wireguard)
    restore_hooks: Optional[Dict[str, str]] = None  # e.g., {"post_restore": "hooks/post_restore.py"}


class ModuleManifest(SQLModel):
    """
    Module manifest schema (manifest.json).
    Defines module metadata, permissions, routes, and integrations.
    """
    id: str
    name: str
    version: str
    description: Optional[str] = None
    author: Optional[str] = None
    
    # Permissions this module provides
    permissions: List[ModulePermission] = []
    
    # Menu items to add to sidebar
    menu: List[ModuleMenuItem] = []
    
    # Firewall chains to create
    firewall_chains: List[ModuleFirewallChain] = []
    
    # Dependencies (other module IDs)
    dependencies: List[str] = []
    
    # Entry point for backend router (relative to module dir)
    backend_router: str = "router.py"
    
    # Static files directory (relative to module dir)
    static_dir: str = "static"
    
    # NEW: System-level dependencies (apt, pip)
    system_dependencies: ModuleSystemDependencies = ModuleSystemDependencies()
    
    # NEW: Database migration scripts (relative paths)
    database_migrations: List[str] = []  # e.g., ["migrations/001_initial.py"]
    
    # NEW: Install lifecycle hooks
    install_hooks: ModuleInstallHooks = ModuleInstallHooks()
    
    # NEW: Frontend view entry point (relative to static/)
    frontend_entry: Optional[str] = None  # e.g., "views/main.js"
    
    # NEW: Backup configuration for module-specific data
    backup: Optional[ModuleBackupConfig] = None


class InstalledModuleResponse(SQLModel):
    """Response schema for installed module."""
    id: str
    name: str
    version: str
    description: Optional[str]
    author: Optional[str]
    installed_at: datetime
    enabled: bool


class ModuleInstallRequest(SQLModel):
    """Request to install a module from URL or staging."""
    source: str  # "staging" or URL
    module_id: Optional[str] = None  # Required if source is "staging"
