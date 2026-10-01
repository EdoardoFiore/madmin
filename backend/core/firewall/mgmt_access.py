"""
Firewall side of a management-port change.

INPUT ends with an ordinary DROP rule (defaults.py), so moving nginx to a new
port without a rule that accepts it locks the admin out. The Settings page
lists the INPUT rules that open the current port; the chosen ones are cloned
for the new port at the top of INPUT before nginx moves, and the old ones are
optionally retired afterwards.
"""
import logging
import uuid
from typing import Dict, List, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .models import FirewallRuleAddress, MachineFirewallRule
from .ports import parse_port_spec, port_in_spec

logger = logging.getLogger(__name__)

_CLONED_FIELDS = (
    "action", "protocol", "source", "destination", "in_interface", "out_interface",
    "state", "limit_rate", "limit_burst", "log_prefix", "log_level", "reject_with",
)


async def rules_opening_port(session: AsyncSession, port: int) -> List[MachineFirewallRule]:
    """Enabled filter/INPUT ACCEPT rules whose port spec names `port` explicitly
    (rules without a port already cover any port and need no copy)."""
    rows = (await session.execute(
        select(MachineFirewallRule).where(
            MachineFirewallRule.table_name == "filter",
            MachineFirewallRule.chain == "INPUT",
            MachineFirewallRule.action == "ACCEPT",
            MachineFirewallRule.enabled == True,  # noqa: E712
        ).order_by(MachineFirewallRule.order)
    )).scalars().all()
    out = []
    for r in rows:
        if not r.port or (r.protocol or "").lower() != "tcp":
            continue
        try:
            if port_in_spec(port, r.port):
                out.append(r)
        except ValueError:
            continue
    return out


def describe(rule: MachineFirewallRule) -> Dict:
    return {
        "id": str(rule.id), "order": rule.order, "protocol": rule.protocol, "port": rule.port,
        "in_interface": rule.in_interface, "source": rule.source, "comment": rule.comment,
    }


async def _move_to_top(session: AsyncSession, rule_ids: List[uuid.UUID]) -> None:
    """Put the given INPUT rules first (in the given order), the rest after."""
    rows = (await session.execute(
        select(MachineFirewallRule).where(
            MachineFirewallRule.table_name == "filter", MachineFirewallRule.chain == "INPUT",
        ).order_by(MachineFirewallRule.order)
    )).scalars().all()
    top = [r for rid in rule_ids for r in rows if r.id == rid]
    rest = [r for r in rows if r.id not in set(rule_ids)]
    for i, r in enumerate(top + rest):
        r.order = i
    await session.flush()


async def clone_for_port(session: AsyncSession, orchestrator, rules: List[MachineFirewallRule],
                         new_port: int) -> List[uuid.UUID]:
    """
    One copy per rule, same match (address refs included) but `--dport new_port`,
    at the top of INPUT. Returns the new rule ids. The caller applies and commits.
    """
    created: List[uuid.UUID] = []
    for r in rules:
        data = {f: getattr(r, f) for f in _CLONED_FIELDS}
        data.update(chain="INPUT", table_name="filter", port=str(new_port), enabled=True,
                    comment=f"MADMIN UI :{new_port} (copia della regola #{r.order + 1})")
        refs = (await session.execute(
            select(FirewallRuleAddress).where(FirewallRuleAddress.rule_id == r.id)
            .order_by(FirewallRuleAddress.order)
        )).scalars().all()
        data["source_refs"] = [
            {"object_id": str(x.object_id)} if x.object_id else {"group_id": str(x.group_id)}
            for x in refs if x.direction == "source"
        ]
        data["destination_refs"] = [
            {"object_id": str(x.object_id)} if x.object_id else {"group_id": str(x.group_id)}
            for x in refs if x.direction == "destination"
        ]
        new = await orchestrator.create_rule(session, data, apply=False)
        created.append(new.id)
    await _move_to_top(session, created)
    return created


async def create_for_port(session: AsyncSession, orchestrator, new_port: int) -> List[uuid.UUID]:
    """No rule opens the current port explicitly: one plain ACCEPT for the new one, on top."""
    data = {"chain": "INPUT", "table_name": "filter", "action": "ACCEPT", "protocol": "tcp",
            "port": str(new_port), "enabled": True, "comment": f"MADMIN UI :{new_port}"}
    new = await orchestrator.create_rule(session, data, apply=False)
    await _move_to_top(session, [new.id])
    return [new.id]


async def retire_old(session: AsyncSession, rules: List[MachineFirewallRule], old_port: int) -> List[str]:
    """
    Stop the old rules from opening the previous port: a single-port rule is
    disabled; in a list the old port is removed (the rule keeps opening the
    others). A range containing it is left as is and reported.
    Returns notes for the response.
    """
    notes = []
    for r in rules:
        spec = r.port or ""
        tokens = spec.split(",")
        if spec == str(old_port):
            r.enabled = False
            notes.append(f"Regola #{r.order + 1} disattivata")
        elif str(old_port) in tokens:
            remaining = ",".join(tk for tk in tokens if tk != str(old_port))
            parse_port_spec(remaining)
            r.port = remaining
            notes.append(f"Regola #{r.order + 1}: porta {old_port} tolta ({remaining})")
        else:
            notes.append(f"Regola #{r.order + 1}: la porta {old_port} è in un intervallo ({spec}), lasciata invariata")
    await session.flush()
    return notes


async def delete_rules(session: AsyncSession, rule_ids: List[uuid.UUID]) -> None:
    from sqlalchemy import delete
    from .models import RuleCounter
    await session.execute(delete(FirewallRuleAddress).where(FirewallRuleAddress.rule_id.in_(rule_ids)))
    await session.execute(delete(RuleCounter).where(RuleCounter.rule_id.in_(rule_ids)))
    await session.execute(delete(MachineFirewallRule).where(MachineFirewallRule.id.in_(rule_ids)))
    await session.flush()
