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
    """Lifecycle hooks for module activation/deactivation."""
    post_install: Optional[str] = None  # e.g., "hooks/post_install.py" — runs on activation
    on_disable: Optional[str] = None    # e.g., "hooks/on_disable.py" — runs on deactivation


class ModuleConfigExport(SQLModel):
    """Config export settings for a module."""
    tables: List[str] = []                    # DB tables to export (FK order)
    irrecoverable_files: List[str] = []       # Filesystem paths that can't be regenerated
    post_restore: Optional[str] = None        # Hook to regenerate config from DB


class ModuleDashboardWidget(SQLModel):
    """Dashboard widget declared by a module."""
    id: str                           # e.g. "active_clients" (prefixed with module_id at runtime)
    title: str                        # e.g. "Client VPN Attivi"
    col: int = 6                      # Bootstrap column width (6 = half, 12 = full)
    permission: Optional[str] = None  # Permission required to see this widget


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
    
    # System-level dependencies (apt, pip)
    system_dependencies: ModuleSystemDependencies = ModuleSystemDependencies()
    
    # Database migration scripts (relative paths)
    database_migrations: List[str] = []
    
    # Install lifecycle hooks
    install_hooks: ModuleInstallHooks = ModuleInstallHooks()
    
    # Frontend view entry point (relative to static/)
    frontend_entry: Optional[str] = None
    
    # Config export settings (tables, irrecoverable files, post_restore hook)
    config_export: Optional[ModuleConfigExport] = None
    
    # Dashboard widgets this module provides
    dashboard_widgets: List[ModuleDashboardWidget] = []

    # OpenAPI tag description (shown in Swagger UI under the module tag)
    openapi_tag_description: Optional[str] = None




