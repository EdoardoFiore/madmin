"""
Which tracked connections would a DROP/REJECT rule actually stop?

A new DROP only applies to new connections: the first rule of INPUT and
FORWARD accepts ESTABLISHED,RELATED. Closing the existing ones means deleting
their conntrack entries, after which their next packet is evaluated again as
NEW. Deleting by the rule's literal fields alone (the previous approach) was
both too broad and blind to order:
- interfaces, address objects/groups and port lists were ignored, so a
  "eth1->eth0 DROP tcp from <object>" policy deleted every TCP entry of the
  box (the admin's own HTTPS session, SSH, every NATed client);
- a connection accepted by a rule ABOVE the DROP was deleted anyway; its
  replies then arrived as NEW with no NAT mapping and were dropped.

This module simulates the chain for each tracked connection, in the order the
engine evaluates it (FORWARD: groups in ForwardSection order, rules in order
inside each group), and selects only the connections whose first deciding
rule is the target. Anything it cannot know — an FQDN object never resolved,
an interface it cannot infer — counts as "might be accepted": the connection
is kept. Module chains (VPN, IPsec, DNS) run before MADMIN_* and are not
simulated; the preview lists what would be closed before anything is.
"""
import ipaddress
import json
import logging
import re
import subprocess
from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Sequence, Set, Tuple

from .ports import port_in_spec

logger = logging.getLogger(__name__)

TERMINAL = {"ACCEPT", "DROP", "REJECT"}
PROTO_NUM = {"icmp": 1, "tcp": 6, "udp": 17}
Net = ipaddress.IPv4Network


@dataclass
class Flow:
    proto: str                 # tcp | udp | icmp | <number>
    src: str                   # original direction
    dst: str
    sport: Optional[int]
    dport: Optional[int]
    reply_src: str             # != dst when the connection was DNATed
    icmp: Optional[Tuple[int, int, int]] = None   # type, code, id

    @property
    def dnat(self) -> bool:
        return self.reply_src != self.dst

    def describe(self) -> dict:
        d = {"proto": self.proto, "src": self.src, "dst": self.dst,
             "sport": self.sport, "dport": self.dport}
        if self.dnat:
            d["to"] = self.reply_src
        return d


_KV = re.compile(r'(\w+)=(\S+)')


def parse_conntrack(text: str) -> List[Flow]:
    """`conntrack -L -f ipv4` output -> flows (original tuple + reply source)."""
    flows = []
    for line in text.splitlines():
        parts = line.split()
        if len(parts) < 3 or not parts[1].isdigit():
            continue
        proto = parts[0]
        orig: Dict[str, str] = {}
        reply: Dict[str, str] = {}
        for k, v in _KV.findall(line):
            target = reply if k in orig and k in ("src", "dst", "sport", "dport", "type", "code", "id") else orig
            target.setdefault(k, v)
        if "src" not in orig or "dst" not in orig:
            continue
        icmp = None
        if proto == "icmp" and "type" in orig:
            icmp = (int(orig["type"]), int(orig.get("code", 0)), int(orig.get("id", 0)))
        flows.append(Flow(
            proto=proto, src=orig["src"], dst=orig["dst"],
            sport=int(orig["sport"]) if "sport" in orig else None,
            dport=int(orig["dport"]) if "dport" in orig else None,
            reply_src=reply.get("src", orig["dst"]), icmp=icmp,
        ))
    return flows


class Topology:
    """Routes and local addresses, to infer a flow's interfaces and chain."""

    def __init__(self, routes: Sequence[Tuple[Net, str]], local_ips: Set[str], default_dev: Optional[str]):
        # longest prefix first
        self.routes = sorted(routes, key=lambda r: r[0].prefixlen, reverse=True)
        self.local_ips = local_ips
        self.default_dev = default_dev

    def dev_for(self, ip: str) -> Optional[str]:
        addr = ipaddress.ip_address(ip)
        for net, dev in self.routes:
            if addr in net:
                return dev
        return self.default_dev

    @classmethod
    def from_system(cls) -> "Topology":
        routes: List[Tuple[Net, str]] = []
        default_dev = None
        out = subprocess.run(["ip", "-j", "-4", "route", "show", "table", "main"],
                             capture_output=True, text=True, timeout=10, check=True).stdout
        for r in json.loads(out or "[]"):
            if r.get("dst") == "default":
                default_dev = default_dev or r.get("dev")
                continue
            try:
                routes.append((ipaddress.ip_network(r["dst"], strict=False), r.get("dev")))
            except (KeyError, ValueError):
                continue
        out = subprocess.run(["ip", "-j", "-4", "addr", "show"],
                             capture_output=True, text=True, timeout=10, check=True).stdout
        local = {a["local"] for i in json.loads(out or "[]") for a in i.get("addr_info", []) if a.get("local")}
        local.add("127.0.0.1")
        return cls(routes, local, default_dev)


def _iface_match(pattern: Optional[str], dev: Optional[str]) -> Optional[bool]:
    """True/False, or None when the interface of the flow is unknown."""
    if not pattern:
        return True
    if dev is None:
        return None
    if pattern.endswith("+"):
        return dev.startswith(pattern[:-1])
    return dev == pattern


def _in_nets(ip: str, nets: Optional[List[Net]]) -> Optional[bool]:
    """nets None = any; [] = matches nothing; UNKNOWN sentinel handled by caller."""
    if nets is None:
        return True
    addr = ipaddress.ip_address(ip)
    return any(addr in n for n in nets)


@dataclass
class RuleView:
    """What the matcher needs from a rule; nets resolved, None = any, 'unknown' = could not resolve."""
    id: str
    action: str
    protocol: Optional[str]
    port: Optional[str]
    in_interface: Optional[str]
    out_interface: Optional[str]
    src: object        # None | List[Net] | "unknown"
    dst: object
    state: Optional[str] = None
    limited: bool = False


def match(rule: RuleView, flow: Flow, chain: str, topo: Topology) -> Optional[bool]:
    """
    Does the rule match the flow's next packet (evaluated as NEW after a
    flush)? True, False, or None when it depends on something unknown.
    """
    if rule.state and "NEW" not in rule.state.upper().split(","):
        return False
    if rule.protocol:
        p = rule.protocol.lower()
        if p not in (flow.proto, str(PROTO_NUM.get(flow.proto, ""))):
            return False
    if rule.port:
        if flow.proto not in ("tcp", "udp") or flow.dport is None:
            return False
        dport = flow.dport
        if not port_in_spec(dport, rule.port):
            return False

    # FORWARD sees the packet after DNAT (destination = the real target)
    dst = flow.reply_src if chain == "FORWARD" else flow.dst
    results = []
    for nets, ip in ((rule.src, flow.src), (rule.dst, dst)):
        if nets == "unknown":
            results.append(None)
        else:
            results.append(_in_nets(ip, nets))
    in_dev = topo.dev_for(flow.src)
    out_dev = topo.dev_for(dst) if chain == "FORWARD" else None
    results.append(_iface_match(rule.in_interface, in_dev))
    if chain == "FORWARD":
        results.append(_iface_match(rule.out_interface, out_dev))
    if any(r is False for r in results):
        return False
    if any(r is None for r in results):
        return None
    return True


def chain_of(flow: Flow, topo: Topology) -> str:
    """INPUT for connections to this machine (not DNATed elsewhere), else FORWARD."""
    if flow.dst in topo.local_ips and not flow.dnat:
        return "INPUT"
    return "FORWARD"


def select_flows(
    flows: Iterable[Flow],
    target: RuleView,
    chain: str,
    ordered: Sequence[RuleView],
    topo: Topology,
    protect_ips: Set[str],
) -> Dict[str, list]:
    """
    Split tracked flows into those the target rule would close and those it
    must not touch. `ordered` = the enabled rules of `chain` in evaluation
    order, target included.
    """
    out = {"close": [], "shadowed": [], "uncertain": [], "protected": []}
    for flow in flows:
        if chain_of(flow, topo) != chain:
            continue
        if flow.src in protect_ips or flow.dst in protect_ips or flow.reply_src in protect_ips:
            if match(target, flow, chain, topo):
                out["protected"].append(flow)
            continue
        for rule in ordered:
            if rule.action not in TERMINAL:
                continue
            m = match(rule, flow, chain, topo)
            if rule.id == target.id:
                if m is True and not rule.limited:
                    out["close"].append(flow)
                elif m is None:
                    out["uncertain"].append(flow)
                break
            if m is False:
                continue
            # an earlier rule decides (or might): not the target's doing
            if m is True and not (rule.action == "ACCEPT" and rule.limited):
                if match(target, flow, chain, topo):
                    out["shadowed"].append(flow)
                break
            if match(target, flow, chain, topo):
                out["uncertain"].append(flow)
            break
    return out


def delete_flow(flow: Flow) -> bool:
    """Delete exactly one conntrack entry by its original tuple."""
    args = ["conntrack", "-D", "-f", "ipv4", "-s", flow.src, "-d", flow.dst]
    if flow.proto in ("tcp", "udp"):
        args[2:2] = ["-p", flow.proto]
        if flow.sport is not None:
            args += ["--sport", str(flow.sport)]
        if flow.dport is not None:
            args += ["--dport", str(flow.dport)]
    elif flow.proto == "icmp" and flow.icmp:
        args[2:2] = ["-p", "icmp"]
        args += ["--icmp-type", str(flow.icmp[0]), "--icmp-code", str(flow.icmp[1]),
                 "--icmp-id", str(flow.icmp[2])]
    else:
        args[2:2] = ["-p", flow.proto]
    try:
        r = subprocess.run(args, capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return False
    return r.returncode == 0


def list_flows() -> List[Flow]:
    r = subprocess.run(["conntrack", "-L", "-f", "ipv4"], capture_output=True, text=True, timeout=30)
    if r.returncode != 0:
        raise RuntimeError((r.stderr or "conntrack -L failed").strip())
    return parse_conntrack(r.stdout)
