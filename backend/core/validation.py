"""
MADMIN shared input validators.

Values typed in the UI end up in config files read by root daemons
(swanctl.conf, named.conf, zone files, dhcpd.conf, .ovpn profiles) or in
iptables arguments. In those formats a newline, a quote, a brace or a ';'
starts a directive of the caller's choosing, so each value is checked against
the grammar of what it is (an IP, a hostname, a port…) rather than escaped
after the fact. Every helper returns the normalised value or raises
ValueError, which pydantic reports as a 422.

Patterns use re.fullmatch: re.match with '$' lets a trailing newline through.
"""
import re
import ipaddress
from typing import Iterable, Optional

from sqlmodel import SQLModel
from pydantic import field_validator

_HOST_LABEL = r'(?!-)[A-Za-z0-9-]{1,63}(?<!-)'
_HOSTNAME_RE = re.compile(rf'{_HOST_LABEL}(\.{_HOST_LABEL})*\.?')


def _clean(value, field: str) -> str:
    """str(value) without surrounding spaces; control characters anywhere are refused
    rather than stripped, so a caller keeping the original never gets a newline."""
    value = str(value)
    if any(ord(c) < 32 or ord(c) == 127 for c in value):
        raise ValueError(f"{field}: caratteri di controllo non ammessi")
    return value.strip()


def no_control_chars(value: str, field: str = "value", max_len: int = 255) -> str:
    """Free text that is stored or shown, never parsed: no control characters."""
    value = str(value)
    if len(value) > max_len:
        raise ValueError(f"{field}: max {max_len} caratteri")
    if any(ord(c) < 32 or ord(c) == 127 for c in value):
        raise ValueError(f"{field}: caratteri di controllo non ammessi")
    return value


def one_of(value: str, allowed: Iterable[str], field: str = "value") -> str:
    allowed = tuple(allowed)
    if value not in allowed:
        raise ValueError(f"{field}: valore non valido '{value}' (ammessi: {', '.join(allowed)})")
    return value


def ip_address(value: str, field: str = "indirizzo", version: Optional[int] = None) -> str:
    try:
        ip = ipaddress.ip_address(_clean(value, field))
    except ValueError:
        raise ValueError(f"{field}: indirizzo IP non valido '{value}'")
    if version and ip.version != version:
        raise ValueError(f"{field}: serve un indirizzo IPv{version}")
    return str(ip)


def ip_network(value: str, field: str = "rete", version: Optional[int] = None) -> str:
    """An IP or a CIDR (host bits allowed, normalised away)."""
    try:
        net = ipaddress.ip_network(_clean(value, field), strict=False)
    except ValueError:
        raise ValueError(f"{field}: IP o CIDR non valido '{value}'")
    if version and net.version != version:
        raise ValueError(f"{field}: serve una rete IPv{version}")
    return str(net)


def hostname(value: str, field: str = "hostname") -> str:
    value = _clean(value, field)
    if len(value) > 253 or not _HOSTNAME_RE.fullmatch(value):
        raise ValueError(f"{field}: hostname non valido '{value}'")
    return value


def host(value: str, field: str = "host") -> str:
    """An IP address or a hostname."""
    try:
        return ip_address(value, field)
    except ValueError:
        return hostname(value, field)


def host_port(value: str, field: str = "endpoint") -> str:
    """host, host:port, IPv6 or [IPv6]:port."""
    value = _clean(value, field)
    m = re.fullmatch(r'\[([0-9A-Fa-f:.]+)\](?::(\d{1,5}))?', value)
    if m:
        ip_address(m.group(1), field, version=6)
        if m.group(2):
            port(m.group(2), field)
        return value
    if value.count(":") > 1:  # bare IPv6, no port
        ip_address(value, field, version=6)
        return value
    name, _, p = value.partition(":")
    host(name, field)
    if p:
        port(p, field)
    return value


def port(value, field: str = "porta") -> str:
    if not re.fullmatch(r'\d{1,5}', str(value)) or not 1 <= int(value) <= 65535:
        raise ValueError(f"{field}: porta non valida '{value}' (1-65535)")
    return str(int(value))


def dport(value, field: str = "porta") -> str:
    """What iptables --dport takes: a port or a range 'a:b'."""
    parts = str(value).split(":")
    if len(parts) > 2:
        raise ValueError(f"{field}: porta o intervallo non valido '{value}'")
    for p in parts:
        port(p, field)
    if len(parts) == 2 and int(parts[0]) > int(parts[1]):
        raise ValueError(f"{field}: intervallo invertito '{value}'")
    return str(value)


# --- Schema mixin for the per-group/per-tunnel firewall rules of VPN modules ---

RULE_ACTIONS = ("ACCEPT", "DROP", "REJECT")
RULE_PROTOCOLS = ("tcp", "udp", "icmp", "all")


class ModuleRuleValidators(SQLModel):
    """
    Validators for the rule schemas of the VPN modules (OpenVPN/WireGuard group
    rules, strongSwan child-SA rules). Their fields go straight into iptables
    argv: a bad value was not an injection, but iptables rejected the rule,
    run_safe swallowed the error, and a rule shown as saved was never applied.
    """

    @field_validator('action', mode='before', check_fields=False)
    @classmethod
    def _action(cls, v):
        return v if v is None else one_of(str(v).upper(), RULE_ACTIONS, "azione")

    @field_validator('protocol', mode='before', check_fields=False)
    @classmethod
    def _protocol(cls, v):
        return v if v is None else one_of(str(v).lower(), RULE_PROTOCOLS, "protocollo")

    @field_validator('port', mode='before', check_fields=False)
    @classmethod
    def _port(cls, v):
        return None if v in (None, "") else dport(v)

    @field_validator('destination', 'source', mode='before', check_fields=False)
    @classmethod
    def _network(cls, v):
        if v in (None, ""):
            return v
        ip_network(v, version=4)
        return _clean(v, "rete")  # kept as typed: iptables accepts both forms

    @field_validator('direction', mode='before', check_fields=False)
    @classmethod
    def _direction(cls, v):
        return v if v is None else one_of(v, ("in", "out", "both"), "direzione")

    @field_validator('description', mode='before', check_fields=False)
    @classmethod
    def _description(cls, v):
        return v if v is None else no_control_chars(v, "descrizione")
