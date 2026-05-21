"""
MADMIN Firewall Orchestrator

High-level firewall management that coordinates:
- Core MADMIN chains (MADMIN_INPUT, MADMIN_OUTPUT, MADMIN_FORWARD)
- Module chains with priority-based ordering
- Rule application from database

Backend is pluggable via FIREWALL_BACKEND env var (iptables | nftables).
"""
import asyncio
import logging
from typing import List, Dict, Optional, Tuple
from datetime import datetime
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update, delete
import uuid

from .models import MachineFirewallRule, ModuleChain
from .base import FirewallBackend

logger = logging.getLogger(__name__)


def _create_backend() -> FirewallBackend:
    """Factory: returns the configured FirewallBackend instance."""
    from config import get_settings
    backend_name = getattr(get_settings(), "firewall_backend", "iptables").lower()
    if backend_name == "nftables":
        from .nftables import NftablesBackend
        return NftablesBackend()
    from .iptables import IptablesBackend
    return IptablesBackend()


class FirewallOrchestrator:
    """
    Orchestrates firewall chain management and rule application.

    Provides a high-level interface for:
    - Managing core chains
    - Registering/unregistering module chains
    - CRUD operations on firewall rules
    - Applying rules from database
    """

    def __init__(self, backend: Optional[FirewallBackend] = None):
        self._initialized = False
        self._backend: FirewallBackend = backend or _create_backend()

    async def initialize(self) -> bool:
        """
        Initialize core firewall chains.
        Should be called on application startup.
        """
        success = self._backend.initialize_core_chains()
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
            table_name: iptables-compatible table name (filter/nat/mangle/raw)

        Returns:
            Created ModuleChain or None on failure
        """
        result = await session.execute(
            select(ModuleChain).where(ModuleChain.chain_name == chain_name)
        )
        existing = result.scalar_one_or_none()

        if existing:
            if (existing.table_name != table_name or
                    existing.parent_chain != parent_chain or
                    existing.priority != priority):
                existing.table_name = table_name
                existing.parent_chain = parent_chain
                existing.priority = priority
                session.add(existing)
                await session.flush()
                logger.info(f"Updated module chain {chain_name} configuration")

            if not self._backend.create_chain(chain_name, table_name):
                logger.error(f"Failed to ensure chain {chain_name} exists")
        else:
            if not self._backend.create_or_flush_chain(chain_name, table_name):
                logger.error(f"Failed to create chain {chain_name}")
                return None

            chain = ModuleChain(
                module_id=module_id,
                chain_name=chain_name,
                parent_chain=parent_chain,
                priority=priority,
                table_name=table_name
            )
            session.add(chain)
            await session.flush()

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
        Removes the chain from the firewall backend and database.
        """
        result = await session.execute(
            select(ModuleChain).where(ModuleChain.chain_name == chain_name)
        )
        chain = result.scalar_one_or_none()

        if not chain:
            return False

        parent_chain = chain.parent_chain
        table_name = chain.table_name

        self._backend.remove_jump_rule(parent_chain, chain_name, table_name)
        self._backend.delete_chain(chain_name, table_name)

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
        Atomically rebuild jump rules for a parent chain based on priorities.

        Order: Module chains first (by priority) → Core MADMIN chain last.
        """
        result = await session.execute(
            select(ModuleChain)
            .where(ModuleChain.parent_chain == parent_chain)
            .where(ModuleChain.table_name == table_name)
            .order_by(ModuleChain.priority)
        )
        module_chains = result.scalars().all()

        core_chain = self._backend.get_madmin_chain(table_name, parent_chain)

        target_chains = []

        if parent_chain == "INPUT" and table_name == "filter":
            for gw_chain in (
                self._backend.gw_excepts_chain,
                self._backend.gw_protect_chain,
            ):
                if self._backend.chain_exists(gw_chain, table_name):
                    target_chains.append(gw_chain)

        for mc in module_chains:
            if not self._backend.chain_exists(mc.chain_name, table_name):
                logger.debug(
                    f"Skipping jump to {mc.chain_name}: chain not yet created"
                )
                continue
            target_chains.append(mc.chain_name)

        if core_chain and self._backend.chain_exists(core_chain, table_name):
            target_chains.append(core_chain)

        if not target_chains:
            logger.warning(
                f"No target chains to rebuild for {parent_chain} ({table_name})"
            )
            return

        if not self._backend.restore_parent_chain_jumps(
            table_name, parent_chain, target_chains
        ):
            logger.error(
                f"Failed to atomically rebuild jumps for {parent_chain} ({table_name})"
            )

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
        result = await session.execute(
            select(MachineFirewallRule).where(MachineFirewallRule.id == rule_id)
        )
        return result.scalar_one_or_none()

    async def create_rule(
        self,
        session: AsyncSession,
        rule_data: Dict
    ) -> MachineFirewallRule:
        """Create a new firewall rule (appends to end of chain)."""
        chain = rule_data.get("chain", "INPUT")

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

        await self.apply_rules(session)

        logger.info(f"Created firewall rule {rule.id}")
        return rule

    async def update_rule(
        self,
        session: AsyncSession,
        rule_id: uuid.UUID,
        rule_data: Dict
    ) -> Optional[MachineFirewallRule]:
        rule = await self.get_rule_by_id(session, rule_id)
        if not rule:
            return None

        for key, value in rule_data.items():
            if hasattr(rule, key):
                setattr(rule, key, value)

        rule.updated_at = datetime.utcnow()
        session.add(rule)
        await session.flush()
        await session.refresh(rule)

        await self.apply_rules(session)

        logger.info(f"Updated firewall rule {rule.id}")
        return rule

    async def delete_rule(
        self,
        session: AsyncSession,
        rule_id: uuid.UUID
    ) -> bool:
        rule = await self.get_rule_by_id(session, rule_id)
        if not rule:
            return False

        chain = rule.chain
        await session.delete(rule)
        await session.flush()

        result = await session.execute(
            select(MachineFirewallRule)
            .where(MachineFirewallRule.chain == chain)
            .order_by(MachineFirewallRule.order)
        )
        rules = result.scalars().all()

        for i, r in enumerate(rules):
            r.order = i
            session.add(r)

        return await self.apply_rules(session)

    async def delete_all_rules(self, session: AsyncSession) -> bool:
        """Delete ALL firewall rules (used for full config restore/replace)."""
        await session.execute(delete(MachineFirewallRule))
        await session.flush()
        await self.apply_rules(session)
        logger.info("Deleted ALL firewall rules")
        return True

    async def reorder_rules(
        self,
        session: AsyncSession,
        orders: List[Dict]
    ) -> bool:
        for item in orders:
            rule_id = uuid.UUID(item["id"]) if isinstance(item["id"], str) else item["id"]
            await session.execute(
                update(MachineFirewallRule)
                .where(MachineFirewallRule.id == rule_id)
                .values(order=item["order"], updated_at=datetime.utcnow())
            )

        await session.flush()
        await self.apply_rules(session)
        return True

    async def _get_lan_interfaces(self) -> List[Tuple[str, List[str]]]:
        """Return (iface_name, [ip, ...]) for all physical LAN interfaces."""
        from core.network.service import NetworkService
        from core.network.utils import get_default_interface

        wan_iface = get_default_interface()
        loop = asyncio.get_event_loop()
        all_ifaces = await loop.run_in_executor(None, NetworkService().get_interfaces)

        result = []
        for iface in all_ifaces:
            name = iface.get("name", "")
            if not name or name == wan_iface or name == "lo":
                continue
            ips = iface.get("addresses", [])
            if ips:
                result.append((name, ips))
        return result

    async def _rebuild_gateway_sets(
        self,
        lan_interfaces: List[Tuple[str, List[str]]]
    ) -> None:
        """Create or refresh per-interface sets for gateway protection."""
        for iface_name, ips in lan_interfaces:
            setname = self._backend.set_name_for_iface(iface_name)
            if self._backend.set_exists(setname):
                self._backend.set_flush(setname)
            else:
                self._backend.set_create(setname)
            for ip in ips:
                self._backend.set_add(setname, ip)

    async def apply_rules(self, session: AsyncSession) -> bool:
        """
        Apply all rules from database to the firewall backend atomically.

        Uses backend.restore_chains() for atomic flush + repopulate per table.
        Also rebuilds gateway protection sets and chain jump ordering.
        """
        success = True

        lan_interfaces = await self._get_lan_interfaces()
        await self._rebuild_gateway_sets(lan_interfaces)

        result = await session.execute(
            select(MachineFirewallRule)
            .where(MachineFirewallRule.enabled == True)
            .order_by(MachineFirewallRule.chain, MachineFirewallRule.order)
        )
        rules = result.scalars().all()

        chain_rules: Dict[str, Dict[str, List[str]]] = {}
        for table, chains in self._backend.chain_map.items():
            chain_rules[table] = {}
            for parent_chain, madmin_chain in chains.items():
                lines: List[str] = []
                if table == "filter" and parent_chain in ("INPUT", "FORWARD"):
                    lines.append(
                        self._backend.rule_to_restore_line(
                            madmin_chain,
                            _EstablishedRelatedRule(madmin_chain)
                        )
                    )
                chain_rules[table][madmin_chain] = lines

        protect_lines = self._backend.build_gateway_protect_lines(lan_interfaces)
        chain_rules["filter"][self._backend.gw_protect_chain] = protect_lines
        chain_rules["filter"][self._backend.gw_excepts_chain] = []

        for rule in rules:
            madmin_chain = self._backend.get_madmin_chain(rule.table_name, rule.chain)
            if not madmin_chain:
                logger.warning(
                    f"Unknown chain {rule.chain} in table {rule.table_name} "
                    f"for rule {rule.id}"
                )
                continue
            chain_rules[rule.table_name][madmin_chain].append(
                self._backend.rule_to_restore_line(madmin_chain, rule)
            )

        for table, chains in chain_rules.items():
            if not self._backend.restore_chains(table, chains):
                logger.error(f"Failed to atomically restore table {table}")
                success = False

        await self.rebuild_chain_jumps(session, "INPUT", "filter")

        if success:
            logger.info(
                f"Atomically applied {len(rules)} firewall rules across "
                f"{len(chain_rules)} tables "
                f"(gateway protect: {len(lan_interfaces)} LAN interfaces)"
            )

        return success


class _EstablishedRelatedRule:
    """
    Minimal rule-like object used to inject the built-in ESTABLISHED/RELATED
    rule into INPUT and FORWARD chains without storing it in the DB.
    """
    def __init__(self, chain: str):
        self.chain = chain
        self.action = "ACCEPT"
        self.protocol = None
        self.source = None
        self.destination = None
        self.port = None
        self.in_interface = None
        self.out_interface = None
        self.state = "ESTABLISHED,RELATED"
        self.limit_rate = None
        self.limit_burst = None
        self.to_destination = None
        self.to_source = None
        self.to_ports = None
        self.log_prefix = None
        self.log_level = None
        self.reject_with = None
        self.comment = "MADMIN_BUILTIN_ESTABLISHED"
        self.table_name = "filter"
        self.id = "builtin"


# Singleton instance
firewall_orchestrator = FirewallOrchestrator()
