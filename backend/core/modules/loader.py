"""
MADMIN Module Loader

Handles discovery, loading, and initialization of installed modules.
"""
import os
import json
import logging
import importlib.util
import shutil
import subprocess
import asyncio
from pathlib import Path
from typing import List, Optional, Dict, Any
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from fastapi import FastAPI, APIRouter
from fastapi.staticfiles import StaticFiles

from config import get_settings
from .models import InstalledModule, ModuleManifest, ModulePermission, ModuleSystemDependencies, ModuleInstallHooks

logger = logging.getLogger(__name__)
settings = get_settings()


class ModuleLoader:
    """
    Discovers and loads installed modules.
    
    Modules are loaded from the modules directory and can provide:
    - FastAPI router for backend endpoints
    - Static files for frontend
    - Permissions for access control
    - Firewall chain definitions
    """
    
    def __init__(self):
        self.loaded_modules: Dict[str, Dict[str, Any]] = {}
        self.modules_dir = Path(settings.modules_dir)
        self.staging_dir = Path(settings.staging_dir)
    
    def _parse_manifest(self, manifest_path: Path) -> Optional[ModuleManifest]:
        """Parse and validate a module's manifest.json."""
        try:
            with open(manifest_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return ModuleManifest(**data)
        except FileNotFoundError:
            logger.error(f"Manifest not found: {manifest_path}")
            return None
        except json.JSONDecodeError as e:
            logger.error(f"Invalid JSON in manifest {manifest_path}: {e}")
            return None
        except Exception as e:
            logger.error(f"Failed to parse manifest {manifest_path}: {e}")
            return None
    
    def discover_modules(self) -> List[str]:
        """
        Discover all installed modules by scanning the modules directory.
        Returns list of module IDs.
        """
        modules = []
        
        if not self.modules_dir.exists():
            logger.warning(f"Modules directory does not exist: {self.modules_dir}")
            return modules
        
        for item in self.modules_dir.iterdir():
            if item.is_dir():
                manifest_path = item / "manifest.json"
                if manifest_path.exists():
                    modules.append(item.name)
        
        return modules
    
    def load_module_router(self, module_id: str, manifest: ModuleManifest) -> Optional[APIRouter]:
        """
        Load a module's FastAPI router.
        
        Args:
            module_id: Module identifier
            manifest: Parsed module manifest
        
        Returns:
            FastAPI APIRouter or None if loading fails
        """
        module_path = self.modules_dir / module_id
        router_file = module_path / manifest.backend_router
        
        if not router_file.exists():
            logger.warning(f"Router file not found for module {module_id}: {router_file}")
            return None
        
        try:
            # Dynamic import of module router
            spec = importlib.util.spec_from_file_location(
                f"modules.{module_id}.router",
                router_file
            )
            if spec is None or spec.loader is None:
                return None
            
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            
            if hasattr(module, "router"):
                return module.router
            else:
                logger.warning(f"Module {module_id} router.py has no 'router' attribute")
                return None
                
        except Exception as e:
            logger.error(f"Failed to load router for module {module_id}: {e}")
            return None
    
    async def register_module_permissions(
        self,
        session: AsyncSession,
        module_id: str,
        permissions: List[ModulePermission]
    ) -> None:
        """Register a module's permissions in the database."""
        from core.auth.models import Permission
        
        for perm in permissions:
            result = await session.execute(
                select(Permission).where(Permission.slug == perm.slug)
            )
            existing = result.scalar_one_or_none()
            
            if not existing:
                permission = Permission(
                    slug=perm.slug,
                    description=perm.description,
                    module_id=module_id
                )
                session.add(permission)
                logger.info(f"Registered permission {perm.slug} for module {module_id}")
    
    async def register_module_chains(
        self,
        session: AsyncSession,
        module_id: str,
        manifest: ModuleManifest
    ) -> None:
        """Register a module's firewall chains."""
        from core.firewall.orchestrator import firewall_orchestrator
        
        for chain_def in manifest.firewall_chains:
            await firewall_orchestrator.register_module_chain(
                session=session,
                module_id=module_id,
                chain_name=chain_def.name,
                parent_chain=chain_def.parent,
                priority=chain_def.priority,
                table_name=chain_def.table
            )
    
    async def install_system_dependencies(
        self,
        manifest: ModuleManifest,
        module_path: Path
    ) -> bool:
        """
        Install system-level dependencies (apt packages, pip packages).
        Requires appropriate system permissions for apt operations.
        
        Returns True if all dependencies installed successfully.
        """
        deps = manifest.system_dependencies
        
        # Install apt packages
        if deps.apt:
            logger.info(f"Installing apt packages: {deps.apt}")
            try:
                # Check if packages are already installed
                for pkg in deps.apt:
                    check = subprocess.run(
                        ["dpkg-query", "-W", "-f=${Status}", pkg],
                        capture_output=True, text=True
                    )
                    is_installed = (
                        check.returncode == 0
                        and "install ok installed" in check.stdout
                    )
                    if not is_installed:
                        # Package not installed, install it
                        result = subprocess.run(
                            ["apt-get", "install", "-y", pkg],
                            capture_output=True,
                            text=True
                        )
                        if result.returncode != 0:
                            logger.error(f"Failed to install apt package {pkg}: {result.stderr}")
                            return False
                        logger.info(f"Installed apt package: {pkg}")
                    else:
                        logger.info(f"Apt package already installed: {pkg}")
            except Exception as e:
                logger.error(f"Error installing apt packages: {e}")
                return False
        
        # Install pip packages
        if deps.pip:
            logger.info(f"Installing pip packages: {deps.pip}")
            try:
                from config import get_settings
                venv_pip = Path(get_settings().data_dir).parent / "venv" / "bin" / "pip"
                pip_cmd = str(venv_pip) if venv_pip.exists() else "pip"
                
                for pkg in deps.pip:
                    result = subprocess.run(
                        [pip_cmd, "install", pkg],
                        capture_output=True,
                        text=True
                    )
                    if result.returncode != 0:
                        logger.error(f"Failed to install pip package {pkg}: {result.stderr}")
                        return False
                    logger.info(f"Installed pip package: {pkg}")
            except Exception as e:
                logger.error(f"Error installing pip packages: {e}")
                return False
        
        return True
    
    async def uninstall_system_dependencies(
        self,
        manifest: ModuleManifest,
        session: AsyncSession
    ) -> bool:
        """
        Uninstall system-level dependencies (apt packages, pip packages).
        Only removes packages if no other installed module needs them.
        
        Returns True if all dependencies uninstalled successfully.
        """
        deps = manifest.system_dependencies
        
        # Get all other installed modules' manifests to check shared deps
        from .models import InstalledModule
        result = await session.execute(
            select(InstalledModule).where(InstalledModule.id != manifest.id)
        )
        other_modules = result.scalars().all()
        
        # Collect all apt/pip packages used by OTHER modules
        other_apt = set()
        other_pip = set()
        for mod in other_modules:
            if mod.manifest_json:
                try:
                    other_manifest = json.loads(mod.manifest_json)
                    sys_deps = other_manifest.get("system_dependencies", {})
                    other_apt.update(sys_deps.get("apt", []))
                    other_pip.update(pkg.split(">=")[0].split("==")[0] for pkg in sys_deps.get("pip", []))
                except:
                    pass
        
        # Uninstall pip packages (only if not used by others)
        if deps.pip:
            logger.info(f"Checking pip packages for removal: {deps.pip}")
            
            # Core pip packages that should NEVER be uninstalled (used by MADMIN core)
            protected_pip = {
                'fastapi', 'uvicorn', 'sqlmodel', 'sqlalchemy', 'asyncpg', 'pydantic',
                'passlib', 'python-jose', 'bcrypt', 'httpx', 'aiofiles',
                'pyotp', 'qrcode', 'pillow',  # 2FA core packages
            }
            
            try:
                from config import get_settings
                venv_pip = Path(get_settings().data_dir).parent / "venv" / "bin" / "pip"
                pip_cmd = str(venv_pip) if venv_pip.exists() else "pip"
                
                for pkg in deps.pip:
                    pkg_name = pkg.split(">=")[0].split("==")[0]
                    
                    if pkg_name in protected_pip:
                        logger.warning(f"Refusing to uninstall protected pip package: {pkg_name}")
                        continue
                    
                    if pkg_name not in other_pip:
                        result = subprocess.run(
                            [pip_cmd, "uninstall", "-y", pkg_name],
                            capture_output=True,
                            text=True
                        )
                        if result.returncode == 0:
                            logger.info(f"Uninstalled pip package: {pkg_name}")
                        else:
                            logger.warning(f"Failed to uninstall pip package {pkg_name}: {result.stderr}")
                    else:
                        logger.info(f"Keeping pip package {pkg_name} (used by other modules)")
            except Exception as e:
                logger.error(f"Error uninstalling pip packages: {e}")
        
        
        # Uninstall apt packages (only if not used by others)
        if deps.apt:
            logger.info(f"Checking apt packages for removal: {deps.apt}")
            
            # Critical system packages that should NEVER be uninstalled
            protected_packages = {
                'openssl', 'ca-certificates', 'sudo', 'systemd', 'bash', 'ssh', 'apt', 'dpkg',
                'python3', 'python3-pip', 'python3-venv',
                'postgresql', 'postgresql-client', 'postgresql-common'
            }
            
            try:
                for pkg in deps.apt:
                    # Check if protected (exact match or startswith for mostly safe check)
                    is_protected = pkg in protected_packages or any(pkg.startswith(p + '-') for p in protected_packages)
                    
                    if is_protected:
                        logger.warning(f"Refusing to uninstall protected system package: {pkg}")
                        continue
                        
                    if pkg not in other_apt:
                        result = subprocess.run(
                            ["apt-get", "purge", "-y", pkg],
                            capture_output=True,
                            text=True
                        )
                        if result.returncode == 0:
                            logger.info(f"Uninstalled apt package: {pkg}")
                        else:
                            logger.warning(f"Failed to uninstall apt package {pkg}: {result.stderr}")
                    else:
                        logger.info(f"Keeping apt package {pkg} (used by other modules)")
            except Exception as e:
                logger.error(f"Error uninstalling apt packages: {e}")
        
        return True
    
    async def run_database_migrations(
        self,
        manifest: ModuleManifest,
        module_path: Path,
        session: AsyncSession
    ) -> bool:
        """
        Execute database migration scripts for a module.
        Migration files are Python scripts with an 'upgrade(session)' function.
        
        Returns True if all migrations ran successfully.
        """
        if not manifest.database_migrations:
            return True
        
        for migration_file in manifest.database_migrations:
            migration_path = module_path / migration_file
            
            if not migration_path.exists():
                logger.warning(f"Migration file not found: {migration_path}")
                continue
            
            try:
                # Dynamic import of migration module
                spec = importlib.util.spec_from_file_location(
                    f"migration_{migration_path.stem}",
                    migration_path
                )
                if spec is None or spec.loader is None:
                    logger.error(f"Failed to load migration spec: {migration_path}")
                    return False
                
                migration_module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(migration_module)
                
                # Execute upgrade function
                if hasattr(migration_module, "upgrade"):
                    await migration_module.upgrade(session)
                    logger.info(f"Executed migration: {migration_file}")
                else:
                    logger.warning(f"Migration {migration_file} has no 'upgrade' function")
                    
            except Exception as e:
                logger.error(f"Migration {migration_file} failed: {e}")
                return False
        
        return True
    
    async def execute_hook(
        self,
        hook_path: Optional[str],
        module_path: Path,
        hook_name: str
    ) -> bool:
        """
        Execute a module lifecycle hook script.
        Hook files are Python scripts with a 'run()' async function.
        
        Returns True if hook executed successfully (or no hook defined).
        """
        if not hook_path:
            return True
        
        full_path = module_path / hook_path
        
        if not full_path.exists():
            logger.warning(f"Hook file not found: {full_path}")
            return True  # Not a failure, just missing optional hook
        
        try:
            spec = importlib.util.spec_from_file_location(
                f"hook_{hook_name}",
                full_path
            )
            if spec is None or spec.loader is None:
                logger.error(f"Failed to load hook spec: {full_path}")
                return False
            
            hook_module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(hook_module)
            
            if hasattr(hook_module, "run"):
                result = hook_module.run()
                # Support both sync and async run functions
                if asyncio.iscoroutine(result):
                    await result
                logger.info(f"Executed {hook_name} hook for module")
                return True
            else:
                logger.warning(f"Hook {hook_path} has no 'run' function")
                return True
                
        except Exception as e:
            logger.error(f"Hook {hook_name} failed: {e}")
            return False
    
    async def load_module(
        self,
        app: FastAPI,
        session: AsyncSession,
        module_id: str
    ) -> bool:
        """
        Load a single module and register its components.
        
        Args:
            app: FastAPI application instance
            session: Database session
            module_id: Module identifier
        
        Returns:
            True if loaded successfully
        """
        module_path = self.modules_dir / module_id
        manifest_path = module_path / "manifest.json"
        
        manifest = self._parse_manifest(manifest_path)
        if not manifest:
            return False
        
        # Load router
        router = self.load_module_router(module_id, manifest)
        if router:
            # Mount router under /api/modules/{module_id}/
            app.include_router(
                router,
                prefix=f"/api/modules/{module_id}",
                tags=[manifest.name]
            )
            logger.info(f"Mounted router for module {module_id}")
        
        # Mount static files
        static_path = module_path / manifest.static_dir
        if static_path.exists():
            app.mount(
                f"/static/modules/{module_id}",
                StaticFiles(directory=str(static_path)),
                name=f"static_{module_id}"
            )
            logger.info(f"Mounted static files for module {module_id}")
        
        # Register permissions
        await self.register_module_permissions(session, module_id, manifest.permissions)
        
        # Register firewall chains
        await self.register_module_chains(session, module_id, manifest)
        
        # Store in loaded modules
        self.loaded_modules[module_id] = {
            "manifest": manifest,
            "router": router,
            "path": str(module_path)
        }
        
        logger.info(f"Successfully loaded module: {module_id} v{manifest.version}")
        return True
    
    async def load_all_modules(self, app: FastAPI, session: AsyncSession) -> int:
        """
        Discover and load all installed modules.
        
        Returns:
            Number of modules loaded
        """
        module_ids = self.discover_modules()
        loaded_count = 0
        
        for module_id in module_ids:
            # Check if module is enabled in DB
            result = await session.execute(
                select(InstalledModule).where(InstalledModule.id == module_id)
            )
            db_module = result.scalar_one_or_none()
            
            if db_module and not db_module.enabled:
                logger.info(f"Skipping disabled module: {module_id}")
                continue
            
            if await self.load_module(app, session, module_id):
                loaded_count += 1
        
        logger.info(f"Loaded {loaded_count}/{len(module_ids)} modules")
        return loaded_count
    
    def get_menu_items(self) -> List[Dict]:
        """
        Get all menu items from loaded modules.
        Used by frontend to build dynamic sidebar.
        """
        items = []
        for module_id, data in self.loaded_modules.items():
            manifest: ModuleManifest = data["manifest"]
            for menu_item in manifest.menu:
                items.append({
                    "module_id": module_id,
                    "label": menu_item.label,
                    "icon": menu_item.icon,
                    "route": menu_item.route
                })
        return items
    
    async def install_from_staging(
        self,
        session: AsyncSession,
        module_id: str
    ) -> Optional[InstalledModule]:
        """
        Install a module from the staging directory.
        
        Full installation lifecycle:
        1. Parse manifest and validate
        2. Execute pre-install hook
        3. Install system dependencies (apt/pip)
        4. Copy module to modules directory
        5. Run database migrations
        6. Execute post-install hook
        7. Create database record
        
        Args:
            session: Database session
            module_id: Module identifier in staging
        
        Returns:
            InstalledModule record or None on failure
        """
        staging_path = self.staging_dir / module_id
        manifest_path = staging_path / "manifest.json"
        
        if not staging_path.exists():
            logger.error(f"Module {module_id} not found in staging")
            return None
        
        manifest = self._parse_manifest(manifest_path)
        if not manifest:
            return None
        
        # Check if already installed
        result = await session.execute(
            select(InstalledModule).where(InstalledModule.id == module_id)
        )
        if result.scalar_one_or_none():
            logger.error(f"Module {module_id} is already installed")
            return None
        
        target_path = self.modules_dir / module_id
        
        # 1. Execute pre-install hook (from staging)
        if manifest.install_hooks.pre_install:
            if not await self.execute_hook(
                manifest.install_hooks.pre_install,
                staging_path,
                "pre_install"
            ):
                logger.error(f"Pre-install hook failed for {module_id}")
                return None
        
        # 2. Install system dependencies
        if not await self.install_system_dependencies(manifest, staging_path):
            logger.error(f"Failed to install system dependencies for {module_id}")
            return None
        
        # 3. Copy to modules directory
        try:
            shutil.copytree(staging_path, target_path)
        except Exception as e:
            logger.error(f"Failed to copy module {module_id}: {e}")
            return None
        
        # 4. Run database migrations
        if not await self.run_database_migrations(manifest, target_path, session):
            logger.error(f"Database migrations failed for {module_id}")
            # Rollback: remove copied files
            shutil.rmtree(target_path, ignore_errors=True)
            return None
        
        # 5. Execute post-install hook (from installed location)
        if manifest.install_hooks.post_install:
            if not await self.execute_hook(
                manifest.install_hooks.post_install,
                target_path,
                "post_install"
            ):
                logger.warning(f"Post-install hook failed for {module_id}, continuing...")
        
        # 6. Create database record
        installed = InstalledModule(
            id=manifest.id,
            name=manifest.name,
            version=manifest.version,
            description=manifest.description,
            author=manifest.author,
            install_path=str(target_path),
            manifest_json=json.dumps(manifest.model_dump())
        )
        session.add(installed)
        
        logger.info(f"Successfully installed module {module_id} from staging")
        return installed
    
    async def _cleanup_module_tables(self, module_path: Path):
        """
        Dynamically import models.py and drop all SQLModel tables defined there.
        """
        models_path = module_path / "models.py"
        if not models_path.exists():
            return
            
        import importlib.util
        import inspect
        from sqlmodel import SQLModel, text
        from core.database import engine
        
        try:
            # Create a fresh metadata instance to avoid "Table already defined" errors
            # when re-importing models that might be already loaded in the main app
            # However, SQLModel uses a global MetaData by default.
            # To fix this, we need to temporarily clear/reset or handle the import carefully.
            # A better approach for cleanup is to parse the file for classes without full registration
            # OR just accept that we might get redefinition errors and extract table names anyway.
            # But the error prevents the module from loading, so we can't inspect it.
            
            # Alternative: Read the file content and extract table names with regex? 
            # No, too brittle.
            
            # Solution: We can try to remove the module from sys.modules if it exists,
            # and crucially, we need to handle the SQLAlchemy MetaData issue.
            # Since we only want to FIND the table names, we can try to use a separate scope.
            
            # Let's try clearing the registry for this specific import context if possible.
            # Given the limitation, we'll use a robust import that catches the error but
            # tries to proceed if the module was partially loaded, OR we iterate over
            # the already loaded classes if we can identify them.
            
            # Actually, the error happens at class definition time.
            # If we know the module name (e.g., 'modules.wireguard.models'), we can check sys.modules.
            
            # Helper to clear SQLModel/SQLAlchemy metadata for these specific tables? Hard.
            
            # Let's use the 'extend_existing' hack by patching SQLModel/SQLAlchemy? Too risky.
            
            # Robust Strategy:
            # 1. Try to import. If it fails with ArgumentError, it means tables are already known.
            # 2. In that case, we can try to find them in SQLModel.metadata.tables directly
            #    by filtering for tables that look like they belong to this module?
            #    But table names don't strictly contain module info.
            
            # Revised Strategy:
            # Manually clean up SQLModel metadata before import.
             
            # Remove any existing table definitions for this module from SQLModel.metadata
            # This is a bit aggressive but we are uninstalling anyway.
            # But we don't know the table names YET. 
            
            # Let's try to reload the module if it's already in sys.modules
            # But 'models.py' inside a module folder isn't usually in sys.modules with a clean name 
            # unless we imported it as 'backend.modules.wireguard.models'.
            
            # Let's go with a specific hack: 
            # We define a context where we temporarily replace SQLModel.metadata with a fresh one?
            # SQLModel.metadata is a property on the class. class definitions use the MetaData
            # from the base class (SQLModel).
            
            # If we clear `SQLModel.metadata.clear()`, we wipe EVERYTHING including Core tables. BAD.
            
            # Okay, simpler approach:
            # If the error is "Table already defined", it means the class is already in memory.
            # If it's in memory, we might find it in `SQLModel.__subclasses__()`.
            
            classes = SQLModel.__subclasses__()
            tables_to_drop = []
            
            # We need to filter for classes belonging to THIS module.
            # How do we know which classes belong to the module being uninstalled?
            # We can try to guess based on the module path.
            
            # Let's try to import the module with a specific name that might match 
            # how it was imported originally?
            # Usually: `backend.modules.wireguard.models`
            
            # Construct potential module name
            # module_path is absolute, e.g., /opt/madmin/backend/modules/wireguard
            # We want "modules.wireguard.models" or "backend.modules.wireguard.models"
            
            # Let's try inspecting the file content for `class X(SQLModel, table=True):`
            # and `__tablename__ = "Y"`. Regex is safer for uninstallation cleanup
            # than executing code that conflicts with running app state.
            
            import re
            content = models_path.read_text()
            
            # Find __tablename__ definitions inside SQLModel classes
            # This is a heuristic but safe from "already defined" errors.
            # Matches: __tablename__ = "wg_instance" or __tablename__='wg_instance'
            matches = re.findall(r'__tablename__\s*=\s*[\'"]([^\'"]+)[\'"]', content)
            
            if matches:
                tables_to_drop = matches
                logger.info(f"Found tables to drop via static analysis: {tables_to_drop}")
                
                async with engine.begin() as conn:
                    # Drop with CASCADE
                    for table in tables_to_drop:
                        await conn.execute(text(f"DROP TABLE IF EXISTS {table} CASCADE"))
                return

        except Exception as e:
            logger.error(f"Failed to cleanup module tables: {e}")

    async def uninstall_module(
        self,
        session: AsyncSession,
        module_id: str
    ) -> bool:
        """
        Uninstall a module.
        
        Full uninstall lifecycle:
        1. Parse stored manifest
        2. Execute pre_uninstall hook
        3. Remove firewall chains
        4. Remove permissions
        5. Remove pip packages (if not shared)
        6. Remove apt packages (if not shared)
        7. Drop module tables (NEW)
        8. Remove module files
        9. Remove database record
        10. Execute post_uninstall hook
        """
        result = await session.execute(
            select(InstalledModule).where(InstalledModule.id == module_id)
        )
        db_module = result.scalar_one_or_none()
        
        if not db_module:
            logger.error(f"Module {module_id} not found in database")
            return False
        
        module_path = Path(db_module.install_path)
        
        # Parse stored manifest
        manifest = None
        if db_module.manifest_json:
            try:
                manifest_data = json.loads(db_module.manifest_json)
                manifest = ModuleManifest(**manifest_data)
            except Exception as e:
                logger.warning(f"Failed to parse stored manifest: {e}")
        
        # 1. Execute pre_uninstall hook
        if manifest and manifest.install_hooks.pre_uninstall:
            await self.execute_hook(
                manifest.install_hooks.pre_uninstall,
                module_path,
                "pre_uninstall"
            )
        
        # 2. Remove firewall chains
        from core.firewall.models import ModuleChain
        await session.execute(
            ModuleChain.__table__.delete().where(ModuleChain.module_id == module_id)
        )
        
        # 3. Remove permissions
        from core.auth.models import Permission
        await session.execute(
            Permission.__table__.delete().where(Permission.module_id == module_id)
        )
        
        # 4. Remove system dependencies (pip/apt)
        if manifest:
            await self.uninstall_system_dependencies(manifest, session)
            
        # 5. Drop module tables (Cleanup DB)
        await self._cleanup_module_tables(module_path)
        
        # 6. Remove module files
        if module_path.exists():
            try:
                shutil.rmtree(module_path)
            except Exception as e:
                logger.error(f"Failed to remove module files: {e}")
        
        # 6. Remove database record
        await session.delete(db_module)
        
        # 7. Remove from loaded modules
        if module_id in self.loaded_modules:
            del self.loaded_modules[module_id]
        
        # 8. Execute post_uninstall hook (if we have a copy somewhere, skip for now)
        # Note: post_uninstall runs after files are deleted, so hook must be external or inline
        
        logger.info(f"Uninstalled module {module_id}")
        return True
    
    async def update_module(
        self,
        session: AsyncSession,
        module_id: str,
        new_staging_path: Path
    ) -> bool:
        """
        Update a module to a new version.
        
        Update lifecycle:
        1. Parse new manifest
        2. Get current module data
        3. Execute pre_update hook (from NEW version)
        4. Backup external_paths (from current manifest)
        5. Partial uninstall (keep permissions, chains will be re-registered)
        6. Install new version
        7. Restore external_paths
        8. Execute post_update hook
        
        Returns True if update successful.
        """
        # 1. Get current module
        result = await session.execute(
            select(InstalledModule).where(InstalledModule.id == module_id)
        )
        current_module = result.scalar_one_or_none()
        
        if not current_module:
            logger.error(f"Module {module_id} not found for update")
            return False
        
        current_path = Path(current_module.install_path)
        
        # Parse current manifest for backup paths
        current_manifest = None
        if current_module.manifest_json:
            try:
                current_manifest = ModuleManifest(**json.loads(current_module.manifest_json))
            except:
                pass
        
        # 2. Parse new manifest
        new_manifest_path = new_staging_path / "manifest.json"
        new_manifest = self._parse_manifest(new_manifest_path)
        if not new_manifest:
            logger.error("Failed to parse new manifest")
            return False
        
        # 3. Execute pre_update hook (from new version)
        if new_manifest.install_hooks.pre_update:
            if not await self.execute_hook(
                new_manifest.install_hooks.pre_update,
                new_staging_path,
                "pre_update"
            ):
                logger.warning("pre_update hook failed, continuing...")
        
        # 4. Backup external_paths
        import tempfile
        backup_dir = None
        if current_manifest and current_manifest.backup and current_manifest.backup.external_paths:
            backup_dir = Path(tempfile.mkdtemp(prefix=f"madmin_update_{module_id}_"))
            for ext_path in current_manifest.backup.external_paths:
                src = Path(ext_path)
                if src.exists():
                    dst = backup_dir / src.name
                    try:
                        if src.is_dir():
                            shutil.copytree(src, dst)
                        else:
                            shutil.copy2(src, dst)
                        logger.info(f"Backed up {ext_path} for update")
                    except Exception as e:
                        logger.warning(f"Failed to backup {ext_path}: {e}")
        
        # 5. Remove old module (but preserve DB record temporarily)
        # Remove old files
        if current_path.exists():
            shutil.rmtree(current_path)
        
        # 6. Install system dependencies from new manifest
        if not await self.install_system_dependencies(new_manifest, new_staging_path):
            logger.error("Failed to install new system dependencies")
            return False
        
        # Copy new module
        target_path = self.modules_dir / module_id
        shutil.copytree(new_staging_path, target_path)
        
        # Run new migrations
        if not await self.run_database_migrations(new_manifest, target_path, session):
            logger.error("New migrations failed")
            # Could rollback here
            return False
        
        # 7. Restore external_paths
        if backup_dir and current_manifest and current_manifest.backup:
            for ext_path in current_manifest.backup.external_paths:
                src = backup_dir / Path(ext_path).name
                if src.exists():
                    dst = Path(ext_path)
                    try:
                        if dst.exists():
                            if dst.is_dir():
                                shutil.rmtree(dst)
                            else:
                                dst.unlink()
                        if src.is_dir():
                            shutil.copytree(src, dst)
                        else:
                            shutil.copy2(src, dst)
                        logger.info(f"Restored {ext_path}")
                    except Exception as e:
                        logger.warning(f"Failed to restore {ext_path}: {e}")
            
            # Cleanup backup
            shutil.rmtree(backup_dir, ignore_errors=True)
        
        # 8. Update database record
        current_module.version = new_manifest.version
        current_module.manifest_json = json.dumps(new_manifest.model_dump())
        session.add(current_module)
        
        # 9. Execute post_update hook
        if new_manifest.install_hooks.post_update:
            await self.execute_hook(
                new_manifest.install_hooks.post_update,
                target_path,
                "post_update"
            )
        
        logger.info(f"Successfully updated module {module_id} to version {new_manifest.version}")
        return True


# Singleton instance
module_loader = ModuleLoader()

