"""
MADMIN Firewall — Protected Port Guard

Prevents DNAT/REDIRECT rules that would compromise MADMIN integrity:

  Guard A — public-listener hijack: a DNAT/REDIRECT whose matched --dport equals a
            port a live MADMIN service listens on (UI/management, public-download link,
            or an active module instance) would intercept that traffic in PREROUTING
            before it reaches the local listener → lockout / hijack.

  Guard B — loopback-destination exposure: a DNAT to a loopback/self address (or a
            REDIRECT, which always targets the host) can expose localhost-only services
            (PostgreSQL, the uvicorn backend) to external networks.

The protected port set is computed dynamically at validation time because the relevant
ports are user-modifiable (UI port, module instance ports, public-download URL).
"""
import logging
from typing import List, Optional, Tuple

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from config import get_settings
from .iptables import split_ip_port
from . import defaults

logger = logging.getLogger(__name__)

# (proto, port, human-readable service name)
ProtectedPort = Tuple[str, int, str]

_LOOPBACK_LITERALS = {"localhost", "127.0.0.1", "::1", "0.0.0.0", "::", ""}

# Backend uvicorn port — hardcoded in main.py / systemd, bound to 127.0.0.1.
_BACKEND_PORT = 8000


# --------------------------------------------------------------------------- #
# Port-spec parsing
# --------------------------------------------------------------------------- #
def spec_is_any(spec: Optional[str]) -> bool:
    """True when the rule matches every port (no --dport) → hijacks/exposes anything."""
    return spec is None or str(spec).strip() == ""


def spec_contains_port(spec: Optional[str], port: int) -> bool:
    """
    Whether an iptables port spec covers `port`. Handles single ("7443"),
    multiport ("80,443,8080") and ranges ("80:443" or "8000-8080").
    """
    if spec is None:
        return False
    for tok in str(spec).split(","):
        tok = tok.strip()
        if not tok:
            continue
        sep = ":" if ":" in tok else ("-" if "-" in tok else None)
        if sep:
            a, _, b = tok.partition(sep)
            try:
                lo, hi = int(a), int(b)
            except ValueError:
                continue
            if lo > hi:
                lo, hi = hi, lo
            if lo <= port <= hi:
                return True
        else:
            try:
                if int(tok) == port:
                    return True
            except ValueError:
                continue
    return False


def is_loopback_host(value: Optional[str]) -> bool:
    """True if an address refers to the local host (loopback / self / any)."""
    if not value:
        return True
    v = value.strip().lower().strip("[]")
    if v in _LOOPBACK_LITERALS:
        return True
    if v.startswith("127."):
        return True
    return False


# --------------------------------------------------------------------------- #
# Protected port sets
# --------------------------------------------------------------------------- #
def _localhost_ports() -> List[ProtectedPort]:
    """Localhost-only services that Guard B must keep unreachable via NAT."""
    ports: List[ProtectedPort] = [("tcp", _BACKEND_PORT, "backend MADMIN (uvicorn)")]
    try:
        from urllib.parse import urlparse
        parsed = urlparse(get_settings().database_url)
        host = (parsed.hostname or "").lower()
        if host in {"localhost", "127.0.0.1", "::1"}:
            ports.append(("tcp", parsed.port or 5432, "PostgreSQL"))
    except Exception as e:  # pragma: no cover - defensive
        logger.warning("protected_ports: cannot parse DATABASE_URL: %s", e)
    return ports


async def get_protected_ports(session: AsyncSession) -> List[ProtectedPort]:
    """
    Externally-reachable MADMIN service ports (Guard A). Each source is isolated so a
    single failure never suppresses the rest.
    """
    protected: List[ProtectedPort] = []

    # Management / UI port (read live from nginx; fall back to UI_PORT default).
    try:
        from core.settings.service import NetworkService
        port = await NetworkService()._get_current_port()
        if not port or port == 80:  # 80 == nginx conf absent (dev/mock)
            port = int(defaults.UI_PORT)
        protected.append(("tcp", port, "pannello di amministrazione MADMIN"))
    except Exception as e:
        logger.warning("protected_ports: management port lookup failed: %s", e)
        protected.append(("tcp", int(defaults.UI_PORT), "pannello di amministrazione MADMIN"))

    # Public-download link port (optional, from SMTP settings).
    try:
        res = await session.execute(text("SELECT public_download_url FROM smtp_settings WHERE id = 1"))
        row = res.first()
        url = row[0] if row else None
        if url:
            from core.settings.service import NetworkService
            dport = NetworkService().get_public_download_port(url)
            protected.append(("tcp", dport, "link pubblico download moduli"))
    except Exception as e:
        logger.warning("protected_ports: public-download port lookup failed: %s", e)

    # Module live ports — each loaded module self-declares them via its optional
    # hooks/service_ports.py. Generic & future-proof: a new module is covered as
    # soon as it ships that hook, no change needed here.
    try:
        from core.modules.loader import module_loader
        protected.extend(await module_loader.collect_service_ports(session))
    except Exception as e:
        logger.warning("protected_ports: module service-port collection failed: %s", e)

    return protected


# --------------------------------------------------------------------------- #
# Guard entrypoint
# --------------------------------------------------------------------------- #
def _proto_matches(rule_proto: Optional[str], target_proto: str) -> bool:
    """Rule with no/`all` protocol matches everything; otherwise exact match."""
    if not rule_proto:
        return True
    rp = rule_proto.lower()
    return rp == "all" or rp == target_proto


async def validate_protected_port_collision(
    session: AsyncSession,
    *,
    table_name: Optional[str],
    action: Optional[str],
    chain: Optional[str],
    protocol: Optional[str],
    port: Optional[str],
    to_destination: Optional[str],
    to_ports: Optional[str],
) -> None:
    """
    Raise ValueError if a DNAT/REDIRECT rule would hijack a public MADMIN listener
    (Guard A) or expose a localhost-only service (Guard B). No-op for everything else.
    """
    if (table_name or "filter") != "nat":
        return
    act = (action or "").upper()
    if act not in ("DNAT", "REDIRECT"):
        return
    ch = (chain or "").upper()

    # --- Guard B: loopback / self destination exposure ---
    if act == "DNAT" and to_destination:
        ip, _ = split_ip_port(to_destination)
        if is_loopback_host(ip) or is_loopback_host(to_destination):
            raise ValueError(
                "DNAT verso un indirizzo loopback/locale espone i servizi interni "
                "(es. database, backend) a reti esterne — non consentito."
            )

    if act == "REDIRECT" and ch == "PREROUTING":
        target = to_ports if not spec_is_any(to_ports) else port
        for proto_l, port_l, name_l in _localhost_ports():
            if not _proto_matches(protocol, proto_l):
                continue
            if spec_is_any(target) or spec_contains_port(target, port_l):
                raise ValueError(
                    f"REDIRECT esporrebbe il servizio locale '{name_l}' (porta {port_l}/{proto_l}) "
                    "a reti esterne — non consentito."
                )

    # --- Guard A: public-listener hijack ---
    if ch in ("PREROUTING", "OUTPUT"):
        protected = await get_protected_ports(session)
        any_port = spec_is_any(port)
        for proto_p, port_p, name_p in protected:
            if not _proto_matches(protocol, proto_p):
                continue
            if any_port or spec_contains_port(port, port_p):
                raise ValueError(
                    f"La porta {port_p}/{proto_p} è in uso dal servizio MADMIN '{name_p}': "
                    "un port forwarding su questa porta comprometterebbe il funzionamento "
                    "del pannello/servizio. Regola rifiutata."
                )
