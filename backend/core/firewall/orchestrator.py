"""
MADMIN Firewall Orchestrator

High-level firewall management that coordinates:
- Core MADMIN chains (MADMIN_INPUT, MADMIN_OUTPUT, MADMIN_FORWARD)
- Module chains with priority-based ordering
- Rule application from database
"""
import asyncio
import ipaddress
import logging
from typing import List, Dict, Optional, Tuple
from datetime import datetime
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update, delete, or_
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


def effective_to_destination(rule, obj_value: Optional[str] = None) -> Optional[str]:
    """
    The literal ip[:port] this DNAT rule actually rewrites to. When the rule
    references an address object (to_destination_object_id), obj_value is
    that object's resolved value — router.py only accepts /32 cidr objects
    here (a single host), never a range or wider CIDR: --to-destination
    rewrites to one address, and every companion below embeds the target as
    a plain -d match, which a range or /24-style CIDR can't be (iptables
    doesn't accept a range there, and a wider CIDR isn't a single rewrite
    target to begin with). Otherwise the rule's own literal to_destination
    column is used unchanged.

    Every apply-time and display-time consumer of a DNAT target — the
    restore line itself, the FORWARD/INPUT/hairpin companions, and the
    protected-port guard — must resolve through this (or receive its result
    via the `to_destination` kwarg the *_fields helpers below accept),
    never read rule.to_destination directly, so switching a rule between a
    literal and an object target can never leave one consumer stale.
    """
    if obj_value:
        base = obj_value[:-3] if obj_value.endswith("/32") else obj_value
        return f"{base}:{rule.to_destination_port}" if rule.to_destination_port else base
    return rule.to_destination


def dnat_forward_fields(rule, to_destination: Optional[str] = None) -> Dict[str, Optional[str]]:
    """
    Compute the FORWARD ACCEPT match for a DNAT rule's companion forward.

    The DNAT rewrites the destination to an internal host; the forwarded packet
    must be accepted toward that translated destination. Refined by the DNAT's
    incoming interface and source when present. Shared by apply_rules (iptables
    generation) and the API listing (read-only synthetic row) so they stay in sync.

    to_destination: pre-resolved via effective_to_destination() by the caller
    (falls back to the rule's literal column when the caller has nothing else
    to resolve, e.g. a plain literal-target rule).
    """
    dest_ip, dest_port = iptables.split_ip_port(to_destination if to_destination is not None else rule.to_destination)
    return {
        "protocol": rule.protocol,
        "source": rule.source,
        "destination": dest_ip,
        "port": dest_port or rule.port,
        "in_interface": rule.in_interface,
    }


def redirect_input_fields(rule) -> Dict[str, Optional[str]]:
    """
    Compute the INPUT ACCEPT match for a nat/PREROUTING REDIRECT companion.

    REDIRECT always delivers to the host itself, so the packet traverses INPUT
    (not FORWARD) after the rewrite — without a companion it dies on the
    default INPUT catch-all. Shared by apply_rules and the API listing so they
    stay in sync (dnat_forward_fields/policy_nat_fields pattern).
    """
    dport = rule.to_ports or rule.port
    # to_ports is validated as \d+(-\d+)? (a range) but --dport wants ':'.
    if dport and "-" in dport:
        dport = dport.replace("-", ":")
    return {
        "protocol": rule.protocol,
        "port": dport,
        "source": rule.source,
        "in_interface": rule.in_interface,
    }


def dnat_input_fields(rule, to_destination: Optional[str] = None) -> Dict[str, Optional[str]]:
    """
    Compute the INPUT ACCEPT match for a DNAT whose target is a local address.

    DNAT rewrites the destination before the routing decision, so by the time
    the packet reaches INPUT it already carries the translated (local)
    destination — matching -d dest_ip here is correct post-NAT state.

    to_destination: pre-resolved via effective_to_destination() by the caller.
    """
    dest_ip, dest_port = iptables.split_ip_port(to_destination if to_destination is not None else rule.to_destination)
    return {
        "protocol": rule.protocol,
        "port": dest_port or rule.port,
        "source": rule.source,
        "destination": dest_ip,
        "in_interface": rule.in_interface,
    }


def policy_nat_fields(rule) -> Dict[str, Optional[str]]:
    """
    Compute the effective fields for a forward policy's POSTROUTING NAT
    companion.

    A filter/FORWARD policy with policy_nat=True owns its outbound masquerade.
    The companion no longer matches by flow (protocol/port/source/destination):
    it matches by conntrack mark (see apply_rules' nat_marks and
    _connmark_restore_line), which is set on the connection by a CONNMARK line
    that shares the policy's exact match — so the masquerade can never fire for
    traffic accepted by a *different*, non-NAT policy, even one with an
    overlapping match (the old flow-based companion could leak this way).
    out_interface may be topologically defaulted at apply time when the policy
    doesn't set one (see apply_rules) — this function returns the rule's own
    value only; the caller resolves the fallback.
    Shared by apply_rules (iptables generation) and the API listing (read-only
    synthetic row) so they stay in sync.
    """
    return {
        "out_interface": rule.out_interface,
    }


def hairpin_masq_fields(rule, to_destination: Optional[str] = None) -> Dict[str, Optional[str]]:
    """
    Compute the POSTROUTING MASQUERADE match for a hairpin-NAT DNAT companion.

    Lets a LAN client reach a port forward via the WAN IP: without this, the
    internal server would reply to the LAN client directly (with its own IP),
    which the client's connection doesn't expect. Scoping (source subnet,
    -d/--dport) is topology-dependent and filled in by the caller — this only
    computes the destination-side match shared with apply_rules' hairpin DNAT
    line, so the two stay in sync the same way dnat_forward_fields/policy_nat_fields do.

    to_destination: pre-resolved via effective_to_destination() by the caller.
    """
    dest_ip, dest_port = iptables.split_ip_port(to_destination if to_destination is not None else rule.to_destination)
    return {
        "protocol": rule.protocol,
        "destination": dest_ip,
        "port": dest_port or rule.port,
    }


def _restore_line(madmin_chain: str, rule, eff_map: Dict, to_destination: Optional[str] = None) -> str:
    """Restore-format line for a rule, honoring resolved address-set tokens.

    to_destination: resolved DNAT target (see effective_to_destination),
    passed by apply_rules for DNAT rules with an object-based target; not
    used for any other rule (build_rule_args ignores it unless action=DNAT).
    """
    eff = eff_map.get(rule.id)
    if eff:
        eff_src, eff_dst = eff
        return iptables.rule_to_restore_line(
            madmin_chain, rule,
            source=eff_src if eff_src is not None else rule.source,
            destination=eff_dst if eff_dst is not None else rule.destination,
            to_destination=to_destination if to_destination is not None else rule.to_destination,
        )
    return iptables.rule_to_restore_line(
        madmin_chain, rule,
        to_destination=to_destination if to_destination is not None else rule.to_destination,
    )


def _connmark_restore_line(madmin_chain: str, rule, eff_map: Dict, mark: int) -> str:
    """
    Restore-format CONNMARK line for a policy-NAT rule's mark companion.

    Reproduces the rule's exact match (protocol/source/destination — honoring
    resolved set:<ipset> tokens the same way _restore_line does — plus
    port/interfaces/state) so the mark is set on precisely the connections this
    policy accepts. Deliberately excludes limit_rate/limit_burst: a rate-limited
    CONNMARK line would own a separate `-m limit` token bucket from the ACCEPT
    line right below it and could mark/skip out of sync with it. Also excludes
    the LOG/REJECT-only extras (irrelevant to an ACCEPT-only policy_nat rule).
    """
    eff = eff_map.get(rule.id)
    source = eff[0] if eff and eff[0] is not None else rule.source
    destination = eff[1] if eff and eff[1] is not None else rule.destination
    xmark = f"0x{mark:x}/0x{iptables.POLICY_NAT_MARK_MASK:x}"
    return " ".join(iptables.build_rule_args(
        chain=madmin_chain, action="CONNMARK",
        protocol=rule.protocol, source=source, destination=destination,
        port=rule.port, in_interface=rule.in_interface, out_interface=rule.out_interface,
        state=rule.state, set_xmark=xmark,
        comment=f"MADMIN_NATMARK_{rule.id}", operation="-A",
    ))


def _build_forward_layout(
    forward_rules: List,
    eff_map: Dict,
    nat_marks: Optional[Dict] = None,
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

    nat_marks: {rule_id: mark_value} for filter/FORWARD policies with
    policy_nat=True (see apply_rules). Each gets a CONNMARK line emitted
    immediately before its own ACCEPT line, in the same (sub)chain — the mark
    lands on the connection's first packet before it's accepted, and the
    POSTROUTING masquerade companion (policy_nat_fields) matches by that mark
    instead of by flow, so it can never fire for a different policy's traffic.

    Returns (forward_lines, {subchain_name: [lines]}).
    """
    nat_marks = nat_marks or {}
    lines: List[str] = []
    subchains: Dict[str, List[str]] = {}
    for rule in forward_rules:
        mark = nat_marks.get(rule.id)
        if rule.in_interface and rule.out_interface:
            name = iptables.forward_subchain_name(rule.in_interface, rule.out_interface)
            if name not in subchains:
                subchains[name] = []
                lines.append(
                    f"-A {iptables.MADMIN_FORWARD_CHAIN}"
                    f" -i {rule.in_interface} -o {rule.out_interface} -j {name}"
                )
            if mark is not None:
                subchains[name].append(_connmark_restore_line(name, rule, eff_map, mark))
            subchains[name].append(_restore_line(name, rule, eff_map))
        else:
            if mark is not None:
                lines.append(_connmark_restore_line(iptables.MADMIN_FORWARD_CHAIN, rule, eff_map, mark))
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

    async def resolve_dnat_targets(
        self,
        session: AsyncSession,
        rules,
    ) -> Dict[uuid.UUID, Optional[str]]:
        """
        Effective to_destination (see effective_to_destination) for every DNAT
        rule in `rules`: literal-target rules resolve to their own column
        unchanged, object-target rules resolve through the referenced
        AddressObject's value — one batched query for every object referenced,
        regardless of how many rules share it. Shared by apply_rules and the
        API layer (router.py) so a DNAT's target is always computed the same
        way no matter which one is asking.
        """
        dnat_rules = [r for r in rules if r.action == "DNAT"]
        obj_ids = {r.to_destination_object_id for r in dnat_rules if r.to_destination_object_id}
        obj_values: Dict[uuid.UUID, str] = {}
        if obj_ids:
            ores = await session.execute(select(AddressObject).where(AddressObject.id.in_(obj_ids)))
            obj_values = {o.id: o.value for o in ores.scalars().all()}
        return {
            r.id: effective_to_destination(
                r, obj_values.get(r.to_destination_object_id) if r.to_destination_object_id else None
            )
            for r in dnat_rules
        }

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
            .where(or_(
                MachineFirewallRule.to_destination.is_not(None),
                MachineFirewallRule.to_destination_object_id.is_not(None),
            ))
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

    async def get_enabled_hairpin_rules(
        self,
        session: AsyncSession
    ) -> List[MachineFirewallRule]:
        """Get enabled DNAT rules with hairpin=True — source of the hairpin-NAT companions."""
        result = await session.execute(
            select(MachineFirewallRule)
            .where(MachineFirewallRule.table_name == "nat")
            .where(MachineFirewallRule.action == "DNAT")
            .where(MachineFirewallRule.hairpin == True)
            .where(MachineFirewallRule.enabled == True)
            .where(or_(
                MachineFirewallRule.to_destination.is_not(None),
                MachineFirewallRule.to_destination_object_id.is_not(None),
            ))
            .order_by(MachineFirewallRule.order)
        )
        return result.scalars().all()

    async def get_enabled_input_companion_rules(
        self,
        session: AsyncSession
    ) -> Dict[str, List[MachineFirewallRule]]:
        """
        Enabled nat/PREROUTING REDIRECT rules and DNAT rules whose target is a
        local address — source of the INPUT ACCEPT companions (both deliver to
        the gateway itself, so they traverse INPUT rather than FORWARD).
        """
        redirect_result = await session.execute(
            select(MachineFirewallRule)
            .where(MachineFirewallRule.table_name == "nat")
            .where(MachineFirewallRule.chain == "PREROUTING")
            .where(MachineFirewallRule.action == "REDIRECT")
            .where(MachineFirewallRule.enabled == True)
            .order_by(MachineFirewallRule.order)
        )
        redirect_rules = list(redirect_result.scalars().all())

        dnat_result = await session.execute(
            select(MachineFirewallRule)
            .where(MachineFirewallRule.table_name == "nat")
            .where(MachineFirewallRule.action == "DNAT")
            .where(MachineFirewallRule.enabled == True)
            .where(or_(
                MachineFirewallRule.to_destination.is_not(None),
                MachineFirewallRule.to_destination_object_id.is_not(None),
            ))
            .order_by(MachineFirewallRule.order)
        )
        dnat_candidates = list(dnat_result.scalars().all())
        dnat_targets = await self.resolve_dnat_targets(session, dnat_candidates)
        topo = await self._get_interface_topology()
        dnat_self_rules = []
        for rule in dnat_candidates:
            dest_ip, _ = iptables.split_ip_port(dnat_targets.get(rule.id))
            if dest_ip and dest_ip in topo["local_ips"]:
                dnat_self_rules.append(rule)

        return {"redirect": redirect_rules, "dnat_self": dnat_self_rules}

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
            to_destination_object_id=(
                uuid.UUID(rule_data["to_destination_object_id"])
                if rule_data.get("to_destination_object_id") else None
            ),
            to_destination_port=rule_data.get("to_destination_port"),
            to_source=rule_data.get("to_source"),
            to_ports=rule_data.get("to_ports"),
            log_prefix=rule_data.get("log_prefix"),
            log_level=rule_data.get("log_level"),
            reject_with=rule_data.get("reject_with"),
            comment=rule_data.get("comment"),
            table_name=table_name,
            order=max_order + 1,
            enabled=rule_data.get("enabled", True),
            policy_nat=rule_data.get("policy_nat", False),
            # NOTE: was missing entirely before this fix — every hairpin-enabled
            # DNAT created via POST /firewall/rules silently persisted as
            # hairpin=False regardless of what the client sent.
            hairpin=rule_data.get("hairpin", False),
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
            # to_destination_object_id is a UUID column; the API layer only
            # ever hands this loop a plain str (see MachineFirewallRuleUpdate).
            if key == "to_destination_object_id" and isinstance(value, str):
                value = uuid.UUID(value)
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
        """
        return (await self._get_interface_topology())["lan_interfaces"]

    async def _get_interface_topology(self) -> Dict:
        """
        Resolve live network topology once per apply: LAN interfaces/subnets, WAN
        IPs, and every IPv4 address owned by a physical interface. Backs the
        hairpin-NAT companions (need each LAN subnet + which one contains a given
        target) and the DNAT/REDIRECT-to-self INPUT companions (need "is this
        address one of ours"). NetworkService already excludes loopback/virtual
        interfaces, so local_ips never includes 127.0.0.1 — that's fine, a DNAT
        to loopback is rejected outright by protected_ports.py Guard B.
        NetworkService.get_interfaces() is synchronous — runs in executor.
        """
        from core.network.service import NetworkService
        from core.network.utils import get_default_interface

        wan_iface = get_default_interface()
        loop = asyncio.get_event_loop()
        all_ifaces = await loop.run_in_executor(None, NetworkService().get_interfaces)

        lan_interfaces: List[Tuple[str, List[str]]] = []
        lan_networks: List[ipaddress.IPv4Network] = []
        wan_ips: List[str] = []
        local_ips: set = set()

        for iface in all_ifaces:
            name = iface.get("name", "")
            if not name:
                continue
            ips = iface.get("addresses", [])
            local_ips.update(ips)

            is_wan = name == wan_iface
            if is_wan:
                wan_ips.extend(ips)
            elif ips:
                lan_interfaces.append((name, ips))

            # Subnets are only meaningful for the LAN side (hairpin scoping).
            if is_wan:
                continue
            for entry in iface.get("addr_info", []):
                ip, netmask = entry.get("address"), entry.get("netmask")
                if not ip or not netmask:
                    continue  # e.g. point-to-point links report no netmask
                try:
                    net = ipaddress.IPv4Network(f"{ip}/{netmask}", strict=False)
                except ValueError:
                    continue
                if net not in lan_networks:
                    lan_networks.append(net)

        return {
            "lan_interfaces": lan_interfaces,
            "lan_networks": lan_networks,
            "wan_ips": wan_ips,
            "local_ips": local_ips,
            "wan_interface": wan_iface,
        }

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
        topo = await self._get_interface_topology()
        await self._rebuild_gateway_ipsets(topo["lan_interfaces"])

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

        # DNAT targets that reference an address object resolve to a literal
        # ip[:port] here, once, for every consumer below (the DNAT restore
        # line itself, its FORWARD/INPUT/hairpin companions) — see
        # effective_to_destination / resolve_dnat_targets.
        dnat_targets = await self.resolve_dnat_targets(session, rules)

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
        protect_lines = iptables.build_gateway_protect_lines(topo["lan_interfaces"])
        chain_rules["filter"][iptables.MADMIN_GW_PROTECT_CHAIN] = protect_lines

        # MADMIN_GW_EXCEPTS starts empty (populated below by DB rules with chain=GW_EXCEPTIONS)
        chain_rules["filter"][iptables.MADMIN_GW_EXCEPTS_CHAIN] = []

        # --- Auto-generate INPUT ACCEPT for REDIRECT / DNAT-to-self rules ---
        # A REDIRECT always delivers to the host itself; a DNAT whose target is
        # one of the host's own addresses does too — both traverse INPUT (not
        # FORWARD) after the rewrite and would hit the INPUT catch-all. Unlike
        # the FORWARD implicit deny (engine-owned, always last), that catch-all
        # is an ordinary DB rule (see defaults.py) — appending companions after
        # DB rules would make them dead on every default install. Prepended
        # here, right after the built-in ESTABLISHED line and before any DB
        # INPUT rule, so they encode the same "the admin explicitly published
        # this service" intent the DNAT/FORWARD companion already carries.
        # Consequence (deliberate, FortiGate-VIP-like): an explicit user INPUT
        # DROP cannot override one of these — disable the PREROUTING rule (or
        # scope its `source`, which the companion inherits) to block it instead.
        auto_input_lines: List[str] = []
        for rule in rules:
            if rule.table_name != "nat":
                continue
            if rule.chain == "PREROUTING" and rule.action == "REDIRECT":
                fields = redirect_input_fields(rule)
            elif rule.action == "DNAT" and rule.to_destination:
                dest_ip, _ = iptables.split_ip_port(rule.to_destination)
                if not dest_ip or dest_ip not in topo["local_ips"]:
                    continue
                fields = dnat_input_fields(rule)
            else:
                continue
            eff = eff_map.get(rule.id)
            if eff and eff[0] is not None:
                fields["source"] = eff[0]   # honor object/group source refs
            auto_input_lines.append(
                " ".join(iptables.build_rule_args(
                    chain=iptables.MADMIN_INPUT_CHAIN,
                    action="ACCEPT",
                    comment=f"MADMIN_AUTO_RDR_{rule.id}",
                    operation="-A",
                    **fields,
                ))
            )
        if auto_input_lines:
            chain_rules["filter"][iptables.MADMIN_INPUT_CHAIN].extend(auto_input_lines)

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
            chain_rules[rule.table_name][madmin_chain].append(
                _restore_line(madmin_chain, rule, eff_map, dnat_targets.get(rule.id))
            )

        # --- FORWARD layout: per-interface-pair subchains + inline wildcard rules ---
        forward_rules = [r for r in rules if r.table_name == "filter" and r.chain == "FORWARD"]

        # Conntrack marks for policy-NAT scoping: assigned by apply-order
        # enumeration on every apply. Netfilter decides a connection's NAT on
        # its FIRST packet only, so re-numbering marks across applies can
        # never re-NAT or break an already-established connection; a stale
        # ctmark left on an old connection is inert (the nat table is never
        # re-consulted for it once a connection has a NAT decision).
        nat_policies = [r for r in forward_rules if r.policy_nat]
        if len(nat_policies) > 255:
            logger.error(
                f"{len(nat_policies)} policy-NAT rules exceed the 255-mark budget "
                f"(POLICY_NAT_MARK_MASK); the extra {len(nat_policies) - 255} get no NAT companion."
            )
        nat_marks = {r.id: (i + 1) << 16 for i, r in enumerate(nat_policies[:255])}

        forward_lines, subchain_map = _build_forward_layout(forward_rules, eff_map, nat_marks)
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
            if rule.table_name != "nat" or rule.action != "DNAT":
                continue
            target = dnat_targets.get(rule.id)
            if not target:
                continue
            fields = dnat_forward_fields(rule, target)
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
        # Scoped by conntrack mark (set by the CONNMARK companion emitted in
        # _build_forward_layout above), not by flow — this is what closes the
        # cross-policy masquerade leak the old flow-based match had: a packet
        # accepted by a *different*, non-NAT policy never carries this mark,
        # no matter how much its match overlaps this policy's.
        auto_nat_lines: List[str] = []
        for rule in nat_policies:
            mark = nat_marks.get(rule.id)
            if mark is None:
                continue  # 255-mark budget exhausted, already logged above
            fields = policy_nat_fields(rule)
            out_if = fields["out_interface"] or topo["wan_interface"]
            if not out_if:
                logger.warning(
                    f"policy NAT {rule.id}: no out_interface and no default-route "
                    "interface resolved — emitting MASQUERADE unscoped as a last resort."
                )
            xmark = f"0x{mark:x}/0x{iptables.POLICY_NAT_MARK_MASK:x}"
            auto_nat_lines.append(
                " ".join(iptables.build_rule_args(
                    chain=iptables.MADMIN_POSTROUTING_NAT_CHAIN,
                    action="MASQUERADE",
                    out_interface=out_if,
                    connmark_match=xmark,
                    comment=f"MADMIN_AUTO_NAT_{rule.id}",
                    operation="-A",
                ))
            )
        if auto_nat_lines:
            chain_rules["nat"][iptables.MADMIN_POSTROUTING_NAT_CHAIN].extend(auto_nat_lines)

        # --- Auto-generate hairpin-NAT companions for DNAT rules with hairpin=True ---
        # Lets a LAN client reach a port forward via the WAN IP (NAT reflection).
        # The original DNAT carries -i <wan> and never matches LAN-sourced
        # traffic, so without this a LAN client hitting the WAN IP would route
        # to the host itself or die in FORWARD. Per LAN subnet: a PREROUTING
        # DNAT without -i (appended after user PREROUTING rules — matches are
        # disjoint from the original rule anyway), a POSTROUTING MASQUERADE so
        # the internal server's reply routes back through the gateway, and a
        # FORWARD ACCEPT for the LAN-sourced flow (the DNAT's own FORWARD
        # companion above carries -i <wan> and won't match it).
        hairpin_prerouting_lines: List[str] = []
        hairpin_postrouting_lines: List[str] = []
        hairpin_forward_lines: List[str] = []
        for rule in rules:
            if rule.table_name != "nat" or rule.action != "DNAT" or not rule.hairpin:
                continue
            target = dnat_targets.get(rule.id)
            if not target:
                continue
            if not topo["lan_networks"]:
                logger.warning(f"Hairpin NAT skipped for rule {rule.id}: no LAN subnet resolved")
                continue

            dest_ip, dest_port = iptables.split_ip_port(target)
            int_port = dest_port or rule.port

            eff = eff_map.get(rule.id)
            eff_dest = eff[1] if (eff and eff[1] is not None) else rule.destination

            # Never leave the hairpin DNAT's destination unscoped: an unscoped
            # -d would hijack ALL LAN traffic on this dport, not just traffic
            # aimed at this forward's public IP(s). Fall back to the host's own
            # WAN addresses (what the forward actually binds to); if neither is
            # available, skip rather than guess.
            if eff_dest:
                dest_targets = [eff_dest]
            elif topo["wan_ips"]:
                dest_targets = topo["wan_ips"]
            else:
                logger.warning(f"Hairpin NAT skipped for rule {rule.id}: no destination and no WAN IP to scope to")
                dest_targets = []

            for subnet in topo["lan_networks"]:
                for dest in dest_targets:
                    hairpin_prerouting_lines.append(
                        " ".join(iptables.build_rule_args(
                            chain=iptables.MADMIN_PREROUTING_NAT_CHAIN,
                            action="DNAT",
                            protocol=rule.protocol,
                            source=str(subnet),
                            destination=dest,
                            port=rule.port,
                            to_destination=target,
                            comment=f"MADMIN_AUTO_HAIRPIN_{rule.id}",
                            operation="-A",
                        ))
                    )
                hairpin_forward_lines.append(
                    " ".join(iptables.build_rule_args(
                        chain=iptables.MADMIN_FORWARD_CHAIN,
                        action="ACCEPT",
                        protocol=rule.protocol,
                        source=str(subnet),
                        destination=dest_ip,
                        port=int_port,
                        comment=f"MADMIN_AUTO_HAIRPIN_{rule.id}",
                        operation="-A",
                    ))
                )

            # Scope the masquerade to the subnet actually containing the
            # target so unrelated intra-subnet flows aren't masqueraded;
            # fall back to every LAN subnet when the target isn't in any of them.
            masq_fields = hairpin_masq_fields(rule, target)
            try:
                target_addr = ipaddress.IPv4Address(dest_ip) if dest_ip else None
            except ValueError:
                target_addr = None
            matching_subnets = [n for n in topo["lan_networks"] if target_addr and target_addr in n] \
                or topo["lan_networks"]
            for subnet in matching_subnets:
                hairpin_postrouting_lines.append(
                    " ".join(iptables.build_rule_args(
                        chain=iptables.MADMIN_POSTROUTING_NAT_CHAIN,
                        action="MASQUERADE",
                        source=str(subnet),
                        comment=f"MADMIN_AUTO_HAIRPIN_{rule.id}",
                        operation="-A",
                        **masq_fields,
                    ))
                )

        if hairpin_prerouting_lines:
            chain_rules["nat"][iptables.MADMIN_PREROUTING_NAT_CHAIN].extend(hairpin_prerouting_lines)
        if hairpin_postrouting_lines:
            chain_rules["nat"][iptables.MADMIN_POSTROUTING_NAT_CHAIN].extend(hairpin_postrouting_lines)
        if hairpin_forward_lines:
            chain_rules["filter"][iptables.MADMIN_FORWARD_CHAIN].extend(hairpin_forward_lines)

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
            f" ({len(subchain_map)} forward subchains, gateway protect: {len(topo['lan_interfaces'])} LAN interfaces)"
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
