"""
MADMIN Module Loader

Handles discovery, loading, and activation of bundled modules.
All modules are pre-installed in backend/modules/. This loader handles:
- Discovery of available modules from the modules directory
- Loading enabled modules (router, static, permissions, chains)
- Activate/deactivate lifecycle (migrations on first activation)
"""
import os
import json
import logging
import importlib.util
import asyncio
from pathlib import Path
from typing import List, Optional, Dict, Any
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from fastapi import FastAPI, APIRouter
from fastapi.staticfiles import StaticFiles

from config import get_settings
from .models import InstalledModule, ModuleManifest, ModulePermission

logger = logging.getLogger(__name__)
settings = get_settings()


class ModuleLoader:
    """
    Discovers and loads bundled modules.
    
    Modules are pre-installed in the modules directory and can provide:
    - FastAPI router for backend endpoints
    - Static files for frontend
    - Permissions for access control
    - Firewall chain definitions
    """
    
    def __init__(self):
        self.loaded_modules: Dict[str, Dict[str, Any]] = {}
        self.modules_dir = Path(settings.modules_dir)
    
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
        Discover all available modules by scanning the modules directory.
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
        Discover and load all enabled modules.
        
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
            
            # Skip modules that were never activated
            if not db_module:
                logger.info(f"Skipping never-activated module: {module_id}")
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
    
    async def activate_module(
        self,
        session: AsyncSession,
        module_id: str
    ) -> dict:
        """
        Activate a module. 
        
        First activation: runs DB migrations + post_install hook.
        Subsequent activations: just sets enabled=true.
        
        Returns dict with status info.
        """
        module_path = self.modules_dir / module_id
        manifest_path = module_path / "manifest.json"
        
        if not manifest_path.exists():
            return {"success": False, "error": f"Modulo '{module_id}' non trovato"}
        
        manifest = self._parse_manifest(manifest_path)
        if not manifest:
            return {"success": False, "error": "Manifest non valido"}
        
        # Get or create DB record
        result = await session.execute(
            select(InstalledModule).where(InstalledModule.id == module_id)
        )
        db_module = result.scalar_one_or_none()
        
        if db_module and db_module.enabled:
            return {"success": True, "message": "Modulo già attivo"}
        
        first_activation = (db_module is None) or (not db_module.activated)
        
        if first_activation:
            # Run database migrations
            logger.info(f"First activation of {module_id} — running migrations")
            if not await self.run_database_migrations(manifest, module_path, session):
                return {"success": False, "error": "Migrazione database fallita"}
            
            # Execute post_install hook
            if manifest.install_hooks.post_install:
                await self.execute_hook(
                    manifest.install_hooks.post_install,
                    module_path,
                    "post_install"
                )
        
        # Create or update DB record
        if db_module:
            db_module.enabled = True
            db_module.activated = True
            db_module.version = manifest.version
            db_module.manifest_json = json.dumps(manifest.model_dump())
        else:
            db_module = InstalledModule(
                id=manifest.id,
                name=manifest.name,
                version=manifest.version,
                description=manifest.description or "",
                author=manifest.author or "",
                install_path=str(module_path),
                manifest_json=json.dumps(manifest.model_dump()),
                enabled=True,
                activated=True
            )
            session.add(db_module)
        
        await session.commit()
        
        logger.info(f"Activated module: {module_id} v{manifest.version}")
        return {
            "success": True,
            "first_activation": first_activation,
            "message": f"Modulo {manifest.name} attivato. Riavvio richiesto."
        }
    
    async def deactivate_module(
        self,
        session: AsyncSession,
        module_id: str
    ) -> dict:
        """
        Deactivate a module. Sets enabled=false, preserves all data.
        
        Returns dict with status info.
        """
        result = await session.execute(
            select(InstalledModule).where(InstalledModule.id == module_id)
        )
        db_module = result.scalar_one_or_none()
        
        if not db_module:
            return {"success": False, "error": f"Modulo '{module_id}' non trovato nel database"}
        
        if not db_module.enabled:
            return {"success": True, "message": "Modulo già disabilitato"}
        
        db_module.enabled = False
        await session.commit()
        
        logger.info(f"Deactivated module: {module_id}")
        return {
            "success": True,
            "message": f"Modulo {db_module.name} disabilitato. Dati preservati. Riavvio richiesto."
        }
    
    async def discover_available_modules(
        self,
        session: AsyncSession
    ) -> List[Dict[str, Any]]:
        """
        List all modules in the modules directory with their status.
        Used by the frontend to show available modules with enable/disable toggle.
        """
        available = []
        
        if not self.modules_dir.exists():
            return available
        
        for item in self.modules_dir.iterdir():
            if not item.is_dir():
                continue
            manifest_path = item / "manifest.json"
            if not manifest_path.exists():
                continue
            
            manifest = self._parse_manifest(manifest_path)
            if not manifest:
                continue
            
            # Check DB status
            result = await session.execute(
                select(InstalledModule).where(InstalledModule.id == manifest.id)
            )
            db_module = result.scalar_one_or_none()
            
            available.append({
                "id": manifest.id,
                "name": manifest.name,
                "version": manifest.version,
                "description": manifest.description or "",
                "author": manifest.author or "",
                "icon": manifest.menu[0].icon if manifest.menu else "puzzle",
                "enabled": db_module.enabled if db_module else False,
                "activated": db_module.activated if db_module else False,
                "permissions": [p.slug for p in manifest.permissions],
                "firewall_chains": len(manifest.firewall_chains),
            })
        
        return available


# Singleton instance
module_loader = ModuleLoader()
