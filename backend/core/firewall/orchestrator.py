"""
MADMIN Firewall Orchestrator

High-level firewall management that coordinates:
- Core MADMIN chains (MADMIN_INPUT, MADMIN_OUTPUT, MADMIN_FORWARD)
- Module chains with priority-based ordering
- Rule application from database
"""
import logging
from typing import List, Dict, Optional
from datetime import datetime
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update, delete
import uuid

from .models import MachineFirewallRule, ModuleChain
from . import iptables

logger = logging.getLogger(__name__)


class FirewallOrchestrator:
    """
    Orchestrates firewall chain management and rule application.
    
    Provides a high-level interface for:
    - Managing core chains
    - Registering/unregistering module chains
    - CRUD operations on firewall rules
    - Applying rules from database
    """
    
    def __init__(self):
        self._initialized = False
    
    async def initialize(self) -> bool:
        """
        Initialize core firewall chains.
        Should be called on application startup.
        """
        success = iptables.initialize_core_chains()
        self._initialized = success
        return success
    
    # --- Module Chain Management ---
    
    async def register_module_chain(
        self,
        session: AsyncSession,
        module_id: str,
        chain_name: str,
        parent_chain: str,
        priority: int = 50,
        table_name: str = "filter"
    ) -> Optional[ModuleChain]:
        """
        Register a new chain for a module.
        
        Args:
            session: Database session
            module_id: Module identifier
            chain_name: Unique chain name (e.g., MOD_WIREGUARD_FWD)
            parent_chain: Parent chain (INPUT, OUTPUT, FORWARD)
            priority: Lower = processed first
            table_name: iptables table
        
        Returns:
            Created ModuleChain or None on failure
        """
        # Check if chain already exists
        result = await session.execute(
            select(ModuleChain).where(ModuleChain.chain_name == chain_name)
        )
        existing = result.scalar_one_or_none()
        
        if existing:
            # Update DB record if fields changed (e.g. table fix or priority change)
            if (existing.table_name != table_name or 
                existing.parent_chain != parent_chain or 
                existing.priority != priority):
                
                existing.table_name = table_name
                existing.parent_chain = parent_chain
                existing.priority = priority
                session.add(existing)
                await session.flush()
                logger.info(f"Updated module chain {chain_name} configuration")

            # Chain exists in DB, but we MUST ensure physical chain exists (e.g. after restart)
            # Use create_chain (not flush) to preserve existing rules if any, but ensure it exists
            if not iptables.create_chain(chain_name, table_name):
                logger.error(f"Failed to ensure iptables chain {chain_name} exists")
                # Continue anyway to try to rebuild jumps
        else:
            # New chain, create and register
            # Create chain in iptables (flush if exists to be safe/clean)
            if not iptables.create_or_flush_chain(chain_name, table_name):
                logger.error(f"Failed to create iptables chain {chain_name}")
                return None
            
            # Register in database
            chain = ModuleChain(
                module_id=module_id,
                chain_name=chain_name,
                parent_chain=parent_chain,
                priority=priority,
                table_name=table_name
            )
            session.add(chain)
            await session.flush()
        
        # Rebuild jump rules (ALWAYS, to ensure integration)
        await self.rebuild_chain_jumps(session, parent_chain, table_name)
        
        if not existing:
            logger.info(f"Registered module chain {chain_name} for module {module_id}")
        return existing or chain
    
    async def unregister_module_chain(
        self,
        session: AsyncSession,
        chain_name: str
    ) -> bool:
        """
        Unregister a module chain.
        Removes the chain from iptables and database.
        """
        result = await session.execute(
            select(ModuleChain).where(ModuleChain.chain_name == chain_name)
        )
        chain = result.scalar_one_or_none()
        
        if not chain:
            return False
        
        parent_chain = chain.parent_chain
        table_name = chain.table_name
        
        # Remove jump rule
        iptables.remove_jump_rule(parent_chain, chain_name, table_name)
        
        # Delete the chain
        iptables.delete_chain(chain_name, table_name)
        
        # Remove from database
        await session.delete(chain)
        
        logger.info(f"Unregistered module chain {chain_name}")
        return True
    
    async def rebuild_chain_jumps(
        self,
        session: AsyncSession,
        parent_chain: str,
        table_name: str = "filter"
    ) -> None:
        """
        Rebuild jump rules for a parent chain based on priorities.
        
        Order: Core MADMIN chain first (highest priority) -> Module chains (by priority)
        """
        # Get all module chains for this parent, ordered by priority
        result = await session.execute(
            select(ModuleChain)
            .where(ModuleChain.parent_chain == parent_chain)
            .where(ModuleChain.table_name == table_name)
            .order_by(ModuleChain.priority)
        )
        module_chains = result.scalars().all()
        
        # Get the core MADMIN chain for this parent and table
        core_chain = iptables.get_madmin_chain(table_name, parent_chain)
        
        # Remove all existing jumps to module chains and core chain
        for mc in module_chains:
            iptables.remove_jump_rule(parent_chain, mc.chain_name, table_name)
        if core_chain:
            iptables.remove_jump_rule(parent_chain, core_chain, table_name)
        
        # Re-add jumps in correct priority order
        # MADMIN core chain FIRST (highest priority), then modules by priority
        position = 1
        
        # Core chain comes first (machine firewall rules have priority)
        if core_chain:
            iptables.ensure_jump_rule(parent_chain, core_chain, table_name, position)
            position += 1
        
        # Module chains follow in priority order (lower priority number = higher priority)
        for mc in module_chains:
            iptables.ensure_jump_rule(parent_chain, mc.chain_name, table_name, position)
            position += 1
    
    # --- Rule Management ---
    
    async def get_all_rules(
        self,
        session: AsyncSession,
        chain: Optional[str] = None
    ) -> List[MachineFirewallRule]:
        """Get all firewall rules, optionally filtered by chain."""
        query = select(MachineFirewallRule).order_by(
            MachineFirewallRule.chain,
            MachineFirewallRule.order
        )
        
        if chain:
            query = query.where(MachineFirewallRule.chain == chain)
        
        result = await session.execute(query)
        return result.scalars().all()
    
    async def get_rule_by_id(
        self,
        session: AsyncSession,
        rule_id: uuid.UUID
    ) -> Optional[MachineFirewallRule]:
        """Get a specific rule by ID."""
        result = await session.execute(
            select(MachineFirewallRule).where(MachineFirewallRule.id == rule_id)
        )
        return result.scalar_one_or_none()
    
    async def create_rule(
        self,
        session: AsyncSession,
        rule_data: Dict
    ) -> MachineFirewallRule:
        """
        Create a new firewall rule.
        Automatically assigns order (appends to end of chain).
        """
        chain = rule_data.get("chain", "INPUT")
        
        # Get max order for this chain
        result = await session.execute(
            select(MachineFirewallRule)
            .where(MachineFirewallRule.chain == chain)
            .order_by(MachineFirewallRule.order.desc())
            .limit(1)
        )
        last_rule = result.scalar_one_or_none()
        max_order = last_rule.order if last_rule else -1
        
        rule = MachineFirewallRule(
            chain=chain,
            action=rule_data.get("action", "ACCEPT"),
            protocol=rule_data.get("protocol"),
            source=rule_data.get("source"),
            destination=rule_data.get("destination"),
            port=rule_data.get("port"),
            in_interface=rule_data.get("in_interface"),
            out_interface=rule_data.get("out_interface"),
            state=rule_data.get("state"),
            limit_rate=rule_data.get("limit_rate"),
            limit_burst=rule_data.get("limit_burst"),
            to_destination=rule_data.get("to_destination"),
            to_source=rule_data.get("to_source"),
            to_ports=rule_data.get("to_ports"),
            log_prefix=rule_data.get("log_prefix"),
            log_level=rule_data.get("log_level"),
            reject_with=rule_data.get("reject_with"),
            comment=rule_data.get("comment"),
            table_name=rule_data.get("table_name", "filter"),
            order=max_order + 1,
            enabled=rule_data.get("enabled", True)
        )
        
        session.add(rule)
        await session.flush()
        await session.refresh(rule)
        
        # Apply rules
        await self.apply_rules(session)
        
        logger.info(f"Created firewall rule {rule.id}")
        return rule
    
    async def update_rule(
        self,
        session: AsyncSession,
        rule_id: uuid.UUID,
        rule_data: Dict
    ) -> Optional[MachineFirewallRule]:
        """Update an existing firewall rule."""
        rule = await self.get_rule_by_id(session, rule_id)
        if not rule:
            return None
        
        # Update fields
        for key, value in rule_data.items():
            if hasattr(rule, key) and value is not None:
                setattr(rule, key, value)
        
        rule.updated_at = datetime.utcnow()
        session.add(rule)
        await session.flush()
        await session.refresh(rule)
        
        # Apply rules
        await self.apply_rules(session)
        
        logger.info(f"Updated firewall rule {rule.id}")
        return rule
    
    async def delete_rule(
        self,
        session: AsyncSession,
        rule_id: uuid.UUID
    ) -> bool:
        """Delete a firewall rule."""
        rule = await self.get_rule_by_id(session, rule_id)
        if not rule:
            return False
        
        chain = rule.chain
        await session.delete(rule)
        await session.flush()
        
        # Reorder remaining rules in chain
        result = await session.execute(
            select(MachineFirewallRule)
            .where(MachineFirewallRule.chain == chain)
            .order_by(MachineFirewallRule.order)
        )
        rules = result.scalars().all()
        
        for i, r in enumerate(rules):
            r.order = i
            session.add(r)
        
        # Apply rules
        return await self.apply_rules(session)
        
    async def delete_all_rules(self, session: AsyncSession) -> bool:
        """
        Delete ALL firewall rules.
        Used for full config restore/replace.
        """
        await session.execute(delete(MachineFirewallRule))
        await session.flush()
        
        # Apply (clear) rules
        await self.apply_rules(session)
        
        logger.info("Deleted ALL firewall rules")
        return True

    
    async def reorder_rules(
        self,
        session: AsyncSession,
        orders: List[Dict]
    ) -> bool:
        """
        Update rule ordering.
        
        Args:
            orders: List of {"id": str, "order": int}
        """
        for item in orders:
            rule_id = uuid.UUID(item["id"]) if isinstance(item["id"], str) else item["id"]
            await session.execute(
                update(MachineFirewallRule)
                .where(MachineFirewallRule.id == rule_id)
                .values(order=item["order"], updated_at=datetime.utcnow())
            )
        
        await session.flush()
        
        # Apply rules
        await self.apply_rules(session)
        
        return True
    
    async def apply_rules(self, session: AsyncSession) -> bool:
        """
        Apply all rules from database to iptables.
        
        1. Flush core MADMIN chains
        2. Add enabled rules in order
        """
        success = True
        
        # Flush all core MADMIN chains across all tables
        for table, chains in iptables.CHAIN_MAP.items():
            for chain_name in chains.values():
                if not iptables.flush_chain(chain_name, table):
                    logger.warning(f"Failed to flush chain {chain_name} in table {table}")
                    success = False
        
        # Get all enabled rules ordered by chain and order
        result = await session.execute(
            select(MachineFirewallRule)
            .where(MachineFirewallRule.enabled == True)
            .order_by(MachineFirewallRule.chain, MachineFirewallRule.order)
        )
        rules = result.scalars().all()
        
        # Apply each rule
        for rule in rules:
            # Get the MADMIN chain for this rule's table and chain
            target_chain = iptables.get_madmin_chain(rule.table_name, rule.chain)
            if not target_chain:
                logger.warning(f"Unknown chain {rule.chain} in table {rule.table_name} for rule {rule.id}")
                continue
            
            if not iptables.add_rule(
                table=rule.table_name,
                chain=target_chain,
                action=rule.action,
                protocol=rule.protocol,
                source=rule.source,
                destination=rule.destination,
                port=rule.port,
                in_interface=rule.in_interface,
                out_interface=rule.out_interface,
                state=rule.state,
                comment=f"ID_{rule.id}",
                limit_rate=rule.limit_rate,
                limit_burst=rule.limit_burst,
                to_destination=rule.to_destination,
                to_source=rule.to_source,
                to_ports=rule.to_ports,
                log_prefix=rule.log_prefix,
                log_level=rule.log_level,
                reject_with=rule.reject_with
            ):
                logger.error(f"Failed to apply rule {rule.id}")
                success = False
        
        if success:
            logger.info(f"Applied {len(rules)} firewall rules")
        
        return success


# Singleton instance
firewall_orchestrator = FirewallOrchestrator()
