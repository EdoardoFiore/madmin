"""
MADMIN Firewall Router

API endpoints for machine firewall management.
"""
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import SQLModel
import uuid

from core.database import get_session
from core.auth.dependencies import require_permission, get_current_user
from core.auth.models import User
from .models import (
    MachineFirewallRuleCreate,
    MachineFirewallRuleUpdate,
    MachineFirewallRuleResponse,
    RuleOrderUpdate,
    ModuleChainResponse
)
from .orchestrator import firewall_orchestrator

router = APIRouter(prefix="/api/firewall", tags=["Firewall"])


def _rule_to_response(rule) -> MachineFirewallRuleResponse:
    """Convert database model to API response."""
    return MachineFirewallRuleResponse(
        id=str(rule.id),
        chain=rule.chain,
        action=rule.action,
        protocol=rule.protocol,
        source=rule.source,
        destination=rule.destination,
        port=rule.port,
        in_interface=rule.in_interface,
        out_interface=rule.out_interface,
        state=rule.state,
        limit_rate=rule.limit_rate,
        limit_burst=rule.limit_burst,
        to_destination=rule.to_destination,
        to_source=rule.to_source,
        to_ports=rule.to_ports,
        log_prefix=rule.log_prefix,
        log_level=rule.log_level,
        reject_with=rule.reject_with,
        comment=rule.comment,
        table_name=rule.table_name,
        order=rule.order,
        enabled=rule.enabled,
        created_at=rule.created_at,
        updated_at=rule.updated_at
    )


@router.get("/rules", response_model=List[MachineFirewallRuleResponse])
async def list_rules(
    chain: Optional[str] = None,
    current_user: User = Depends(require_permission("firewall.view")),
    session: AsyncSession = Depends(get_session)
):
    """List all firewall rules, optionally filtered by chain."""
    rules = await firewall_orchestrator.get_all_rules(session, chain)
    return [_rule_to_response(r) for r in rules]


@router.get("/rules/{rule_id}", response_model=MachineFirewallRuleResponse)
async def get_rule(
    rule_id: str,
    current_user: User = Depends(require_permission("firewall.view")),
    session: AsyncSession = Depends(get_session)
):
    """Get a specific firewall rule by ID."""
    try:
        rule_uuid = uuid.UUID(rule_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid rule ID format")
    
    rule = await firewall_orchestrator.get_rule_by_id(session, rule_uuid)
    if not rule:
        raise HTTPException(status_code=404, detail="Rule not found")
    
    return _rule_to_response(rule)


@router.post("/rules", response_model=MachineFirewallRuleResponse, status_code=status.HTTP_201_CREATED)
async def create_rule(
    rule_data: MachineFirewallRuleCreate,
    current_user: User = Depends(require_permission("firewall.manage")),
    session: AsyncSession = Depends(get_session)
):
    """Create a new firewall rule."""
    # Valid chains per table
    table_chains = {
        "filter": ("INPUT", "OUTPUT", "FORWARD"),
        "nat": ("PREROUTING", "POSTROUTING", "OUTPUT"),
        "mangle": ("PREROUTING", "INPUT", "FORWARD", "OUTPUT", "POSTROUTING"),
        "raw": ("PREROUTING", "OUTPUT")
    }
    
    table = rule_data.table_name or "filter"
    if table not in table_chains:
        raise HTTPException(status_code=400, detail=f"Table must be one of: {', '.join(table_chains.keys())}")
    
    if rule_data.chain not in table_chains[table]:
        raise HTTPException(
            status_code=400,
            detail=f"Chain for table {table} must be one of: {', '.join(table_chains[table])}"
        )
    
    # Valid actions per table
    table_actions = {
        "filter": ("ACCEPT", "DROP", "REJECT", "LOG", "RETURN"),
        "nat": ("SNAT", "DNAT", "MASQUERADE", "REDIRECT", "ACCEPT", "RETURN"),
        "mangle": ("MARK", "TOS", "TTL", "ACCEPT", "RETURN"),
        "raw": ("NOTRACK", "ACCEPT", "RETURN")
    }
    
    if rule_data.action not in table_actions[table]:
        raise HTTPException(
            status_code=400,
            detail=f"Action for table {table} must be one of: {', '.join(table_actions[table])}"
        )
    
    rule = await firewall_orchestrator.create_rule(session, rule_data.model_dump())
    await session.commit()
    
    return _rule_to_response(rule)


@router.patch("/rules/{rule_id}", response_model=MachineFirewallRuleResponse)
async def update_rule(
    rule_id: str,
    rule_data: MachineFirewallRuleUpdate,
    current_user: User = Depends(require_permission("firewall.manage")),
    session: AsyncSession = Depends(get_session)
):
    """Update an existing firewall rule."""
    try:
        rule_uuid = uuid.UUID(rule_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid rule ID format")
    
    # Filter out None values
    update_data = {k: v for k, v in rule_data.model_dump().items() if v is not None}
    
    if not update_data:
        raise HTTPException(status_code=400, detail="No fields to update")
    
    rule = await firewall_orchestrator.update_rule(session, rule_uuid, update_data)
    if not rule:
        raise HTTPException(status_code=404, detail="Rule not found")
    
    await session.commit()
    return _rule_to_response(rule)


@router.delete("/rules/{rule_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_rule(
    rule_id: str,
    current_user: User = Depends(require_permission("firewall.manage")),
    session: AsyncSession = Depends(get_session)
):
    """Delete a firewall rule."""
    try:
        rule_uuid = uuid.UUID(rule_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid rule ID format")
    
    success = await firewall_orchestrator.delete_rule(session, rule_uuid)
    if not success:
        raise HTTPException(status_code=404, detail="Rule not found")
    
    await session.commit()


@router.put("/rules/order")
async def update_rule_order(
    orders: List[RuleOrderUpdate],
    current_user: User = Depends(require_permission("firewall.manage")),
    session: AsyncSession = Depends(get_session)
):
    """Update the order of firewall rules."""
    order_list = [{"id": o.id, "order": o.order} for o in orders]
    
    await firewall_orchestrator.reorder_rules(session, order_list)
    await session.commit()
    
    return {"status": "ok", "message": f"Updated order for {len(orders)} rules"}


class SingleRuleReorder(SQLModel):
    new_order: int


@router.patch("/rules/{rule_id}/reorder")
async def reorder_single_rule(
    rule_id: str,
    data: SingleRuleReorder,
    current_user: User = Depends(require_permission("firewall.manage")),
    session: AsyncSession = Depends(get_session)
):
    """Move a single rule to a new position."""
    try:
        rule_uuid = uuid.UUID(rule_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid rule ID format")
    
    from sqlalchemy import select
    from .models import MachineFirewallRule
    
    # Get the rule
    result = await session.execute(
        select(MachineFirewallRule).where(MachineFirewallRule.id == rule_uuid)
    )
    rule = result.scalar_one_or_none()
    if not rule:
        raise HTTPException(status_code=404, detail="Rule not found")
    
    old_order = rule.order
    new_order = data.new_order
    
    # Get all rules in the same chain/table
    chain_rules = await session.execute(
        select(MachineFirewallRule)
        .where(MachineFirewallRule.chain == rule.chain)
        .where(MachineFirewallRule.table_name == rule.table_name)
        .order_by(MachineFirewallRule.order)
    )
    all_rules = list(chain_rules.scalars().all())
    
    # Shift rules
    if new_order < old_order:
        # Moving up
        for r in all_rules:
            if r.id != rule.id and r.order >= new_order and r.order < old_order:
                r.order += 1
    else:
        # Moving down
        for r in all_rules:
            if r.id != rule.id and r.order > old_order and r.order <= new_order:
                r.order -= 1
    
    rule.order = new_order
    await session.commit()
    
    # Re-apply rules
    await firewall_orchestrator.apply_rules(session)
    
    return {"status": "ok", "message": f"Rule moved to position {new_order}"}


@router.post("/apply")
async def apply_rules(
    current_user: User = Depends(require_permission("firewall.manage")),
    session: AsyncSession = Depends(get_session)
):
    """Manually trigger rule application to iptables."""
    success = await firewall_orchestrator.apply_rules(session)
    
    if not success:
        raise HTTPException(
            status_code=500,
            detail="Failed to apply some rules. Check server logs."
        )
    
    return {"status": "ok", "message": "Rules applied successfully"}


# --- Module Chain Endpoints (for admin/debug) ---

@router.get("/chains", response_model=List[ModuleChainResponse])
async def list_module_chains(
    current_user: User = Depends(require_permission("firewall.view")),
    session: AsyncSession = Depends(get_session)
):
    """List all registered module chains."""
    from sqlalchemy import select
    from .models import ModuleChain
    
    result = await session.execute(
        select(ModuleChain).order_by(ModuleChain.parent_chain, ModuleChain.priority)
    )
    chains = result.scalars().all()
    
    return [
        ModuleChainResponse(
            id=str(c.id),
            module_id=c.module_id,
            chain_name=c.chain_name,
            parent_chain=c.parent_chain,
            priority=c.priority,
            table_name=c.table_name
        )
        for c in chains
    ]


class ModuleChainOrderUpdate(SQLModel):
    """Schema for updating module chain priority."""
    id: str
    priority: int


@router.put("/chains/order")
async def update_chain_order(
    orders: List[ModuleChainOrderUpdate],
    current_user: User = Depends(require_permission("firewall.manage")),
    session: AsyncSession = Depends(get_session)
):
    """
    Update the priority order of module chains.
    Lower priority = processed first (after MADMIN).
    """
    from sqlalchemy import select
    from .models import ModuleChain
    
    for item in orders:
        try:
            chain_uuid = uuid.UUID(item.id)
        except ValueError:
            continue
        
        result = await session.execute(
            select(ModuleChain).where(ModuleChain.id == chain_uuid)
        )
        chain = result.scalar_one_or_none()
        if chain:
            chain.priority = item.priority
            session.add(chain)
    
    await session.commit()
    
    # Rebuild all chain jumps to reflect new priorities
    # Get unique parent chains that need rebuilding
    result = await session.execute(select(ModuleChain))
    all_chains = result.scalars().all()
    
    rebuilt = set()
    for chain in all_chains:
        key = (chain.parent_chain, chain.table_name)
        if key not in rebuilt:
            await firewall_orchestrator.rebuild_chain_jumps(session, chain.parent_chain, chain.table_name)
            rebuilt.add(key)
    
    return {"status": "ok", "message": f"Updated priority for {len(orders)} chains"}

