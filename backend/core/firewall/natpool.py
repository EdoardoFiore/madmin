"""
Outbound NAT sources: the addresses a forward policy can NAT to.

A policy with NAT leaves through the address of its outgoing interface
(MASQUERADE), through one specific address of the machine (SNAT
--to-source), or through an IP pool (FortiGate-style):

- overload:   many clients share the pool, `SNAT --to-source a-b --persistent`
              (the same client always leaves with the same address);
- one_to_one: a subnet maps onto a block of the same size, `NETMAP --to cidr`.

Replies to the translated connections must reach the machine. A pool with
`arp_reply` gets each of its addresses added as a /32 on the interface whose
subnet contains it, so the machine answers ARP for them. Linux proxy-ARP
entries (`ip neigh add proxy`) are not used: the kernel answers them only
when the route to the address leaves through another interface, never for an
address in the subnet of the interface asking. The /32s are not services:
apply_rules drops new connections to them in INPUT (MADMIN_GW_PROTECT, before
any module chain). Replies to NATed traffic and port forwards are translated
back in PREROUTING and never reach INPUT. Addresses outside every connected
subnet are left alone: the provider must route them to the machine.

MADMIN owns only the /32s it added (state file): netplan addresses are never
touched, and NetworkService hides the managed ones from the interface list.
"""
import ipaddress
import json
import logging
import subprocess
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Set, Tuple

logger = logging.getLogger(__name__)

POOL_TYPES = ("overload", "one_to_one")
MAX_POOL_SIZE = 256


def interface_addresses() -> Dict[str, List[str]]:
    """{interface: [IPv4 addresses]} as NetworkService reports them (primary first). Blocking."""
    from core.network.service import NetworkService

    out: Dict[str, List[str]] = {}
    for iface in NetworkService().get_interfaces():
        name = iface.get("name")
        if name:
            out[name] = list(iface.get("addresses") or [])
    return out


def nat_ip_is_local(ip: str, out_interface: Optional[str], addrs: Dict[str, List[str]]) -> bool:
    """True when ip is an address of out_interface, or of any interface when the policy names none."""
    if out_interface:
        if out_interface.endswith("+"):
            prefix = out_interface[:-1]
            return any(ip in ips for name, ips in addrs.items() if name.startswith(prefix))
        return ip in addrs.get(out_interface, [])
    return any(ip in ips for ips in addrs.values())


def is_single_ipv4(value: str) -> bool:
    try:
        ipaddress.IPv4Address(value)
        return True
    except ValueError:
        return False


# ---------------------------------------------------------------------------
# Pools
# ---------------------------------------------------------------------------

def parse_pool(pool_type: str, value: str) -> Tuple[ipaddress.IPv4Address, ipaddress.IPv4Address,
                                                    Optional[ipaddress.IPv4Network]]:
    """
    (first, last, network) of a pool; network only for one_to_one.
    overload: "a" or "a-b"; one_to_one: a CIDR. At most MAX_POOL_SIZE
    addresses. Raises ValueError with a message for the user.
    """
    value = (value or "").strip()
    if not value.isascii():
        raise ValueError("Indirizzi non validi")
    if pool_type == "overload":
        first_s, _, last_s = value.partition("-")
        try:
            first = ipaddress.IPv4Address(first_s)
            last = ipaddress.IPv4Address(last_s) if last_s else first
        except ValueError:
            raise ValueError("Un pool overload è un IPv4 o un intervallo a-b (es. 203.0.113.10-203.0.113.20)")
        if last < first:
            raise ValueError("Intervallo non valido: il primo indirizzo è dopo l'ultimo")
        if int(last) - int(first) + 1 > MAX_POOL_SIZE:
            raise ValueError(f"Al massimo {MAX_POOL_SIZE} indirizzi per pool")
        return first, last, None
    if pool_type == "one_to_one":
        try:
            net = ipaddress.IPv4Network(value, strict=True)
        except ValueError:
            raise ValueError("Un pool one-to-one è una subnet CIDR (es. 203.0.113.16/28)")
        if net.num_addresses > MAX_POOL_SIZE:
            raise ValueError(f"Al massimo {MAX_POOL_SIZE} indirizzi per pool (/24)")
        return net.network_address, net.broadcast_address, net
    raise ValueError(f"Tipo di pool non valido: {pool_type}")


def pool_addresses(pool) -> List[str]:
    first, last, _ = parse_pool(pool.type, pool.value)
    return [str(ipaddress.IPv4Address(i)) for i in range(int(first), int(last) + 1)]


def pool_target(pool) -> Tuple[str, Dict]:
    """(action, extra build_rule_args) for NAT through this pool."""
    first, last, net = parse_pool(pool.type, pool.value)
    if net is not None:
        return "NETMAP", {"netmap_to": str(net)}
    if first == last:
        return "SNAT", {"to_source": str(first)}
    return "SNAT", {"to_source": f"{first}-{last}", "persistent": True}


def pools_overlap(a, b) -> bool:
    a1, a2, _ = parse_pool(a.type, a.value)
    b1, b2, _ = parse_pool(b.type, b.value)
    return a1 <= b2 and b1 <= a2


def guard_matches(pools: Iterable, exclude: Iterable[str] = ()) -> List[str]:
    """
    Destination matches for the INPUT guard of the ARP-answered pools: the
    /32s exist only to receive replies, never new connections. "a" or "a-b"
    (iprange). `exclude`: addresses configured on the interfaces (netplan),
    which stay reachable even if a pool covers them.
    """
    exclude = set(exclude)
    out = []
    for pool in pools:
        if not pool.arp_reply:
            continue
        first, last, _ = parse_pool(pool.type, pool.value)
        ips = [ipaddress.IPv4Address(i) for i in range(int(first), int(last) + 1)]
        if not exclude.intersection(str(ip) for ip in ips):
            out.append(str(first) if first == last else f"{first}-{last}")
        else:
            out.extend(str(ip) for ip in ips if str(ip) not in exclude)
    return out


def describe(pool, pools: Iterable, ifaces: List[Dict]) -> Tuple[List[str], List[str]]:
    """
    (interfaces its /32s go on, warnings) for the pool list. ifaces: as
    NetworkService.get_interfaces returns them (managed /32s already hidden).
    """
    subnets = []
    configured = set()
    for iface in ifaces:
        for a in iface.get("addr_info", []):
            configured.add(a.get("address"))
            try:
                net = ipaddress.IPv4Network(f"{a['address']}/{a['netmask']}", strict=False)
            except (KeyError, TypeError, ValueError):
                continue
            if net.prefixlen < 32:
                subnets.append((net, iface.get("name")))
    devs: List[str] = []
    warnings: List[str] = []
    addrs = pool_addresses(pool)
    if pool.arp_reply:
        for ip in addrs:
            dev = next((d for net, d in subnets if ipaddress.IPv4Address(ip) in net), None)
            if dev is None:
                if "not_on_connected_subnet" not in warnings:
                    warnings.append("not_on_connected_subnet")
            elif dev not in devs:
                devs.append(dev)
    if configured.intersection(addrs):
        warnings.append("overlaps_interface_ip")
    if any(other.id != pool.id and pools_overlap(pool, other) for other in pools):
        warnings.append("overlaps_pool")
    return devs, warnings


# ---------------------------------------------------------------------------
# The /32 addresses of ARP-answered pools
# ---------------------------------------------------------------------------

def _state_file() -> Path:
    from config import get_settings
    return Path(get_settings().data_dir) / "firewall" / "nat_pool_addrs.json"


def managed_ips() -> Set[str]:
    """Addresses MADMIN added for the pools (hidden from the interface list)."""
    try:
        data = json.loads(_state_file().read_text(encoding="utf-8"))
        return {entry["ip"] for entry in data}
    except (OSError, ValueError, KeyError, TypeError):
        return set()


def _read_state() -> List[Dict[str, str]]:
    try:
        data = json.loads(_state_file().read_text(encoding="utf-8"))
        return [e for e in data if isinstance(e, dict) and "ip" in e and "dev" in e]
    except (OSError, ValueError):
        return []


def _write_state(entries: List[Dict[str, str]]) -> None:
    from core.fsutil import atomic_write
    path = _state_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write(path, json.dumps(sorted(entries, key=lambda e: (e["dev"], e["ip"])), indent=1), mode=0o600)


def _system_addresses() -> List[Dict]:
    """[{dev, ip, prefixlen}] of every IPv4 address (ip -j addr). Blocking."""
    out = subprocess.run(["ip", "-j", "-4", "addr", "show"],
                         capture_output=True, text=True, timeout=10, check=True).stdout
    rows = []
    for iface in json.loads(out or "[]"):
        for a in iface.get("addr_info", []):
            if a.get("local"):
                rows.append({"dev": iface.get("ifname"), "ip": a["local"], "prefixlen": a.get("prefixlen", 32)})
    return rows


def plan_addresses(pools: Iterable, system: List[Dict], owned: Set[Tuple[str, str]]) -> Dict:
    """
    What the pools need on the interfaces, given the current addresses:
    {"desired": {(ip, dev)}, "add": [...], "remove": [...],
     "routed": [ip, ...]  (outside every connected subnet: nothing to add),
     "conflicts": [ip, ...]  (already configured, e.g. by netplan)}.
    `owned`: (ip, dev) pairs MADMIN added earlier.
    """
    present = {(a["ip"], a["dev"]) for a in system}
    configured = {a["ip"] for a in system if (a["ip"], a["dev"]) not in owned}
    subnets = []
    for a in system:
        if (a["ip"], a["dev"]) in owned or a["prefixlen"] >= 32:
            continue
        try:
            subnets.append((ipaddress.IPv4Network(f"{a['ip']}/{a['prefixlen']}", strict=False), a["dev"]))
        except ValueError:
            continue
    subnets.sort(key=lambda s: s[0].prefixlen, reverse=True)

    desired: Set[Tuple[str, str]] = set()
    routed: List[str] = []
    conflicts: List[str] = []
    for pool in pools:
        if not pool.arp_reply:
            continue
        for ip in pool_addresses(pool):
            if ip in configured:
                conflicts.append(ip)
                continue
            addr = ipaddress.IPv4Address(ip)
            dev = next((d for net, d in subnets if addr in net), None)
            if dev is None:
                routed.append(ip)
                continue
            desired.add((ip, dev))
    return {
        "desired": desired,
        "add": sorted(desired - present),
        "remove": sorted((owned - desired) & present),
        "routed": routed,
        "conflicts": conflicts,
    }


def _ip(args: List[str]) -> bool:
    try:
        subprocess.run(["ip", "-4", *args], capture_output=True, text=True, timeout=10, check=True)
        return True
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, OSError) as e:
        logger.error(f"ip {' '.join(args)} failed: {getattr(e, 'stderr', '') or e}")
        return False


def reconcile(pools: Iterable) -> Dict:
    """
    Bring the /32s of the ARP-answered pools in line with the pools: add the
    missing ones, remove those MADMIN added that no pool needs any more.
    Blocking (run in a thread). No-op with MOCK_IPTABLES.
    """
    from config import get_settings
    pools = list(pools)
    if get_settings().mock_iptables:
        return {"add": [], "remove": [], "routed": [], "conflicts": []}
    owned = {(e["ip"], e["dev"]) for e in _read_state()}
    try:
        system = _system_addresses()
    except (subprocess.SubprocessError, OSError, ValueError) as e:
        logger.error(f"NAT pool addresses not reconciled: {e}")
        return {"add": [], "remove": [], "routed": [], "conflicts": []}
    plan = plan_addresses(pools, system, owned)
    kept = set(owned) & plan["desired"]
    for ip, dev in plan["add"]:
        if _ip(["addr", "add", f"{ip}/32", "dev", dev]):
            kept.add((ip, dev))
    for ip, dev in plan["remove"]:
        if not _ip(["addr", "del", f"{ip}/32", "dev", dev]):
            kept.add((ip, dev))   # still there: still ours
    # owned entries already gone from the system are forgotten
    present = {(a["ip"], a["dev"]) for a in system} | set(plan["add"])
    _write_state([{"ip": ip, "dev": dev} for ip, dev in kept if (ip, dev) in present])
    if plan["add"] or plan["remove"]:
        logger.info(f"NAT pool addresses: +{len(plan['add'])} -{len(plan['remove'])}")
    return plan
