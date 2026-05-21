"""
MADMIN Nftables Backend

FirewallBackend implementation backed by nftables (nft) + nft sets.
All rules live in table `ip madmin`. Dispatcher chains (INPUT, FORWARD, …)
carry type/hook declarations; MADMIN_* chains are regular chains with no hook.

Design notes:
- Batch operations use `nft -f /dev/stdin` for atomicity (like iptables-restore).
- Sets replace ipset: `nft set` of type ipv4_addr with flag interval.
- The `table` parameter (filter/nat/mangle/raw) is mapped to nftables chain
  types via _NFT_DISPATCHER_MAP and _NFT_HOOK_DECLS.
- MOCK_IPTABLES=true skips all nft calls (same dev flag as iptables backend).
- rule_to_restore_line() converts MachineFirewallRule to nft rule syntax.
"""
import subprocess
import logging
import re
from typing import Dict, List, Optional, Tuple

from config import get_settings
from .base import (
    FirewallBackend,
    FirewallError,
    CHAIN_MAP,
    MADMIN_GW_PROTECT_CHAIN,
    MADMIN_GW_EXCEPTS_CHAIN,
)

logger = logging.getLogger(__name__)
settings = get_settings()

NFT_TABLE = "ip madmin"

# ---------------------------------------------------------------------------
# Dispatcher chain names: maps (iptables-table, parent-chain) → nft chain name
# These are the hooked chains that replace iptables built-in chains.
# ---------------------------------------------------------------------------
_NFT_DISPATCHER_MAP: Dict[Tuple[str, str], str] = {
    ("filter",  "INPUT"):       "INPUT",
    ("filter",  "FORWARD"):     "FORWARD",
    ("filter",  "OUTPUT"):      "OUTPUT",
    ("nat",     "PREROUTING"):  "PREROUTING",
    ("nat",     "POSTROUTING"): "POSTROUTING",
    ("nat",     "OUTPUT"):      "NAT_OUTPUT",
    ("mangle",  "PREROUTING"):  "PREROUTING_MANGLE",
    ("mangle",  "INPUT"):       "INPUT_MANGLE",
    ("mangle",  "FORWARD"):     "FORWARD_MANGLE",
    ("mangle",  "OUTPUT"):      "OUTPUT_MANGLE",
    ("mangle",  "POSTROUTING"): "POSTROUTING_MANGLE",
    ("raw",     "PREROUTING"):  "PREROUTING_RAW",
    ("raw",     "OUTPUT"):      "OUTPUT_RAW",
}

# nftables type/hook declarations for dispatcher chains
_NFT_HOOK_DECLS: Dict[str, str] = {
    "INPUT":              "type filter hook input priority 0; policy accept;",
    "FORWARD":            "type filter hook forward priority 0; policy accept;",
    "OUTPUT":             "type filter hook output priority 0; policy accept;",
    "PREROUTING":         "type nat hook prerouting priority -100; policy accept;",
    "POSTROUTING":        "type nat hook postrouting priority 100; policy accept;",
    "NAT_OUTPUT":         "type nat hook output priority -100; policy accept;",
    "PREROUTING_MANGLE":  "type route hook prerouting priority -150; policy accept;",
    "INPUT_MANGLE":       "type filter hook input priority -150; policy accept;",
    "FORWARD_MANGLE":     "type filter hook forward priority -150; policy accept;",
    "OUTPUT_MANGLE":      "type route hook output priority -150; policy accept;",
    "POSTROUTING_MANGLE": "type filter hook postrouting priority -150; policy accept;",
    "PREROUTING_RAW":     "type filter hook prerouting priority -300; policy accept;",
    "OUTPUT_RAW":         "type filter hook output priority -300; policy accept;",
}

# Reverse map: dispatcher chain name → (iptables-table, parent-chain)
_NFT_DISPATCHER_REVERSE: Dict[str, Tuple[str, str]] = {
    v: k for k, v in _NFT_DISPATCHER_MAP.items()
}


class NftablesError(FirewallError):
    """Nftables-specific firewall error."""
    pass


# ---------------------------------------------------------------------------
# Low-level nft executor
# ---------------------------------------------------------------------------

def _run_nft(args: List[str], suppress_errors: bool = False) -> Tuple[bool, str]:
    """Execute an nft command. Returns (success, output)."""
    if settings.mock_iptables:
        logger.debug(f"[MOCK nft] Would execute: nft {' '.join(args)}")
        return True, ""

    cmd = ["nft"] + args
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        return True, result.stdout
    except subprocess.CalledProcessError as e:
        if not suppress_errors:
            logger.error(f"nft command failed: {' '.join(cmd)}: {e.stderr.strip()}")
            raise NftablesError(f"nft error: {e.stderr.strip()}")
        return False, e.stderr
    except FileNotFoundError:
        msg = "nft command not found — install nftables package"
        logger.error(msg)
        if not suppress_errors:
            raise NftablesError(msg)
        return False, "nft not found"


def _nft_apply_script(script: str, suppress_errors: bool = False) -> bool:
    """Apply an nft batch script via stdin (atomic — equivalent to iptables-restore)."""
    if settings.mock_iptables:
        logger.debug(f"[MOCK nft] Would apply script:\n{script}")
        return True

    try:
        result = subprocess.run(
            ["nft", "-f", "/dev/stdin"],
            input=script,
            capture_output=True,
            text=True,
            check=True,
        )
        logger.debug("nft script applied successfully")
        return True
    except subprocess.CalledProcessError as e:
        if not suppress_errors:
            logger.error(f"nft script failed: {e.stderr.strip()}")
            raise NftablesError(f"nft script error: {e.stderr.strip()}")
        logger.debug(f"nft script failed (suppressed): {e.stderr.strip()}")
        return False
    except FileNotFoundError:
        msg = "nft command not found — install nftables package"
        logger.error(msg)
        if not suppress_errors:
            raise NftablesError(msg)
        return False


# ---------------------------------------------------------------------------
# Chain helpers
# ---------------------------------------------------------------------------

def _dispatcher_chain(table: str, parent_chain: str) -> Optional[str]:
    return _NFT_DISPATCHER_MAP.get((table, parent_chain))


def _nft_chain_exists(chain_name: str) -> bool:
    success, _ = _run_nft(
        ["list", "chain", "ip", "madmin", chain_name], suppress_errors=True
    )
    return success


def _nft_create_chain(chain_name: str, hook_decl: Optional[str] = None) -> bool:
    """Create chain in ip madmin; idempotent. Optionally set hook declaration."""
    if _nft_chain_exists(chain_name):
        return True
    script_lines = [
        "add table ip madmin",
        f"add chain ip madmin {chain_name}",
    ]
    if hook_decl:
        script_lines.append(f"add chain ip madmin {chain_name} {{ {hook_decl} }}")
    return _nft_apply_script("\n".join(script_lines) + "\n")


def _nft_flush_chain(chain_name: str) -> bool:
    return _nft_apply_script(f"flush chain ip madmin {chain_name}\n", suppress_errors=True)


def _nft_delete_chain(chain_name: str) -> bool:
    script = (
        f"flush chain ip madmin {chain_name}\n"
        f"delete chain ip madmin {chain_name}\n"
    )
    return _nft_apply_script(script, suppress_errors=True)


# ---------------------------------------------------------------------------
# Rule formatting: MachineFirewallRule → nft rule syntax
# ---------------------------------------------------------------------------

_NFT_REJECT_MAP = {
    "icmp-port-unreachable":     "icmp type port-unreachable",
    "icmp-net-unreachable":      "icmp type net-unreachable",
    "icmp-host-unreachable":     "icmp type host-unreachable",
    "icmp-net-prohibited":       "icmp type net-prohibited",
    "icmp-host-prohibited":      "icmp type host-prohibited",
    "icmp-admin-prohibited":     "icmp type admin-prohibited",
    "tcp-reset":                 "tcp reset",
}


def _rule_to_nft(madmin_chain: str, rule) -> str:
    """Convert a MachineFirewallRule to an nft add-rule line."""
    parts: List[str] = []

    proto = (rule.protocol or "").lower()
    action = (rule.action or "ACCEPT").upper()

    if proto and proto != "all":
        if proto == "icmp":
            parts.append("ip protocol icmp")
        elif proto in ("tcp", "udp"):
            parts.append(proto)

    if rule.source:
        parts.append(f"ip saddr {rule.source}")
    if rule.destination:
        parts.append(f"ip daddr {rule.destination}")
    if rule.in_interface:
        parts.append(f"iifname \"{rule.in_interface}\"")
    if rule.out_interface:
        parts.append(f"oifname \"{rule.out_interface}\"")

    if rule.state:
        states = ",".join(s.lower().strip() for s in rule.state.split(","))
        parts.append(f"ct state {{{states}}}")

    if rule.port and proto in ("tcp", "udp"):
        port_str = str(rule.port).strip()
        if "," in port_str:
            # multiport
            ports = ",".join(p.strip() for p in port_str.split(","))
            parts.append(f"{proto} dport {{{ports}}}")
        elif ":" in port_str:
            lo, hi = port_str.split(":", 1)
            parts.append(f"{proto} dport {lo}-{hi}")
        else:
            parts.append(f"{proto} dport {port_str}")

    if rule.limit_rate:
        burst = f" burst {rule.limit_burst} packets" if rule.limit_burst else ""
        parts.append(f"limit rate {rule.limit_rate}{burst}")

    # Action
    if action == "ACCEPT":
        parts.append("accept")
    elif action == "DROP":
        parts.append("drop")
    elif action == "RETURN":
        parts.append("return")
    elif action == "REJECT":
        reject_with = _NFT_REJECT_MAP.get(
            (rule.reject_with or "").lower(), "icmp type port-unreachable"
        )
        parts.append(f"reject with {reject_with}")
    elif action == "MASQUERADE":
        ports_part = f" to :{rule.to_ports}" if rule.to_ports else ""
        parts.append(f"masquerade{ports_part}")
    elif action == "DNAT" and rule.to_destination:
        parts.append(f"dnat to {rule.to_destination}")
    elif action == "SNAT" and rule.to_source:
        parts.append(f"snat to {rule.to_source}")
    elif action == "REDIRECT":
        ports_part = f" to :{rule.to_ports}" if rule.to_ports else ""
        parts.append(f"redirect{ports_part}")
    elif action == "LOG":
        prefix = re.sub(r'[^a-zA-Z0-9_\-\. \[\]]', '', rule.log_prefix or "")[:28]
        level = (rule.log_level or "info").lower()
        parts.append(f"log prefix \"{prefix} \" level {level}")
    else:
        parts.append(action.lower())

    if rule.comment:
        safe = re.sub(r'[^a-zA-Z0-9_\-\. ]', '', str(rule.comment))[:255]
        parts.append(f"comment \"{safe}\"")

    rule_expr = " ".join(parts)
    return f"add rule ip madmin {madmin_chain} {rule_expr}"


# ---------------------------------------------------------------------------
# Set operations (nft sets replace ipset)
# ---------------------------------------------------------------------------

def _nft_set_name(iface_name: str) -> str:
    sanitized = iface_name.upper().replace(".", "_").replace("-", "_")[:21]
    return f"MADMIN_GW_{sanitized}"


def _nft_set_exists(setname: str) -> bool:
    ok, _ = _run_nft(["list", "set", "ip", "madmin", setname], suppress_errors=True)
    return ok


def _nft_set_create(setname: str) -> bool:
    if _nft_set_exists(setname):
        return True
    script = (
        "add table ip madmin\n"
        f"add set ip madmin {setname} {{ type ipv4_addr; flags interval; }}\n"
    )
    return _nft_apply_script(script)


def _nft_set_flush(setname: str) -> bool:
    return _nft_apply_script(
        f"flush set ip madmin {setname}\n", suppress_errors=True
    )


def _nft_set_add(setname: str, ip: str) -> bool:
    return _nft_apply_script(
        f"add element ip madmin {setname} {{ {ip} }}\n"
    )


def _nft_set_destroy(setname: str) -> bool:
    return _nft_apply_script(
        f"delete set ip madmin {setname}\n", suppress_errors=True
    )


# ---------------------------------------------------------------------------
# Gateway protection lines (nft syntax)
# ---------------------------------------------------------------------------

def _build_gateway_protect_lines_nft(
    lan_interfaces: List[Tuple[str, List[str]]]
) -> List[str]:
    """
    Build nft add-rule lines for MADMIN_GW_PROTECT.

    For each LAN interface: drops traffic that arrives on that interface,
    is destined for a local address, but NOT in the interface's own nft set.
    Mirrors the iptables ipset-based gateway protection logic.
    """
    lines = []
    for iface_name, ips in lan_interfaces:
        if not ips:
            continue
        setname = _nft_set_name(iface_name)
        if not _nft_set_exists(setname):
            logger.warning(
                f"nft set {setname} for {iface_name} does not exist; "
                "skipping gateway protection rule for this interface"
            )
            continue
        lines.append(
            f"add rule ip madmin {MADMIN_GW_PROTECT_CHAIN} "
            f"iifname \"{iface_name}\" "
            f"ip daddr != @{setname} "
            f"fib daddr type local drop"
        )
    return lines


# ---------------------------------------------------------------------------
# NftablesBackend
# ---------------------------------------------------------------------------

class NftablesBackend(FirewallBackend):
    """
    FirewallBackend implementation backed by nftables.
    Uses a single `ip madmin` table with dispatcher chains (hooked) and
    MADMIN_* chains (regular, no hook).
    """

    # ------------------------------------------------------------------
    # Initialization
    # ------------------------------------------------------------------

    def initialize_core_chains(self) -> bool:
        logger.info("Initializing MADMIN core nftables chains...")
        if settings.mock_iptables:
            logger.debug("[MOCK nft] Skipping initialize_core_chains")
            return True

        script_lines = ["add table ip madmin"]

        # Dispatcher chains (with hook declarations)
        _BUILTIN_PARENTS = {"INPUT", "OUTPUT", "FORWARD", "PREROUTING", "POSTROUTING"}
        for (table, parent), dispatcher in _NFT_DISPATCHER_MAP.items():
            if parent not in _BUILTIN_PARENTS:
                continue
            decl = _NFT_HOOK_DECLS.get(dispatcher, "")
            if decl:
                script_lines.append(
                    f"add chain ip madmin {dispatcher} {{ {decl} }}"
                )
            else:
                script_lines.append(f"add chain ip madmin {dispatcher}")

        # MADMIN_* chains (no hook)
        all_madmin_chains: set = set()
        for chains in CHAIN_MAP.values():
            all_madmin_chains.update(chains.values())
        all_madmin_chains.add(MADMIN_GW_PROTECT_CHAIN)
        all_madmin_chains.add(MADMIN_GW_EXCEPTS_CHAIN)

        for chain in sorted(all_madmin_chains):
            script_lines.append(f"add chain ip madmin {chain}")

        # Wire dispatcher → MADMIN jumps for each table/parent
        for (table, parent), dispatcher in _NFT_DISPATCHER_MAP.items():
            if parent not in _BUILTIN_PARENTS:
                continue
            madmin_chain = self.get_madmin_chain(table, parent)
            if madmin_chain:
                script_lines.append(
                    f"add rule ip madmin {dispatcher} jump {madmin_chain}"
                )

        script = "\n".join(script_lines) + "\n"
        success = _nft_apply_script(script)

        if success:
            logger.info("All MADMIN nftables chains initialized successfully")
        else:
            logger.warning("Some MADMIN nftables chains failed to initialize")
        return success

    # ------------------------------------------------------------------
    # Chain operations
    # ------------------------------------------------------------------

    def chain_exists(self, chain_name: str, table: str = "filter") -> bool:
        return _nft_chain_exists(chain_name)

    def create_chain(self, chain_name: str, table: str = "filter") -> bool:
        return _nft_create_chain(chain_name)

    def create_or_flush_chain(self, chain_name: str, table: str = "filter") -> bool:
        if _nft_chain_exists(chain_name):
            return _nft_flush_chain(chain_name)
        return _nft_create_chain(chain_name)

    def delete_chain(self, chain_name: str, table: str = "filter") -> bool:
        return _nft_delete_chain(chain_name)

    def remove_jump_rule(
        self, source_chain: str, target_chain: str, table: str = "filter"
    ) -> bool:
        # nft requires rule handle to delete; flush + rebuild is used by orchestrator
        # For individual jump removal, delete all matching rules (handle lookup).
        if settings.mock_iptables:
            logger.debug(f"[MOCK nft] remove jump {source_chain} → {target_chain}")
            return True
        ok, output = _run_nft(
            ["--handle", "--numeric", "list", "chain", "ip", "madmin", source_chain],
            suppress_errors=True,
        )
        if not ok:
            return False
        for line in output.splitlines():
            if f"jump {target_chain}" in line:
                m = re.search(r"# handle (\d+)", line)
                if m:
                    handle = m.group(1)
                    ok2, _ = _run_nft(
                        ["delete", "rule", "ip", "madmin", source_chain, "handle", handle],
                        suppress_errors=True,
                    )
                    if not ok2:
                        return False
        return True

    # ------------------------------------------------------------------
    # Atomic rule application
    # ------------------------------------------------------------------

    def restore_chains(
        self, table: str, chain_rules: Dict[str, List[str]]
    ) -> bool:
        """
        Atomically flush + repopulate chains in ip madmin.
        chain_rules lines are expected in nft add-rule format
        (produced by rule_to_restore_line).
        The `table` parameter is accepted for interface compatibility but
        all chains live in `ip madmin`.
        """
        if settings.mock_iptables:
            logger.debug(
                f"[MOCK nft] Would restore {len(chain_rules)} chains (table={table})"
            )
            return True

        script_lines = ["table ip madmin"]
        for chain in chain_rules:
            script_lines.append(f"flush chain ip madmin {chain}")
        for chain, rules in chain_rules.items():
            script_lines.extend(rules)

        script = "\n".join(script_lines) + "\n"
        try:
            result = _nft_apply_script(script)
            logger.debug(
                f"Atomically restored nft chains (table={table}): {list(chain_rules.keys())}"
            )
            return result
        except NftablesError as e:
            logger.error(f"nft restore_chains failed (table={table}): {e}")
            raise FirewallError(str(e)) from e

    def restore_parent_chain_jumps(
        self, table: str, parent_chain: str, target_chains: List[str]
    ) -> bool:
        """
        Atomically rebuild jump rules in a dispatcher chain.
        Dispatcher chain name is resolved via _NFT_DISPATCHER_MAP.
        Falls back to parent_chain directly if not in the map (e.g. module chains).
        """
        dispatcher = _dispatcher_chain(table, parent_chain) or parent_chain

        if settings.mock_iptables:
            logger.debug(
                f"[MOCK nft] Would restore jumps in {dispatcher}: {target_chains}"
            )
            return True

        script_lines = [
            "table ip madmin",
            f"flush chain ip madmin {dispatcher}",
        ]
        for target in target_chains:
            script_lines.append(
                f"add rule ip madmin {dispatcher} jump {target}"
            )

        script = "\n".join(script_lines) + "\n"
        try:
            ok = _nft_apply_script(script)
            logger.debug(
                f"Atomically rebuilt nft jumps in {dispatcher}: {target_chains}"
            )
            return ok
        except NftablesError:
            logger.error(
                f"nft restore_parent_chain_jumps failed for {dispatcher} ({table})"
            )
            return False

    # ------------------------------------------------------------------
    # Rule formatting
    # ------------------------------------------------------------------

    def rule_to_restore_line(self, madmin_chain: str, rule) -> str:
        return _rule_to_nft(madmin_chain, rule)

    # ------------------------------------------------------------------
    # Gateway protection
    # ------------------------------------------------------------------

    def build_gateway_protect_lines(
        self, lan_interfaces: List[Tuple[str, List[str]]]
    ) -> List[str]:
        return _build_gateway_protect_lines_nft(lan_interfaces)

    # ------------------------------------------------------------------
    # Set operations
    # ------------------------------------------------------------------

    def set_name_for_iface(self, iface_name: str) -> str:
        return _nft_set_name(iface_name)

    def set_exists(self, setname: str) -> bool:
        return _nft_set_exists(setname)

    def set_create(self, setname: str) -> bool:
        return _nft_set_create(setname)

    def set_flush(self, setname: str) -> bool:
        return _nft_set_flush(setname)

    def set_add(self, setname: str, ip: str) -> bool:
        return _nft_set_add(setname, ip)

    def set_destroy(self, setname: str) -> bool:
        return _nft_set_destroy(setname)

    # ------------------------------------------------------------------
    # Conntrack (same binary, backend-agnostic)
    # ------------------------------------------------------------------

    def flush_conntrack_for_rule(
        self,
        protocol: Optional[str] = None,
        source: Optional[str] = None,
        destination: Optional[str] = None,
        port: Optional[str] = None,
    ) -> int:
        # conntrack tool is independent of iptables/nftables
        from .iptables import flush_conntrack_for_rule as _ipt_flush
        return _ipt_flush(protocol, source, destination, port)
