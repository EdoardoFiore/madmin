"""
MADMIN address-object materialization.

Builds the ipsets backing firewall address objects, groups and per-rule
aggregates, mirroring the off-request-path / fail-soft design of
core.firewall.geoip.

Uniform naming (all object types share the same scheme):
- object (cidr/range/fqdn/geo) -> hash:net  MADMIN_AO_<ref_key>
- group                         -> list:set  MADMIN_AG_<ref_key>  (members = leaf object sets)
- per-rule aggregate (>1 ref)   -> list:set  MADMIN_RS_<rid> / MADMIN_RD_<rid>

Resolution per type (IPv4 only in v1):
- cidr  -> the CIDR as-is (a /32 host is allowed)
- range -> CIDRs covering the range (ipaddress.summarize_address_range)
- fqdn  -> A records (socket.getaddrinfo), fail-soft via last-good resolved_ips
- geo   -> country CIDR list from core.firewall.geoip (disk-cached, fail-soft)

The build functions operate on plain dict "plans" (no DB session) so they can run
in a worker thread off the request path, exactly like geoip.
"""
import ipaddress
import logging
import re
import secrets
import socket
from typing import Dict, List, Optional, Iterable

from config import get_settings
from . import iptables, geoip

logger = logging.getLogger(__name__)
settings = get_settings()

AO_PREFIX = "MADMIN_AO_"
AG_PREFIX = "MADMIN_AG_"
RULE_SRC_PREFIX = "MADMIN_RS_"
RULE_DST_PREFIX = "MADMIN_RD_"
# ipsets owned by this module (for destroy-unreferenced sweeps)
_MANAGED_PREFIXES = (AO_PREFIX, AG_PREFIX, RULE_SRC_PREFIX, RULE_DST_PREFIX)
_LIST_PREFIXES = (AG_PREFIX, RULE_SRC_PREFIX, RULE_DST_PREFIX)

# RFC-1123 hostname (at least two labels), used to validate fqdn objects.
_HOSTNAME_RE = re.compile(
    r'^(?=.{1,253}$)(?!-)[A-Za-z0-9-]{1,63}(?<!-)'
    r'(\.(?!-)[A-Za-z0-9-]{1,63}(?<!-))+$'
)


# =============================================================================
# NAMING
# =============================================================================

def object_leaf_set_name(ref_key: str) -> str:
    return f"{AO_PREFIX}{ref_key}"


def group_set_name(ref_key: str) -> str:
    return f"{AG_PREFIX}{ref_key}"


def rule_set_name(rule_id, direction: str) -> str:
    """Per-rule aggregate set name for a direction with >1 references."""
    rid = str(rule_id).replace("-", "")[:12]
    prefix = RULE_SRC_PREFIX if direction == "source" else RULE_DST_PREFIX
    return f"{prefix}{rid}"


def new_ref_key() -> str:
    """8-char hex key used to name an object/group ipset (<= 31-char set limit)."""
    return secrets.token_hex(4)


# =============================================================================
# VALIDATION / RESOLUTION (shared with the router)
# =============================================================================

def normalize_cidr(value: str) -> str:
    """Validate an IPv4 CIDR/host and return its canonical form. Raises ValueError."""
    net = ipaddress.ip_network(value.strip(), strict=False)
    if net.version != 4:
        raise ValueError("Solo IPv4 supportato")
    return str(net)


def range_to_cidrs(value: str) -> List[str]:
    """Convert 'a-b' IPv4 range into covering CIDRs. Raises ValueError."""
    a, sep, b = value.strip().partition("-")
    if not sep:
        raise ValueError("Range non valido: usa il formato 'start-end'")
    start = ipaddress.IPv4Address(a.strip())
    end = ipaddress.IPv4Address(b.strip())
    if int(end) < int(start):
        raise ValueError("Range non valido: l'indirizzo finale precede quello iniziale")
    return [str(n) for n in ipaddress.summarize_address_range(start, end)]


def is_valid_fqdn(value: str) -> bool:
    return bool(_HOSTNAME_RE.match(value.strip()))


def _resolve_fqdn(value: str) -> List[str]:
    """Resolve A records for an FQDN. Returns [] on failure (fail-soft)."""
    try:
        infos = socket.getaddrinfo(value.strip(), None, family=socket.AF_INET)
    except (socket.gaierror, OSError, UnicodeError) as e:
        logger.warning(f"Address: FQDN resolution failed for {value}: {e}")
        return []
    return sorted({info[4][0] for info in infos})


def resolve_entries(obj_type: str, value: str) -> List[str]:
    """Resolve the IPv4 entries for an object by type (network for fqdn/geo)."""
    if obj_type == "cidr":
        return [normalize_cidr(value)]
    if obj_type == "range":
        return range_to_cidrs(value)
    if obj_type == "fqdn":
        return _resolve_fqdn(value)
    if obj_type == "geo":
        return geoip.country_cidrs(value)
    return []


# =============================================================================
# MATERIALIZATION
# =============================================================================

def _object_entries(obj: dict) -> List[str]:
    """Entries to load into an object's leaf set, fail-soft for dynamic types.

    obj keys: type, value, enabled, resolved_ips (list|None for last-good cache).
    """
    if not obj.get("enabled", True):
        return []
    t, v = obj["type"], obj["value"]
    try:
        if t == "cidr":
            return [normalize_cidr(v)]
        if t == "range":
            return range_to_cidrs(v)
        if t == "fqdn":
            # Prefer last-good resolution (set by router/daily task) to avoid
            # re-resolving on every apply; fall back to a fresh lookup.
            return list(obj.get("resolved_ips") or []) or _resolve_fqdn(v)
        if t == "geo":
            return geoip.country_cidrs(v)
    except ValueError:
        return []
    return []


def ensure_sets_exist(plan: dict) -> None:
    """
    Synchronously create EMPTY ipsets for everything referenced by a --match-set
    so apply_rules()'s restore_chains() never fails on a missing set. Fast: no
    resolution, no bulk load. Real population happens in sync_referenced().
    """
    for ref_key in plan.get("objects", {}):
        name = object_leaf_set_name(ref_key)
        if not iptables.ipset_exists(name):
            iptables.ipset_create_net(name)
    for ref_key in plan.get("groups", {}):
        name = group_set_name(ref_key)
        if not iptables.ipset_exists(name):
            iptables.ipset_create_list(name)
    for agg_name in plan.get("rule_sets", {}):
        if not iptables.ipset_exists(agg_name):
            iptables.ipset_create_list(agg_name)


def sync_referenced(plan: dict) -> None:
    """
    Off request-path: build leaf object sets, then group list:sets, then per-rule
    aggregate list:sets (members must exist first), then destroy unreferenced
    MADMIN_AO_/AG_/RS_/RD_ sets. Never raises.

    plan = {
      "objects":   { ref_key: {type, value, enabled, resolved_ips} },  # all leaf objects needed
      "groups":    { ref_key: {enabled, member_object_keys: [ref_key,...]} },
      "rule_sets": { agg_set_name: [leaf_set_name, ...] },
    }
    """
    try:
        objects = plan.get("objects", {})
        groups = plan.get("groups", {})
        rule_sets = plan.get("rule_sets", {})

        # 1) leaf object hash:net sets
        for ref_key, obj in objects.items():
            iptables.ipset_restore_net(object_leaf_set_name(ref_key), _object_entries(obj))

        # 2) group list:sets — members (leaf object sets) now exist
        for ref_key, g in groups.items():
            members = (
                [object_leaf_set_name(k) for k in g.get("member_object_keys", [])]
                if g.get("enabled", True) else []
            )
            iptables.ipset_restore_list(group_set_name(ref_key), members)

        # 3) per-rule aggregate list:sets — members are leaf object sets
        for agg_name, member_set_names in rule_sets.items():
            iptables.ipset_restore_list(agg_name, member_set_names)

        # 4) destroy unreferenced
        keep = (
            {object_leaf_set_name(k) for k in objects}
            | {group_set_name(k) for k in groups}
            | set(rule_sets.keys())
        )
        _destroy_unreferenced(keep)
    except Exception as e:
        logger.error(f"Address: sync_referenced failed: {e}", exc_info=True)


def _destroy_unreferenced(keep: set) -> None:
    """Destroy MADMIN_AO_/AG_/RS_/RD_ sets not in `keep`. list:sets first so a
    stale list:set never blocks destruction of a member it references."""
    if settings.mock_iptables:
        return
    import subprocess
    try:
        result = subprocess.run(["ipset", "list", "-name"], capture_output=True, text=True)
    except FileNotFoundError:
        return
    if result.returncode != 0:
        return
    to_destroy = [
        n for n in result.stdout.split()
        if n.startswith(_MANAGED_PREFIXES) and n not in keep
    ]
    to_destroy.sort(key=lambda n: 0 if n.startswith(_LIST_PREFIXES) else 1)
    for name in to_destroy:
        iptables.ipset_destroy(name)
        logger.info(f"Address: destroyed unreferenced ipset {name}")


def refresh_dynamic(objects: Iterable[dict]) -> Dict[str, List[str]]:
    """
    Re-resolve fqdn objects and re-download geo objects, rebuilding their leaf
    sets. Returns {ref_key: fresh_ips} for fqdn objects whose resolution
    succeeded, so the caller (which holds the DB session) can persist
    resolved_ips. Geo uses the geoip disk cache and is not persisted here.
    Never raises per object.
    """
    fresh: Dict[str, List[str]] = {}
    for obj in objects:
        t = obj["type"]
        ref_key = obj["ref_key"]
        if not obj.get("enabled", True):
            continue
        try:
            if t == "fqdn":
                ips = _resolve_fqdn(obj["value"])
                if ips:
                    iptables.ipset_restore_net(object_leaf_set_name(ref_key), ips)
                    fresh[ref_key] = ips
                elif obj.get("resolved_ips"):
                    iptables.ipset_restore_net(
                        object_leaf_set_name(ref_key), list(obj["resolved_ips"])
                    )
            elif t == "geo":
                cidrs = geoip.country_cidrs(obj["value"], force_reload=True)
                if cidrs:
                    iptables.ipset_restore_net(object_leaf_set_name(ref_key), cidrs)
        except Exception as e:
            logger.error(f"Address: refresh failed for {ref_key} ({t}): {e}")
    return fresh
