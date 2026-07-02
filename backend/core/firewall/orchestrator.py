"""
MADMIN Firewall Orchestrator

High-level firewall management that coordinates:
- Core MADMIN chains (MADMIN_INPUT, MADMIN_OUTPUT, MADMIN_FORWARD)
- Module chains with priority-based ordering
- Rule application from database
"""
import asyncio
import logging
from typing import List, Dict, Optional, Tuple
from datetime import datetime
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update, delete
import uuid

import json

from .models import (
    MachineFirewallRule, ModuleChain,
    AddressObject, AddressGroup, AddressGroupMember, FirewallRuleAddress,
)
from . import iptables, addresses

logger = logging.getLogger(__name__)

# Comment marking the always-last implicit deny appended to MADMIN_FORWARD by
# apply_rules(). The FORWARD catch-all is no longer a DB rule: new policies are
# always reachable by construction, FortiGate-style.
IMPLICIT_DENY_COMMENT = "MADMIN_IMPLICIT_DENY"


def dnat_forward_fields(rule) -> Dict[str, Optional[str]]:
    """
    Compute the FORWARD ACCEPT match for a DNAT rule's companion forward.

    The DNAT rewrites the destination to an internal host; the forwarded packet
    must be accepted toward that translated destination. Refined by the DNAT's
    incoming interface and source when present. Shared by apply_rules (iptables
    generation) and the API listing (read-only synthetic row) so they stay in sync.
    """
    dest_ip, dest_port = iptables.split_ip_port(rule.to_destination)
    return {
        "protocol": rule.protocol,
        "source": rule.source,
        "destination": dest_ip,
        "port": dest_port or rule.port,
        "in_interface": rule.in_interface,
    }


def policy_nat_fields(rule) -> Dict[str, Optional[str]]:
    """
    Compute the POSTROUTING MASQUERADE match for a forward policy's NAT companion.

    A filter/FORWARD policy with policy_nat=True owns its outbound masquerade. The
    companion is scoped to the policy's exact flow (source/destination/protocol/
    port and out_interface) so it never masquerades traffic belonging to other
    non-NAT policies. in_interface is deliberately excluded: -i does not exist in
    POSTROUTING and would make iptables-restore reject the whole nat table.
    Shared by apply_rules (iptables generation) and the API listing (read-only
    synthetic row) so they stay in sync.
    """
    return {
        "protocol": rule.protocol,
        "port": rule.port,
        "source": rule.source,
        "destination": rule.destination,
        "out_interface": rule.out_interface,
    }


def _restore_line(madmin_chain: str, rule, eff_map: Dict) -> str:
    """Restore-format line for a rule, honoring resolved address-set tokens."""
    eff = eff_map.get(rule.id)
    if eff:
        eff_src, eff_dst = eff
        return iptables.rule_to_restore_line(
            madmin_chain, rule,
            source=eff_src if eff_src is not None else rule.source,
            destination=eff_dst if eff_dst is not None else rule.destination,
        )
    return iptables.rule_to_restore_line(madmin_chain, rule)


def _build_forward_layout(
    forward_rules: List,
    eff_map: Dict,
) -> Tuple[List[str], Dict[str, List[str]]]:
    """
    Build the MADMIN_FORWARD body with per-interface-pair subchains.

    Rules with both interfaces set are grouped into a per-pair subchain,
    dispatched by a single `-i X -o Y -j MFWD_*` jump emitted at the position
    of the pair's first rule; partial/wildcard rules stay inline. Evaluation is
    therefore grouped by pair at the group's first-occurrence position — the
    same grouping the Standard UI displays. A packet matching no rule in its
    pair subchain falls through (implicit RETURN) and continues in
    MADMIN_FORWARD toward later wildcard rules, DNAT companions and the
    implicit deny.

    Returns (forward_lines, {subchain_name: [lines]}).
    """
    lines: List[str] = []
    subchains: Dict[str, List[str]] = {}
    for rule in forward_rules:
        if rule.in_interface and rule.out_interface:
            name = iptables.forward_subchain_name(rule.in_interface, rule.out_interface)
            if name not in subchains:
                subchains[name] = []
                lines.append(
                    f"-A {iptables.MADMIN_FORWARD_CHAIN}"
                    f" -i {rule.in_interface} -o {rule.out_interface} -j {name}"
                )
            subchains[name].append(_restore_line(name, rule, eff_map))
        else:
            lines.append(_restore_line(iptables.MADMIN_FORWARD_CHAIN, rule, eff_map))
    return lines, subchains


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
        Atomically rebuild jump rules for a parent chain based on priorities.

        Order: Module chains first (by priority) → Core MADMIN chain last (default policy)

        Uses iptables-restore --noflush to flush and re-add all jumps as a single
        kernel transaction — no window where the parent chain has no jump to MADMIN.
        """
        # Get all module chains for this parent, ordered by priority
        result = await session.execute(
            select(ModuleChain)
            .where(ModuleChain.parent_chain == parent_chain)
            .where(ModuleChain.table_name == table_name)
            .order_by(ModuleChain.priority)
        )
        module_chains = result.scalars().all()

        core_chain = iptables.get_madmin_chain(table_name, parent_chain)

        # Build ordered target list: verify chains exist before building restore block
        # (all checks happen before touching iptables — old jumps remain active)
        target_chains = []

        # For INPUT/filter: prepend gateway chains before any module chain.
        # MADMIN_GW_EXCEPTS (priority 0) runs first to allow admin overrides,
        # MADMIN_GW_PROTECT (priority 1) runs second to enforce LAN isolation.
        if parent_chain == "INPUT" and table_name == "filter":
            for gw_chain in (
                iptables.MADMIN_GW_EXCEPTS_CHAIN,
                iptables.MADMIN_GW_PROTECT_CHAIN,
            ):
                if iptables.chain_exists(gw_chain, table_name):
                    target_chains.append(gw_chain)

        for mc in module_chains:
            if not iptables.chain_exists(mc.chain_name, table_name):
                logger.debug(f"Skipping jump to {mc.chain_name}: chain not yet created in iptables")
                continue
            target_chains.append(mc.chain_name)
        if core_chain and iptables.chain_exists(core_chain, table_name):
            target_chains.append(core_chain)

        if not target_chains:
            logger.warning(f"No target chains to rebuild for {parent_chain} ({table_name})")
            return

        # Atomically flush parent_chain and re-add all jumps in one kernel transaction
        if not iptables.restore_parent_chain_jumps(table_name, parent_chain, target_chains):
            logger.error(f"Failed to atomically rebuild jumps for {parent_chain} ({table_name})")
    
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

    async def get_enabled_dnat_rules(
        self,
        session: AsyncSession
    ) -> List[MachineFirewallRule]:
        """Get enabled DNAT rules — source of the auto-generated FORWARD companions."""
        result = await session.execute(
            select(MachineFirewallRule)
            .where(MachineFirewallRule.table_name == "nat")
            .where(MachineFirewallRule.action == "DNAT")
            .where(MachineFirewallRule.enabled == True)
            .where(MachineFirewallRule.to_destination.is_not(None))
            .order_by(MachineFirewallRule.order)
        )
        return result.scalars().all()

    async def get_enabled_policy_nat_rules(
        self,
        session: AsyncSession
    ) -> List[MachineFirewallRule]:
        """Get enabled forward policies with policy_nat — source of the POSTROUTING masquerade companions."""
        result = await session.execute(
            select(MachineFirewallRule)
            .where(MachineFirewallRule.table_name == "filter")
            .where(MachineFirewallRule.chain == "FORWARD")
            .where(MachineFirewallRule.policy_nat == True)
            .where(MachineFirewallRule.enabled == True)
            .order_by(MachineFirewallRule.order)
        )
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

    async def _set_rule_addresses(
        self,
        session: AsyncSession,
        rule_id: uuid.UUID,
        refs: Optional[List[Dict]],
        direction: str,
    ) -> bool:
        """
        Replace the object/group references for a rule direction.

        `refs` is a list of {"object_id"|"group_id"} dicts (None = leave as is).
        Returns True if at least one non-empty reference was written (so the
        caller can null the literal source/destination column for that direction).
        """
        if refs is None:
            return False
        await session.execute(
            delete(FirewallRuleAddress).where(
                FirewallRuleAddress.rule_id == rule_id,
                FirewallRuleAddress.direction == direction,
            )
        )
        wrote = False
        for i, ref in enumerate(refs):
            obj_id = ref.get("object_id")
            grp_id = ref.get("group_id")
            if not obj_id and not grp_id:
                continue
            session.add(FirewallRuleAddress(
                rule_id=rule_id,
                direction=direction,
                object_id=uuid.UUID(obj_id) if obj_id else None,
                group_id=uuid.UUID(grp_id) if grp_id else None,
                order=i,
            ))
            wrote = True
        await session.flush()
        return wrote
    
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
        table_name = rule_data.get("table_name", "filter")

        # Get max order for this (table, chain) — chains like FORWARD exist in
        # multiple tables and must not share numbering
        result = await session.execute(
            select(MachineFirewallRule)
            .where(MachineFirewallRule.chain == chain)
            .where(MachineFirewallRule.table_name == table_name)
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
            table_name=table_name,
            order=max_order + 1,
            enabled=rule_data.get("enabled", True),
            policy_nat=rule_data.get("policy_nat", False)
        )
        
        session.add(rule)
        await session.flush()
        await session.refresh(rule)

        # Object/group references (multi-select). When present they take
        # precedence over the literal source/destination column.
        if await self._set_rule_addresses(session, rule.id, rule_data.get("source_refs"), "source"):
            rule.source = None
        if await self._set_rule_addresses(session, rule.id, rule_data.get("destination_refs"), "destination"):
            rule.destination = None
        session.add(rule)
        await session.flush()

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
        
        # Update fields (source_refs/destination_refs are not model columns and
        # are handled separately below)
        for key, value in rule_data.items():
            if hasattr(rule, key):
                setattr(rule, key, value)

        rule.updated_at = datetime.utcnow()
        session.add(rule)
        await session.flush()

        # Object/group references: replace when explicitly provided
        if "source_refs" in rule_data:
            if await self._set_rule_addresses(session, rule.id, rule_data.get("source_refs"), "source"):
                rule.source = None
        if "destination_refs" in rule_data:
            if await self._set_rule_addresses(session, rule.id, rule_data.get("destination_refs"), "destination"):
                rule.destination = None
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
        table_name = rule.table_name
        # Remove the rule's object/group references first (no DB-level cascade)
        await session.execute(
            delete(FirewallRuleAddress).where(FirewallRuleAddress.rule_id == rule_id)
        )
        await session.delete(rule)
        await session.flush()

        # Reorder remaining rules in the same (table, chain)
        result = await session.execute(
            select(MachineFirewallRule)
            .where(MachineFirewallRule.chain == chain)
            .where(MachineFirewallRule.table_name == table_name)
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
        await session.execute(delete(FirewallRuleAddress))
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
    
    async def _get_lan_interfaces(self) -> List[Tuple[str, List[str]]]:
        """
        Return list of (iface_name, [ip, ...]) for all physical LAN interfaces.
        Excludes WAN (default route interface) and loopback.
        NetworkService.get_interfaces() is synchronous — runs in executor.
        """
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

    async def _rebuild_gateway_ipsets(
        self,
        lan_interfaces: List[Tuple[str, List[str]]]
    ) -> None:
        """
        Create or refresh ipsets MADMIN_GW_<IFACE> for each LAN interface.
        Each ipset contains all IPs assigned to that interface.
        Called within apply_rules() before restore_chains().
        """
        for iface_name, ips in lan_interfaces:
            setname = iptables.ipset_name_for_iface(iface_name)
            if iptables.ipset_exists(setname):
                iptables.ipset_flush(setname)
            else:
                iptables.ipset_create(setname)
            for ip in ips:
                iptables.ipset_add(setname, ip)

    async def _build_address_plan(self, session: AsyncSession, rules):
        """
        Assemble the ipset materialization plan and resolve each rule direction's
        address references into an effective 'set:<ipset>' token.

        Every address object and group is materialized for as long as it exists
        (independent of rule references), so its set is visible/populated even
        before any policy uses it. Per-rule aggregate list:sets are added only
        for directions with >1 reference.

        Returns (eff_map, plan):
          eff_map: {rule_id: (eff_source|None, eff_destination|None)}
          plan:    {"objects": {ref_key: {...}}, "groups": {...}, "rule_sets": {...}}
        """
        # --- All objects and groups (so every set is materialized) ---
        ores = await session.execute(select(AddressObject))
        obj_by_id: Dict[uuid.UUID, AddressObject] = {o.id: o for o in ores.scalars().all()}

        gres = await session.execute(select(AddressGroup))
        group_objs: Dict[uuid.UUID, AddressGroup] = {g.id: g for g in gres.scalars().all()}

        group_members: Dict[uuid.UUID, List[uuid.UUID]] = {}
        if group_objs:
            mres = await session.execute(select(AddressGroupMember))
            for m in mres.scalars().all():
                if m.member_object_id:
                    group_members.setdefault(m.group_id, []).append(m.member_object_id)

        def _obj_dict(o: AddressObject) -> dict:
            ips = None
            if o.resolved_ips:
                try:
                    ips = json.loads(o.resolved_ips)
                except Exception:
                    ips = None
            return {"ref_key": o.ref_key, "type": o.type, "value": o.value,
                    "enabled": o.enabled, "resolved_ips": ips}

        plan_objects = {o.ref_key: _obj_dict(o) for o in obj_by_id.values()}
        plan_groups = {
            g.ref_key: {
                "enabled": g.enabled,
                "member_object_keys": [
                    obj_by_id[mid].ref_key for mid in group_members.get(gid, [])
                    if mid in obj_by_id
                ],
            }
            for gid, g in group_objs.items()
        }
        plan_rule_sets: Dict[str, list] = {}
        eff: Dict[uuid.UUID, list] = {}

        # --- Effective per-direction tokens from rule references ---
        rule_ids = [r.id for r in rules]
        if rule_ids:
            ra_result = await session.execute(
                select(FirewallRuleAddress)
                .where(FirewallRuleAddress.rule_id.in_(rule_ids))
                .order_by(FirewallRuleAddress.order)
            )
            by_dir: Dict[tuple, list] = {}
            for ra in ra_result.scalars().all():
                by_dir.setdefault((ra.rule_id, ra.direction), []).append(ra)

            for (rid, direction), ra_list in by_dir.items():
                valid = [
                    ra for ra in ra_list
                    if (ra.object_id in obj_by_id) or (ra.group_id in group_objs)
                ]
                if not valid:
                    continue
                if len(valid) == 1:
                    ra = valid[0]
                    if ra.object_id:
                        set_name = addresses.object_leaf_set_name(obj_by_id[ra.object_id].ref_key)
                    else:
                        set_name = addresses.group_set_name(group_objs[ra.group_id].ref_key)
                else:
                    # per-rule aggregate: flatten everything to leaf object sets
                    set_name = addresses.rule_set_name(rid, direction)
                    leaf_names, seen = [], set()
                    for ra in valid:
                        member_ids = [ra.object_id] if ra.object_id else group_members.get(ra.group_id, [])
                        for mid in member_ids:
                            if mid in obj_by_id:
                                nm = addresses.object_leaf_set_name(obj_by_id[mid].ref_key)
                                if nm not in seen:
                                    seen.add(nm)
                                    leaf_names.append(nm)
                    plan_rule_sets[set_name] = leaf_names
                slot = eff.setdefault(rid, [None, None])
                slot[0 if direction == "source" else 1] = f"set:{set_name}"

        eff_map = {rid: (s, d) for rid, (s, d) in eff.items()}
        plan = {"objects": plan_objects, "groups": plan_groups, "rule_sets": plan_rule_sets}
        return eff_map, plan

    async def apply_rules(self, session: AsyncSession) -> bool:
        """
        Apply all rules from database to iptables atomically.

        Uses a single iptables-restore --noflush invocation to flush and
        repopulate every MADMIN core chain (plus the per-pair FORWARD
        subchains) — no window where chains are empty and traffic is
        unprotected. Raises IptablesError on failure; the previous ruleset
        stays in place.

        Also rebuilds MADMIN_GW_PROTECT from current network topology (ipset-based
        cross-gateway isolation) and MADMIN_GW_EXCEPTS from DB rules.
        """
        # --- Gateway protection: resolve topology and rebuild ipsets ---
        lan_interfaces = await self._get_lan_interfaces()
        await self._rebuild_gateway_ipsets(lan_interfaces)

        # --- Get all enabled DB rules ordered by chain and order ---
        result = await session.execute(
            select(MachineFirewallRule)
            .where(MachineFirewallRule.enabled == True)
            .order_by(MachineFirewallRule.chain, MachineFirewallRule.order)
        )
        rules = result.scalars().all()

        # --- Address objects/groups: resolve each rule direction's references
        #     to an effective "set:<ipset>" token and materialize the backing
        #     ipsets. ---
        # 1) ensure_sets_exist creates the (possibly empty) sets synchronously so
        #    the --match-set references in restore_chains() are always valid.
        # 2) sync_referenced resolves/builds the set contents off the request
        #    path in a worker thread (network for fqdn/geo), so create/update
        #    returns immediately; the set matches nothing until it finishes.
        eff_map, addr_plan = await self._build_address_plan(session, rules)
        addresses.ensure_sets_exist(addr_plan)
        asyncio.create_task(asyncio.to_thread(addresses.sync_referenced, addr_plan))

        # Build per-table chain rules: {table: {madmin_chain: [restore-format lines]}}
        chain_rules: Dict[str, Dict[str, List[str]]] = {}
        for table, chains in iptables.CHAIN_MAP.items():
            chain_rules[table] = {}
            for parent_chain, madmin_chain in chains.items():
                lines: List[str] = []
                # Built-in ESTABLISHED/RELATED as first rule for INPUT and FORWARD
                if table == "filter" and parent_chain in ("INPUT", "FORWARD"):
                    lines.append(
                        f"-A {madmin_chain} -m conntrack --ctstate ESTABLISHED,RELATED"
                        f" -j ACCEPT -m comment --comment MADMIN_BUILTIN_ESTABLISHED"
                    )
                chain_rules[table][madmin_chain] = lines

        # --- Inject auto-generated MADMIN_GW_PROTECT content ---
        protect_lines = iptables.build_gateway_protect_lines(lan_interfaces)
        chain_rules["filter"][iptables.MADMIN_GW_PROTECT_CHAIN] = protect_lines

        # MADMIN_GW_EXCEPTS starts empty (populated below by DB rules with chain=GW_EXCEPTIONS)
        chain_rules["filter"][iptables.MADMIN_GW_EXCEPTS_CHAIN] = []

        # --- Assign DB rules to their respective MADMIN chains ---
        # filter/FORWARD is handled by the pair-subchain layout builder below.
        for rule in rules:
            if rule.table_name == "filter" and rule.chain == "FORWARD":
                continue
            madmin_chain = iptables.get_madmin_chain(rule.table_name, rule.chain)
            if not madmin_chain:
                # The API rejects these since table/chain validation; legacy bad
                # rows must not break the whole apply.
                logger.error(f"Unknown chain {rule.chain} in table {rule.table_name} for rule {rule.id} — skipped")
                continue
            chain_rules[rule.table_name][madmin_chain].append(_restore_line(madmin_chain, rule, eff_map))

        # --- FORWARD layout: per-interface-pair subchains + inline wildcard rules ---
        forward_rules = [r for r in rules if r.table_name == "filter" and r.chain == "FORWARD"]
        forward_lines, subchain_map = _build_forward_layout(forward_rules, eff_map)
        chain_rules["filter"][iptables.MADMIN_FORWARD_CHAIN].extend(forward_lines)
        chain_rules["filter"].update(subchain_map)

        # --- Auto-generate FORWARD ACCEPT for DNAT rules ---
        # A DNAT in PREROUTING/OUTPUT rewrites the destination to an internal host;
        # the translated packet then traverses FORWARD and would hit the implicit
        # deny. Emit a companion ACCEPT toward the translated destination, refined
        # by the DNAT's incoming interface and source when present, appended AFTER
        # the user policies so an explicit deny can block port-forwarded traffic.
        auto_forward_lines: List[str] = []
        for rule in rules:
            if rule.table_name != "nat" or rule.action != "DNAT" or not rule.to_destination:
                continue
            fields = dnat_forward_fields(rule)
            eff = eff_map.get(rule.id)
            if eff and eff[0] is not None:
                fields["source"] = eff[0]   # honor object/group source refs
            auto_forward_lines.append(
                " ".join(iptables.build_rule_args(
                    chain=iptables.MADMIN_FORWARD_CHAIN,
                    action="ACCEPT",
                    comment=f"MADMIN_AUTO_DNAT_{rule.id}",
                    operation="-A",
                    **fields,
                ))
            )
        if auto_forward_lines:
            chain_rules["filter"][iptables.MADMIN_FORWARD_CHAIN].extend(auto_forward_lines)

        # --- Auto-generate POSTROUTING MASQUERADE for policies with policy_nat ---
        # A filter/FORWARD policy can own its outbound NAT (navigation masquerade).
        # Emit a companion MASQUERADE in POSTROUTING matching the same flow, so the
        # policy is the single source of truth (mirrors the DNAT->FORWARD companion).
        auto_nat_lines: List[str] = []
        for rule in rules:
            if rule.table_name != "filter" or rule.chain != "FORWARD" or not rule.policy_nat:
                continue
            fields = policy_nat_fields(rule)
            eff = eff_map.get(rule.id)
            if eff:
                if eff[0] is not None:
                    fields["source"] = eff[0]        # honor object/group source refs
                if eff[1] is not None:
                    fields["destination"] = eff[1]   # honor object/group dest refs
            auto_nat_lines.append(
                " ".join(iptables.build_rule_args(
                    chain=iptables.MADMIN_POSTROUTING_NAT_CHAIN,
                    action="MASQUERADE",
                    comment=f"MADMIN_AUTO_NAT_{rule.id}",
                    operation="-A",
                    **fields,
                ))
            )
        if auto_nat_lines:
            chain_rules["nat"][iptables.MADMIN_POSTROUTING_NAT_CHAIN].extend(auto_nat_lines)

        # --- Implicit deny: always-last FORWARD drop (not a DB rule) ---
        chain_rules["filter"][iptables.MADMIN_FORWARD_CHAIN].append(
            f"-A {iptables.MADMIN_FORWARD_CHAIN}"
            f" -m comment --comment {IMPLICIT_DENY_COMMENT} -j DROP"
        )

        # --- Stale pair subchains (pairs no longer in use): flushed and deleted
        #     in the same restore transaction ---
        stale = sorted(set(iptables.list_forward_subchains()) - set(subchain_map))

        # --- Apply atomically: single iptables-restore across all tables ---
        try:
            iptables.restore_all(chain_rules, delete_chains={"filter": stale})
        except iptables.IptablesError:
            logger.error("Atomic firewall restore failed; previous ruleset left in place")
            raise

        # --- Rebuild parent-chain jump order for INPUT ---
        # Ensures MADMIN_GW_EXCEPTS → MADMIN_GW_PROTECT → MADMIN_INPUT are wired
        # in the correct order even when no module chain is registered for INPUT.
        await self.rebuild_chain_jumps(session, "INPUT", "filter")

        logger.info(
            f"Atomically applied {len(rules)} firewall rules across {len(chain_rules)} tables"
            f" ({len(subchain_map)} forward subchains, gateway protect: {len(lan_interfaces)} LAN interfaces)"
        )
        # Persist rules + ipsets so the fail-closed boot guard can restore a
        # self-consistent last-good ruleset after a reboot. Best-effort, off
        # the event loop. (Dynamic geo/fqdn sets may still be filling in via
        # sync_referenced; that's fine — madmin always rebuilds from the DB on
        # the next startup, this snapshot only covers the boot window.)
        asyncio.create_task(asyncio.to_thread(iptables.save_rules))

        return True

    async def resync_addresses(self, session: AsyncSession) -> bool:
        """
        Rebuild address-object/group/per-rule ipsets WITHOUT touching iptables
        chains. Used after address-object/group CRUD: the --match-set names
        referenced by rules are unchanged, only set membership/content changes,
        so a full apply_rules() (chain rebuild) is unnecessary.
        """
        result = await session.execute(
            select(MachineFirewallRule).where(MachineFirewallRule.enabled == True)
        )
        rules = result.scalars().all()
        _, plan = await self._build_address_plan(session, rules)
        addresses.ensure_sets_exist(plan)
        asyncio.create_task(asyncio.to_thread(addresses.sync_referenced, plan))
        return True


# Singleton instance
firewall_orchestrator = FirewallOrchestrator()
