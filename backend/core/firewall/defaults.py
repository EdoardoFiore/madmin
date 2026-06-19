"""
Default protective firewall rules.

Generated dynamically from the live interfaces so the rules do not depend on
hardcoded names (e.g. eth0/eth1). The WAN is resolved from the default route and
the LAN interfaces are every other physical NIC. Used by the installer via
POST /api/firewall/apply-defaults.
"""
from typing import List, Tuple, Dict

from core.network.utils import get_default_interface

# UI port exposed on the WAN (matches the Nginx HTTPS listener).
UI_PORT = "7443"
# Fallback WAN name when no default route is present (legacy convention).
WAN_FALLBACK = "eth0"


def build_default_protection_rules(wan: str, lan_ifaces: List[str]) -> List[Dict]:
    """
    Build the default protective ruleset.

    - FORWARD: allow LAN -> WAN egress, drop everything else.
    - INPUT: allow the UI port on the WAN and loopback, drop everything else.
    - POSTROUTING: MASQUERADE each LAN interface out the WAN.

    The list order is the rule order (create_rule assigns `order` by insertion).
    Dict keys match the fields accepted by orchestrator.create_rule.
    """
    rules: List[Dict] = [
        {"chain": "FORWARD", "action": "ACCEPT", "out_interface": wan, "table_name": "filter"},
        {"chain": "FORWARD", "action": "DROP", "table_name": "filter"},
        {"chain": "INPUT", "action": "ACCEPT", "protocol": "tcp", "port": UI_PORT,
         "in_interface": wan, "table_name": "filter"},
        {"chain": "INPUT", "action": "ACCEPT", "in_interface": "lo", "table_name": "filter"},
        {"chain": "INPUT", "action": "DROP", "table_name": "filter"},
    ]
    rules += [
        {"chain": "POSTROUTING", "action": "MASQUERADE", "in_interface": lan,
         "out_interface": wan, "table_name": "nat"}
        for lan in lan_ifaces
    ]
    return rules


async def generate_default_protection_rules(orchestrator) -> Tuple[str, List[str], List[Dict]]:
    """
    Resolve the live WAN/LAN interfaces and build the default ruleset.

    Returns (wan, lan_ifaces, rules). The WAN is the default-route interface
    (fallback `eth0`); LAN interfaces are all physical NICs except WAN and lo
    (reuses orchestrator._get_lan_interfaces).
    """
    wan = get_default_interface() or WAN_FALLBACK
    lan_ifaces = [name for name, _ips in await orchestrator._get_lan_interfaces()]
    rules = build_default_protection_rules(wan, lan_ifaces)
    return wan, lan_ifaces, rules
