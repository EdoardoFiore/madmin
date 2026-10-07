"""
Rules that can never decide anything: shadowed or duplicated by an earlier one.

A rule is shadowed when an earlier enabled terminal rule of the same chain
(in evaluation order) matches every packet it matches — the classic case is
an ACCEPT added at the end of INPUT, below the final DROP: it looks active
and is never reached. Conservative by design: anything that cannot be proven
(different address objects, a rate-limited rule, partial state lists) is not
reported. The filter table, where the first terminal match decides, and the
nat/POSTROUTING rules of Advanced, where the first match decides the source
address (every action there is terminal; ACCEPT and RETURN both mean "no NAT").
"""
import ipaddress
from typing import Dict, Iterable, List, Optional, Sequence

from .ports import parse_port_spec

TERMINAL = {"ACCEPT", "DROP", "REJECT"}
NAT_TERMINAL = {"ACCEPT", "RETURN", "MASQUERADE", "SNAT"}


def policy_nat_key(rule) -> tuple:
    """The NAT an accepting filter rule applies: none, the interface address, an address, a pool."""
    if rule.action != "ACCEPT" or not getattr(rule, "policy_nat", False):
        return ("none",)
    return ("nat", getattr(rule, "to_source", None), getattr(rule, "nat_pool_id", None))


def nat_decision(rule) -> tuple:
    """What a nat/POSTROUTING rule decides: no NAT, or NAT to which address."""
    if rule.action in ("ACCEPT", "RETURN"):
        return ("none",)
    return (rule.action, getattr(rule, "to_source", None), getattr(rule, "nat_pool_id", None))


def _iface_covers(a: Optional[str], b: Optional[str]) -> bool:
    if not a:
        return True
    if not b:
        return False
    if a.endswith("+"):
        return b.startswith(a[:-1])
    return a == b


def _ports_cover(a: Optional[str], b: Optional[str]) -> bool:
    if not a:
        return True
    if not b:
        return False
    try:
        outer, inner = parse_port_spec(a), parse_port_spec(b)
    except ValueError:
        return False
    return all(any(lo <= blo and bhi <= hi for lo, hi in outer) for blo, bhi in inner)


def _refs_key(refs) -> Optional[frozenset]:
    if not refs:
        return None
    out = set()
    for r in refs:
        oid = getattr(r, "object_id", None) if not isinstance(r, dict) else r.get("object_id")
        gid = getattr(r, "group_id", None) if not isinstance(r, dict) else r.get("group_id")
        out.add(("o", oid) if oid else ("g", gid))
    return frozenset(out)


def _addr_covers(a_lit, a_refs, b_lit, b_refs) -> bool:
    ak, bk = _refs_key(a_refs), _refs_key(b_refs)
    if ak is not None:
        return ak == bk           # same objects/groups only: contents can change
    if not a_lit:
        return True
    if bk is not None or not b_lit:
        return False
    try:
        return ipaddress.ip_network(b_lit, strict=False).subnet_of(ipaddress.ip_network(a_lit, strict=False))
    except (ValueError, TypeError):
        return False


def _state_covers(a: Optional[str], b: Optional[str]) -> bool:
    if not a:
        return True
    if not b:
        return False
    return set(b.upper().split(",")) <= set(a.upper().split(","))


def covers(a, b) -> bool:
    """Does rule `a` match every packet rule `b` matches?"""
    if a.limit_rate:
        return False
    if a.protocol and (a.protocol or "").lower() != (b.protocol or "").lower():
        return False
    if a.port and not ((a.protocol or "").lower() in ("tcp", "udp") and _ports_cover(a.port, b.port)):
        return False
    return (
        _iface_covers(a.in_interface, b.in_interface)
        and _iface_covers(a.out_interface, b.out_interface)
        and _addr_covers(a.source, a.source_refs, b.source, b.source_refs)
        and _addr_covers(a.destination, a.destination_refs, b.destination, b.destination_refs)
        and _state_covers(a.state, b.state)
    )


def analyze(ordered: Sequence, nat: bool = False) -> Dict[str, dict]:
    """
    `ordered`: the rules of one filter chain (or, with nat=True, of
    nat/POSTROUTING) in evaluation order, enabled and disabled. Returns
    {rule_id: {"by": id, "kind": "shadowed"|"shadowed_nat"|"duplicate"|"redundant"}}
    for every enabled rule an earlier enabled terminal rule makes useless.
    shadowed_nat: both accept, but the earlier one with another NAT (or none):
    the NAT configured on this rule is never applied, since a connection is
    NATed by the policy that accepted it.
    """
    terminal = NAT_TERMINAL if nat else TERMINAL
    decision = nat_decision if nat else (lambda r: r.action)
    out: Dict[str, dict] = {}
    earlier: List = []
    for rule in ordered:
        if not rule.enabled:
            continue
        for prev in earlier:
            if covers(prev, rule):
                if decision(prev) != decision(rule):
                    kind = "shadowed"       # the opposite decision is taken above
                elif not nat and policy_nat_key(prev) != policy_nat_key(rule):
                    kind = "shadowed_nat"   # accepted above, with a different NAT
                elif covers(rule, prev):
                    kind = "duplicate"
                else:
                    kind = "redundant"      # same decision, already taken above
                out[str(rule.id)] = {"by": str(prev.id), "kind": kind}
                break
        if rule.action in terminal:
            earlier.append(rule)
    return out
