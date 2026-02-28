"""
MADMIN Modules Router

API endpoints for module management.
Modules are pre-installed (monolithic). Only activation/deactivation is supported.
"""
import logging
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from pydantic import BaseModel

from core.database import get_session
from core.auth.dependencies import require_permission
from core.auth.models import User
from .models import InstalledModule
from .loader import module_loader

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/modules", tags=["Modules"])


# ============== MODULE MANAGEMENT ==============


class ModuleInfo(BaseModel):
    """Module info returned to frontend."""
    id: str
    name: str
    version: str
    description: str = ""
    author: str = ""
    icon: str = "puzzle"
    enabled: bool = False
    activated: bool = False
    permissions: List[str] = []
    firewall_chains: int = 0


@router.get("/available", response_model=List[ModuleInfo])
async def list_available_modules(
    current_user: User = Depends(require_permission("modules.view")),
    session: AsyncSession = Depends(get_session)
):
    """
    List all available modules with their status.
    Reads from the modules directory and cross-references with DB.
    """
    modules = await module_loader.discover_available_modules(session)
    return [ModuleInfo(**m) for m in modules]


@router.get("/menu")
async def get_menu_items(
    current_user: User = Depends(require_permission("modules.view"))
):
    """Get all menu items from loaded modules for sidebar."""
    return module_loader.get_menu_items()


@router.post("/{module_id}/activate")
async def activate_module(
    module_id: str,
    current_user: User = Depends(require_permission("modules.manage")),
    session: AsyncSession = Depends(get_session)
):
    """
    Activate a module.
    
    First activation: runs database migrations and post_install hook.
    Subsequent activations: just enables the module.
    Requires application restart to take effect.
    """
    result = await module_loader.activate_module(session, module_id)
    
    if not result.get("success"):
        raise HTTPException(status_code=400, detail=result.get("error", "Attivazione fallita"))
    
    return result


@router.post("/{module_id}/deactivate")
async def deactivate_module(
    module_id: str,
    current_user: User = Depends(require_permission("modules.manage")),
    session: AsyncSession = Depends(get_session)
):
    """
    Deactivate a module. Data is preserved.
    Requires application restart to take effect.
    """
    result = await module_loader.deactivate_module(session, module_id)
    
    if not result.get("success"):
        raise HTTPException(status_code=400, detail=result.get("error", "Disattivazione fallita"))
    
    return result


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
