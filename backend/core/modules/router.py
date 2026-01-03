"""
MADMIN Modules Router

API endpoints for module management.
"""
import os
import json
import zipfile
import tempfile
import shutil
from pathlib import Path
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, status, UploadFile, File
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from pydantic import BaseModel

from core.database import get_session
from core.auth.dependencies import require_permission
from core.auth.models import User
from config import get_settings
from .models import InstalledModule, InstalledModuleResponse, ModuleInstallRequest, ModuleManifest
from .loader import module_loader

router = APIRouter(prefix="/api/modules", tags=["Modules"])
settings = get_settings()


class StagingModuleInfo(BaseModel):
    """Info about a module in staging folder."""
    id: str
    name: str
    version: str
    description: Optional[str] = None
    author: Optional[str] = None
    path: str


@router.get("/", response_model=List[InstalledModuleResponse])
async def list_modules(
    current_user: User = Depends(require_permission("modules.view")),
    session: AsyncSession = Depends(get_session)
):
    """List all installed modules."""
    result = await session.execute(
        select(InstalledModule).order_by(InstalledModule.name)
    )
    modules = result.scalars().all()
    
    return [
        InstalledModuleResponse(
            id=m.id,
            name=m.name,
            version=m.version,
            description=m.description,
            author=m.author,
            installed_at=m.installed_at,
            enabled=m.enabled
        )
        for m in modules
    ]


@router.get("/menu")
async def get_menu_items(
    current_user: User = Depends(require_permission("modules.view"))
):
    """Get all menu items from loaded modules for sidebar."""
    return module_loader.get_menu_items()


@router.get("/staging", response_model=List[StagingModuleInfo])
async def list_staging_modules(
    current_user: User = Depends(require_permission("modules.manage")),
    session: AsyncSession = Depends(get_session)
):
    """
    List modules available in staging folder (not yet installed).
    
    Staging folder is scanned for directories containing manifest.json.
    Already installed modules are filtered out.
    """
    staging_path = Path(settings.staging_dir)
    
    if not staging_path.exists():
        return []
    
    # Get installed module IDs
    result = await session.execute(select(InstalledModule.id))
    installed_ids = {row[0] for row in result.fetchall()}
    
    available = []
    
    for item in staging_path.iterdir():
        if not item.is_dir():
            continue
        
        manifest_path = item / "manifest.json"
        if not manifest_path.exists():
            continue
        
        try:
            with open(manifest_path, "r", encoding="utf-8") as f:
                manifest_data = json.load(f)
            
            module_id = manifest_data.get("id", item.name)
            
            # Skip if already installed
            if module_id in installed_ids:
                continue
            
            available.append(StagingModuleInfo(
                id=module_id,
                name=manifest_data.get("name", module_id),
                version=manifest_data.get("version", "1.0.0"),
                description=manifest_data.get("description"),
                author=manifest_data.get("author"),
                path=str(item)
            ))
        except (json.JSONDecodeError, IOError):
            continue
    
    return available


@router.post("/upload", response_model=StagingModuleInfo)
async def upload_module_zip(
    file: UploadFile = File(...),
    current_user: User = Depends(require_permission("modules.manage"))
):
    """
    Upload a module ZIP file.
    
    The ZIP is extracted to the staging folder. It must contain:
    - manifest.json at the root, OR
    - A single subfolder containing manifest.json
    
    After upload, use /install endpoint to actually install the module.
    """
    if not file.filename.endswith(".zip"):
        raise HTTPException(status_code=400, detail="Il file deve essere un .zip")
    
    staging_path = Path(settings.staging_dir)
    staging_path.mkdir(parents=True, exist_ok=True)
    
    # Save ZIP to temp file
    with tempfile.NamedTemporaryFile(delete=False, suffix=".zip") as tmp:
        content = await file.read()
        tmp.write(content)
        tmp_path = tmp.name
    
    try:
        with zipfile.ZipFile(tmp_path, 'r') as zf:
            # Check ZIP structure
            names = zf.namelist()
            
            # Case 1: manifest.json at root
            if "manifest.json" in names:
                # Read manifest to get module ID
                with zf.open("manifest.json") as mf:
                    manifest_data = json.load(mf)
                module_id = manifest_data.get("id")
                if not module_id:
                    raise HTTPException(status_code=400, detail="manifest.json manca campo 'id'")
                
                # Extract to staging/module_id
                target_path = staging_path / module_id
                if target_path.exists():
                    shutil.rmtree(target_path)
                target_path.mkdir(parents=True)
                zf.extractall(target_path)
            
            # Case 2: Single subfolder with manifest.json
            else:
                # Find subfolder
                subfolders = set()
                for name in names:
                    parts = name.split("/")
                    if len(parts) > 1 and parts[0]:
                        subfolders.add(parts[0])
                
                if len(subfolders) != 1:
                    raise HTTPException(
                        status_code=400, 
                        detail="ZIP deve contenere manifest.json alla root o una singola cartella con manifest.json"
                    )
                
                subfolder = list(subfolders)[0]
                manifest_name = f"{subfolder}/manifest.json"
                
                if manifest_name not in names:
                    raise HTTPException(status_code=400, detail="manifest.json non trovato nel ZIP")
                
                with zf.open(manifest_name) as mf:
                    manifest_data = json.load(mf)
                module_id = manifest_data.get("id", subfolder)
                
                # Extract to staging/module_id
                target_path = staging_path / module_id
                if target_path.exists():
                    shutil.rmtree(target_path)
                target_path.mkdir(parents=True)
                
                # Extract by stripping the subfolder prefix
                for name in names:
                    if not name.startswith(subfolder + "/"):
                        continue
                    relative = name[len(subfolder) + 1:]
                    if not relative:
                        continue
                    
                    target = target_path / relative
                    if name.endswith("/"):
                        target.mkdir(parents=True, exist_ok=True)
                    else:
                        target.parent.mkdir(parents=True, exist_ok=True)
                        with zf.open(name) as src, open(target, "wb") as dst:
                            dst.write(src.read())
        
        return StagingModuleInfo(
            id=module_id,
            name=manifest_data.get("name", module_id),
            version=manifest_data.get("version", "1.0.0"),
            description=manifest_data.get("description"),
            author=manifest_data.get("author"),
            path=str(target_path)
        )
    
    except zipfile.BadZipFile:
        raise HTTPException(status_code=400, detail="File ZIP non valido")
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="manifest.json non valido")
    finally:
        # Cleanup temp file
        os.unlink(tmp_path)



@router.post("/install", response_model=InstalledModuleResponse, status_code=status.HTTP_201_CREATED)
async def install_module(
    request: ModuleInstallRequest,
    current_user: User = Depends(require_permission("modules.manage")),
    session: AsyncSession = Depends(get_session)
):
    """
    Install a module from staging or URL.
    
    For now, only staging installation is supported.
    """
    if request.source != "staging":
        raise HTTPException(
            status_code=400,
            detail="Only 'staging' source is currently supported"
        )
    
    if not request.module_id:
        raise HTTPException(
            status_code=400,
            detail="module_id is required for staging installation"
        )
    
    installed = await module_loader.install_from_staging(session, request.module_id)
    
    if not installed:
        raise HTTPException(
            status_code=400,
            detail="Failed to install module. Check server logs."
        )
    
    await session.commit()
    
    # Post-install: Try to register module firewall chains if the module has that capability
    try:
        modules_dir = Path(settings.modules_dir)
        service_path = modules_dir / request.module_id / "service.py"
        
        if service_path.exists():
            import importlib.util
            spec = importlib.util.spec_from_file_location(f"{request.module_id}.service", service_path)
            if spec and spec.loader:
                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)
                
                # Check for WireGuardService or similar service class with register_module_chains
                for attr_name in dir(module):
                    attr = getattr(module, attr_name)
                    if isinstance(attr, type) and hasattr(attr, 'register_module_chains'):
                        # Found a service class with register_module_chains
                        await attr.register_module_chains(session)
                        await session.commit()
                        break
    except Exception as e:
        # Log but don't fail installation if chain registration fails
        import logging
        logging.getLogger(__name__).warning(f"Failed to register module chains: {e}")
    
    return InstalledModuleResponse(
        id=installed.id,
        name=installed.name,
        version=installed.version,
        description=installed.description,
        author=installed.author,
        installed_at=installed.installed_at,
        enabled=installed.enabled
    )


@router.delete("/{module_id}", status_code=status.HTTP_204_NO_CONTENT)
async def uninstall_module(
    module_id: str,
    current_user: User = Depends(require_permission("modules.manage")),
    session: AsyncSession = Depends(get_session)
):
    """Uninstall a module."""
    success = await module_loader.uninstall_module(session, module_id)
    
    if not success:
        raise HTTPException(
            status_code=404,
            detail="Module not found or uninstall failed"
        )
    
    await session.commit()


@router.patch("/{module_id}/enable")
async def enable_module(
    module_id: str,
    current_user: User = Depends(require_permission("modules.manage")),
    session: AsyncSession = Depends(get_session)
):
    """Enable a module."""
    result = await session.execute(
        select(InstalledModule).where(InstalledModule.id == module_id)
    )
    module = result.scalar_one_or_none()
    
    if not module:
        raise HTTPException(status_code=404, detail="Module not found")
    
    module.enabled = True
    session.add(module)
    await session.commit()
    
    return {"status": "ok", "message": f"Module {module_id} enabled. Restart required."}


@router.patch("/{module_id}/disable")
async def disable_module(
    module_id: str,
    current_user: User = Depends(require_permission("modules.manage")),
    session: AsyncSession = Depends(get_session)
):
    """Disable a module."""
    result = await session.execute(
        select(InstalledModule).where(InstalledModule.id == module_id)
    )
    module = result.scalar_one_or_none()
    
    if not module:
        raise HTTPException(status_code=404, detail="Module not found")
    
    module.enabled = False
    session.add(module)
    await session.commit()
    
    return {"status": "ok", "message": f"Module {module_id} disabled. Restart required."}


# ============== STORE ENDPOINTS ==============

from .store import module_store, StoreModule


class StoreInstallRequest(BaseModel):
    """Request to install module from store."""
    module_id: str
    version: Optional[str] = None


@router.get("/store/available")
async def get_store_modules(
    current_user: User = Depends(require_permission("modules.view")),
    session: AsyncSession = Depends(get_session)
):
    """
    Get all modules available in the store.
    Returns modules from cloud registry with install status.
    """
    try:
        available = await module_store.get_available_modules()
    except Exception as e:
        raise HTTPException(
            status_code=503,
            detail=f"Impossibile contattare il registry: {str(e)}"
        )
    
    # Get installed module IDs
    result = await session.execute(select(InstalledModule.id, InstalledModule.version))
    installed = {row[0]: row[1] for row in result.fetchall()}
    
    # Get staging module IDs
    staging_path = Path(settings.staging_dir)
    staging_ids = set()
    if staging_path.exists():
        for item in staging_path.iterdir():
            if item.is_dir() and (item / "manifest.json").exists():
                staging_ids.add(item.name)
    
    # Enrich with install status
    modules = []
    for mod in available:
        status = "available"
        if mod.id in installed:
            current_ver = installed[mod.id]
            if mod.version > current_ver:
                status = "update_available"
            else:
                status = "installed"
        elif mod.id in staging_ids:
            status = "in_staging"
        
        modules.append({
            **mod.model_dump(),
            "install_status": status,
            "installed_version": installed.get(mod.id)
        })
    
    return {"modules": modules}


@router.get("/store/module/{module_id}")
async def get_store_module_details(
    module_id: str,
    current_user: User = Depends(require_permission("modules.view"))
):
    """Get details for a specific module from the store."""
    module = await module_store.get_module_info(module_id)
    
    if not module:
        raise HTTPException(status_code=404, detail="Modulo non trovato nel registry")
    
    return module.model_dump()


@router.post("/store/install")
async def install_from_store(
    request: StoreInstallRequest,
    current_user: User = Depends(require_permission("modules.manage")),
    session: AsyncSession = Depends(get_session)
):
    """
    Download and install a module from the store (GitHub).
    
    Downloads to staging folder. Use /install endpoint to complete installation.
    """
    result = await module_store.install_module(
        request.module_id,
        request.version
    )
    
    if not result.get("success"):
        raise HTTPException(
            status_code=400,
            detail=result.get("error", "Installazione fallita")
        )
    
    return result


@router.get("/store/updates")
async def check_store_updates(
    current_user: User = Depends(require_permission("modules.view")),
    session: AsyncSession = Depends(get_session)
):
    """Check for available updates for installed modules."""
    result = await session.execute(
        select(InstalledModule.id, InstalledModule.version)
    )
    installed = [{"id": row[0], "version": row[1]} for row in result.fetchall()]
    
    updates = await module_store.check_updates(installed)
    
    return {"updates": updates, "count": len(updates)}

