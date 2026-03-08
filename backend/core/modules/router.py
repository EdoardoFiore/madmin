"""
MADMIN Modules Router

API endpoints for module management.
Modules are pre-installed (monolithic). Only activation/deactivation is supported.
"""
import logging
from pathlib import Path
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import PlainTextResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from pydantic import BaseModel

from core.database import get_session
from core.auth.dependencies import require_permission, get_current_user
from core.auth.models import User
from config import get_settings
from .models import InstalledModule
from .loader import module_loader

logger = logging.getLogger(__name__)
settings = get_settings()

router = APIRouter(prefix="/api/modules", tags=["Modules"])


# ============== MODULE MANAGEMENT ==============


@router.get("/available")
async def list_available_modules(
    current_user: User = Depends(require_permission("modules.view")),
    session: AsyncSession = Depends(get_session)
):
    """
    List all available modules with their status and details.
    """
    return await module_loader.discover_available_modules(session)


@router.get("/menu")
async def get_menu_items(
    current_user: User = Depends(require_permission("modules.view"))
):
    """Get all menu items from loaded modules for sidebar."""
    return module_loader.get_menu_items()


@router.get("/widgets")
async def get_module_widgets(
    current_user: User = Depends(get_current_user)
):
    """Get all dashboard widgets from active modules, filtered by user permissions."""
    all_widgets = module_loader.get_dashboard_widgets()
    
    # Filter by user permissions
    result = []
    for w in all_widgets:
        perm = w.get("permission")
        if perm:
            # Check if user has the required permission
            if not (currentUser_is_super := currentUser_has_perm(current_user, perm)):
                continue
        result.append({
            "module_id": w["module_id"],
            "widget_id": w["widget_id"],
            "title": w["title"],
            "col": w["col"],
        })
    
    return result


def currentUser_has_perm(user: User, permission: str) -> bool:
    """Check if user has a specific permission."""
    if user.is_superuser:
        return True
    try:
        import json
        perms = json.loads(user.permissions) if isinstance(user.permissions, str) else user.permissions
        return "*" in perms or permission in perms
    except Exception:
        return False

@router.post("/{module_id}/activate")
async def activate_module(
    module_id: str,
    current_user: User = Depends(require_permission("modules.manage")),
    session: AsyncSession = Depends(get_session)
):
    """
    Activate a module.
    Runs database migrations and post_install hook.
    """
    try:
        result = await module_loader.activate_module(session, module_id)
        
        if not result.get("success"):
            raise HTTPException(status_code=400, detail=result.get("error", "Attivazione fallita"))
        
        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Unexpected error activating module {module_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Errore imprevisto durante l'attivazione: {str(e)}")


@router.post("/{module_id}/deactivate")
async def deactivate_module(
    module_id: str,
    current_user: User = Depends(require_permission("modules.manage")),
    session: AsyncSession = Depends(get_session)
):
    """
    Deactivate a module with full cleanup.
    Removes chains, permissions, and drops module tables.
    """
    try:
        result = await module_loader.deactivate_module(session, module_id)
        
        if not result.get("success"):
            raise HTTPException(status_code=400, detail=result.get("error", "Disattivazione fallita"))
        
        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Unexpected error deactivating module {module_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Errore imprevisto durante la disattivazione: {str(e)}")


@router.get("/{module_id}/readme")
async def get_module_readme(
    module_id: str,
    current_user: User = Depends(require_permission("modules.view"))
):
    """Get a module's README.md content."""
    module_path = Path(settings.modules_dir) / module_id / "README.md"
    
    if not module_path.exists():
        raise HTTPException(status_code=404, detail="README non trovato")
    
    try:
        content = module_path.read_text(encoding="utf-8")
        return {"content": content}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ============== FIREWALL CHAIN PRIORITY ==============


class ChainPriorityItem(BaseModel):
    chain_name: str
    priority: int


class ChainPriorityUpdate(BaseModel):
    chains: List[ChainPriorityItem]


@router.get("/chains/priority")
async def get_chain_priorities(
    current_user: User = Depends(require_permission("modules.view")),
    session: AsyncSession = Depends(get_session)
):
    """Get all module firewall chain priorities."""
    from core.firewall.models import ModuleChain
    
    result = await session.execute(
        select(ModuleChain).order_by(ModuleChain.priority)
    )
    chains = result.scalars().all()
    
    return [
        {
            "chain_name": c.chain_name,
            "module_id": c.module_id,
            "parent_chain": c.parent_chain,
            "priority": c.priority,
            "table_name": c.table_name
        }
        for c in chains
    ]


@router.put("/chains/priority")
async def update_chain_priorities(
    update: ChainPriorityUpdate,
    current_user: User = Depends(require_permission("modules.manage")),
    session: AsyncSession = Depends(get_session)
):
    """Update firewall chain priorities."""
    from core.firewall.models import ModuleChain
    
    for item in update.chains:
        result = await session.execute(
            select(ModuleChain).where(ModuleChain.chain_name == item.chain_name)
        )
        chain = result.scalar_one_or_none()
        
        if chain:
            chain.priority = item.priority
    
    await session.commit()
    
    return {"status": "ok", "message": "Priorità aggiornate. Riavvio richiesto."}

