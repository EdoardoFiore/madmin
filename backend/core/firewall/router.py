"""
MADMIN Firewall Router

API endpoints for machine firewall management.
"""
from typing import List, Optional
import json
from fastapi import APIRouter, Depends, HTTPException, status, File, UploadFile, Query
from fastapi.responses import JSONResponse
from fastapi.encoders import jsonable_encoder
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
from .iptables import IptablesError

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
    
    try:
        rule = await firewall_orchestrator.create_rule(session, rule_data.model_dump())
        await session.commit()
        return _rule_to_response(rule)
    except IptablesError as e:
        await session.rollback()
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        await session.rollback()
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")


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
    update_data = rule_data.model_dump(exclude_unset=True)
    
    if not update_data:
        raise HTTPException(status_code=400, detail="No fields to update")
    
    try:
        rule = await firewall_orchestrator.update_rule(session, rule_uuid, update_data)
        if not rule:
            raise HTTPException(status_code=404, detail="Rule not found")
        
        await session.commit()
        return _rule_to_response(rule)
    except IptablesError as e:
        await session.rollback()
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        await session.rollback()
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")


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
    
    try:
        success = await firewall_orchestrator.delete_rule(session, rule_uuid)
        if not success:
            raise HTTPException(status_code=404, detail="Rule not found")
        
        await session.commit()
    except IptablesError as e:
        await session.rollback()
        raise HTTPException(status_code=400, detail=str(e))
    except HTTPException:
        await session.rollback()
        raise
    except Exception as e:
        await session.rollback()
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")


@router.put("/rules/order")
async def update_rule_order(
    orders: List[RuleOrderUpdate],
    current_user: User = Depends(require_permission("firewall.manage")),
    session: AsyncSession = Depends(get_session)
):
    """Update the order of firewall rules."""
    order_list = [{"id": o.id, "order": o.order} for o in orders]
    
    try:
        await firewall_orchestrator.reorder_rules(session, order_list)
        await session.commit()
        return {"status": "ok", "message": f"Updated order for {len(orders)} rules"}
    except IptablesError as e:
        await session.rollback()
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        await session.rollback()
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")


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
    
    try:
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
    except IptablesError as e:
        await session.rollback()
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        await session.rollback()
        raise HTTPException(status_code=500, detail=f"Internal server error: {str(e)}")


@router.post("/apply")
async def apply_rules(
    current_user: User = Depends(require_permission("firewall.manage")),
    session: AsyncSession = Depends(get_session)
):
    """Manually trigger rule application to iptables."""
    try:
        success = await firewall_orchestrator.apply_rules(session)
        
        if not success:
            raise HTTPException(
                status_code=500,
                detail="Failed to apply some rules. Check server logs."
            )
        
        return {"status": "ok", "message": "Rules applied successfully"}
    except IptablesError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/export", response_class=JSONResponse)
async def export_rules(
    current_user: User = Depends(require_permission("firewall.view")),
    session: AsyncSession = Depends(get_session)
):
    """
    Export all firewall rules as JSON.
    """
    rules = await firewall_orchestrator.get_all_rules(session)
    export_data = [_rule_to_response(r).model_dump() for r in rules]
    
    return JSONResponse(
        content=jsonable_encoder(export_data),
        headers={"Content-Disposition": "attachment; filename=firewall_rules.json"}
    )


@router.post("/import", status_code=status.HTTP_200_OK)
async def import_rules(
    file: UploadFile = File(...),
    mode: str = Query("append", description="Import mode: 'append' (default) or 'replace'"),
    current_user: User = Depends(require_permission("firewall.manage")),
    session: AsyncSession = Depends(get_session)
):
    """
    Import firewall rules from JSON file.
    Mode:
    - append: Add rules to existing ones (default)
    - replace: Delete all existing rules and add new ones
    """
    if mode not in ["append", "replace"]:
        raise HTTPException(status_code=400, detail="Invalid mode. Use 'append' or 'replace'")
    
    try:
        content = await file.read()
        rules_data = json.loads(content)
        
        if not isinstance(rules_data, list):
            raise HTTPException(status_code=400, detail="Invalid file format: expected a list of rules")
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid JSON file")
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Error reading file: {str(e)}")
        
    try:
        # If replace mode, clear existing rules
        if mode == "replace":
            await firewall_orchestrator.delete_all_rules(session)
            
        applied_count = 0
        errors = []
        
        for i, rule_dict in enumerate(rules_data):
            try:
                # Sanitize input (remove ID, dates, etc to treat as new rule)
                clean_data = {
                    k: v for k, v in rule_dict.items() 
                    if k in MachineFirewallRuleCreate.model_fields
                }
                
                # Check required fields
                if "chain" not in clean_data or "action" not in clean_data:
                    errors.append(f"Rule #{i+1}: Missing chain or action")
                    continue
                    
                # Create rule (validates data implicitly via Pydantic model in orchestrator or here)
                # Orchestrator create_rule accepts dict and creates model
                await firewall_orchestrator.create_rule(session, clean_data)
                applied_count += 1
                
            except Exception as e:
                errors.append(f"Rule #{i+1}: {str(e)}")
        
        await session.commit()
        
        return {
            "status": "ok", 
            "message": f"Imported {applied_count} rules", 
            "errors": errors if errors else None
        }
        
    except Exception as e:
        await session.rollback()
        raise HTTPException(status_code=500, detail=f"Import failed: {str(e)}")


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

