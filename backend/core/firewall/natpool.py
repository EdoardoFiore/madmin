"""
Outbound NAT sources: the addresses a forward policy can NAT to.

A policy with NAT leaves through the address of its outgoing interface
(MASQUERADE) or through one specific address of the machine (SNAT
--to-source). That address must be on the machine, or replies to the
translated connections never come back.
"""
import ipaddress
from typing import Dict, List, Optional


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
