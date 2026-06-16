"""
MADMIN Iptables Manager

Low-level wrapper for iptables commands.
Handles chain creation, rule application, and command execution.
Supports all standard iptables tables: filter, nat, mangle, raw.
"""
import subprocess
import logging
import re
from typing import List, Optional, Tuple, Dict
from config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

# =============================================================================
# CHAIN CONSTANTS
# =============================================================================

# Filter table chains
MADMIN_INPUT_CHAIN = "MADMIN_INPUT"
MADMIN_OUTPUT_CHAIN = "MADMIN_OUTPUT"
MADMIN_FORWARD_CHAIN = "MADMIN_FORWARD"

# Gateway protection chains (filter only, not jumped from built-in INPUT directly)
MADMIN_GW_EXCEPTS_CHAIN = "MADMIN_GW_EXCEPTS"   # user-managed ACCEPT exceptions
MADMIN_GW_PROTECT_CHAIN = "MADMIN_GW_PROTECT"   # auto-generated ipset DROP

# NAT table chains
MADMIN_PREROUTING_NAT_CHAIN = "MADMIN_PREROUTING"
MADMIN_POSTROUTING_NAT_CHAIN = "MADMIN_POSTROUTING"
MADMIN_OUTPUT_NAT_CHAIN = "MADMIN_OUTPUT_NAT"

# Mangle table chains
MADMIN_PREROUTING_MANGLE_CHAIN = "MADMIN_PREROUTING_MANGLE"
MADMIN_INPUT_MANGLE_CHAIN = "MADMIN_INPUT_MANGLE"
MADMIN_FORWARD_MANGLE_CHAIN = "MADMIN_FORWARD_MANGLE"
MADMIN_OUTPUT_MANGLE_CHAIN = "MADMIN_OUTPUT_MANGLE"
MADMIN_POSTROUTING_MANGLE_CHAIN = "MADMIN_POSTROUTING_MANGLE"

# Raw table chains
MADMIN_PREROUTING_RAW_CHAIN = "MADMIN_PREROUTING_RAW"
MADMIN_OUTPUT_RAW_CHAIN = "MADMIN_OUTPUT_RAW"


# =============================================================================
# CHAIN MAPPING
# =============================================================================

# Extended mapping: (logical_chain, table) -> MADMIN chain name
# This allows rules to specify table_name and chain, and we route to correct MADMIN chain
CHAIN_MAP: Dict[str, Dict[str, str]] = {
    "filter": {
        "INPUT": MADMIN_INPUT_CHAIN,
        "OUTPUT": MADMIN_OUTPUT_CHAIN,
        "FORWARD": MADMIN_FORWARD_CHAIN,
        # GW_EXCEPTIONS is a virtual key (not a real iptables parent chain).
        # Rules with chain="GW_EXCEPTIONS" are routed to MADMIN_GW_EXCEPTS by apply_rules().
        # The jump from INPUT is managed by rebuild_chain_jumps(), not initialize_core_chains().
        "GW_EXCEPTIONS": MADMIN_GW_EXCEPTS_CHAIN,
    },
    "nat": {
        "PREROUTING": MADMIN_PREROUTING_NAT_CHAIN,
        "OUTPUT": MADMIN_OUTPUT_NAT_CHAIN,
        "POSTROUTING": MADMIN_POSTROUTING_NAT_CHAIN,
    },
    "mangle": {
        "PREROUTING": MADMIN_PREROUTING_MANGLE_CHAIN,
        "INPUT": MADMIN_INPUT_MANGLE_CHAIN,
        "FORWARD": MADMIN_FORWARD_MANGLE_CHAIN,
        "OUTPUT": MADMIN_OUTPUT_MANGLE_CHAIN,
        "POSTROUTING": MADMIN_POSTROUTING_MANGLE_CHAIN,
    },
    "raw": {
        "PREROUTING": MADMIN_PREROUTING_RAW_CHAIN,
        "OUTPUT": MADMIN_OUTPUT_RAW_CHAIN,
    },
}

# Helper function to get MADMIN chain for a given table and parent
def get_madmin_chain(table: str, parent_chain: str) -> Optional[str]:
    """Get the MADMIN chain name for a given table and parent chain."""
    table_map = CHAIN_MAP.get(table, {})
    return table_map.get(parent_chain)


# =============================================================================
# IPSET MATCH HELPERS
# =============================================================================

# A firewall rule's source/destination may carry a "set:<ipset_name>" token
# instead of a literal IP/CIDR. The orchestrator resolves a rule direction's
# address object/group references to a concrete ipset (a leaf hash:net, a group
# list:set, or a per-rule aggregate list:set) and passes this token to
# build_rule_args, which translates it into `-m set --match-set <name> src|dst`.
# This keeps the rule-build path free of any DB access.
_SET_TOKEN_RE = re.compile(r'^set:([A-Za-z0-9_]+)$')


def parse_set(value: Optional[str]) -> Optional[str]:
    """Return the ipset name if value is a 'set:<name>' token, else None."""
    if not value:
        return None
    m = _SET_TOKEN_RE.match(value.strip())
    return m.group(1) if m else None


# =============================================================================
# LOW-LEVEL IPTABLES OPERATIONS
# =============================================================================

class IptablesError(Exception):
    """Custom exception for iptables errors."""
    pass


def parse_iptables_error(stderr: str) -> str:
    """
    Parse iptables/nftables error messages into user-friendly text.
    """
    err = stderr.lower()
    
    # Common nftables/iptables-nft errors
    if "rule_append failed (invalid argument)" in err:
        if "dnat" in err and "output" in err:
            return "DNAT not allowed in OUTPUT chain (use NAT/OUTPUT)"
        return "Parametri non validi per questa chain/tabella. Controlla la compatibilità (es. DNAT solo in NAT)."
    
    if "no chain/target/match by that name" in err:
        return "Chain, target o modulo non trovato. Verifica che la chain esista."
        
    if "bad rule (does a matching rule exist in that chain?)" in err:
        return "Regola non trovata (impossibile eliminare/modificare)."
        
    if "permission denied" in err:
        return "Permesso negato (richiede privilegi di root)."
        
    if "resource temporarily unavailable" in err:
        return "Risorsa non disponibile (lock di iptables attivo? Riprova)."

    # Fallback: clean up the system error
    return f"Errore iptables: {stderr.strip()}"


def _run_iptables(table: str, args: List[str], suppress_errors: bool = False) -> Tuple[bool, str]:
    """
    Execute an iptables command.
    
    Args:
        table: iptables table (filter, nat, mangle, raw)
        args: Command arguments (without 'iptables -t table')
        suppress_errors: If True, don't log errors and don't raise exceptions
    
    Returns:
        Tuple of (success: bool, output: str)
        
    Raises:
        IptablesError: If command fails and suppress_errors is False
    """
    if settings.mock_iptables:
        cmd_str = f"iptables -t {table} {' '.join(args)}"
        logger.debug(f"[MOCK] Would execute: {cmd_str}")
        return True, ""
    
    cmd = ["iptables", "-t", table] + args
    
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=True
        )
        return True, result.stdout
    except subprocess.CalledProcessError as e:
        if not suppress_errors:
            logger.error(f"iptables command failed: {' '.join(cmd)}")
            logger.error(f"Error: {e.stderr}")
            
            # Parse and raise user-friendly error
            friendly_msg = parse_iptables_error(e.stderr)
            raise IptablesError(friendly_msg)
            
        return False, e.stderr
    except FileNotFoundError:
        logger.error("iptables command not found")
        if not suppress_errors:
            raise IptablesError("Comando iptables non trovato sul sistema")
        return False, "iptables not found"


def chain_exists(chain_name: str, table: str = "filter") -> bool:
    """Check if an iptables chain exists."""
    success, _ = _run_iptables(table, ["-L", chain_name, "-n"], suppress_errors=True)
    return success


def create_chain(chain_name: str, table: str = "filter") -> bool:
    """Create an iptables chain if it doesn't exist."""
    if chain_exists(chain_name, table):
        return True
    
    success, _ = _run_iptables(table, ["-N", chain_name])
    if success:
        logger.info(f"Created chain {chain_name} in table {table}")
    return success


def flush_chain(chain_name: str, table: str = "filter") -> bool:
    """Flush all rules from a chain."""
    success, _ = _run_iptables(table, ["-F", chain_name])
    if success:
        logger.debug(f"Flushed chain {chain_name}")
    return success


def delete_chain(chain_name: str, table: str = "filter") -> bool:
    """Delete a chain (flush first, tolerant of non-existent chains)."""
    # Flush and delete — both suppress errors for cleanup tolerance
    _run_iptables(table, ["-F", chain_name], suppress_errors=True)
    success, _ = _run_iptables(table, ["-X", chain_name], suppress_errors=True)
    return success


IPTABLES_MAX_CHAIN_LEN = 29


def create_or_flush_chain(chain_name: str, table: str = "filter") -> bool:
    """Create a chain if it doesn't exist, or flush it if it does."""
    if len(chain_name) > IPTABLES_MAX_CHAIN_LEN:
        raise ValueError(
            f"Chain name too long: '{chain_name}' ({len(chain_name)} chars, "
            f"max {IPTABLES_MAX_CHAIN_LEN})"
        )
    if chain_exists(chain_name, table):
        return flush_chain(chain_name, table)
    else:
        return create_chain(chain_name, table)


def split_ip_port(value: Optional[str]) -> Tuple[Optional[str], Optional[str]]:
    """
    Split an iptables IP[:port] target (e.g. DNAT to-destination) into (ip, port).

    Splits on the last ':' so it tolerates plain IPs ("10.0.0.1" -> ("10.0.0.1", None))
    and IP:port ("10.0.0.1:8080" -> ("10.0.0.1", "8080")). The port part may be a
    range ("8000-8080"); it is returned verbatim.
    """
    if not value:
        return None, None
    if ":" in value:
        ip, _, port = value.rpartition(":")
        return ip, (port or None)
    return value, None


_UNSET = object()


def rule_to_restore_line(madmin_chain: str, rule, source=_UNSET, destination=_UNSET) -> str:
    """Convert a MachineFirewallRule to an iptables-restore format line (-A ...).

    `source`/`destination` may be overridden with an effective value (e.g. a
    'set:<ipset>' token resolved from the rule's address-object references)
    without mutating the ORM object; if omitted, the rule's own columns are used.
    """
    args = build_rule_args(
        chain=madmin_chain,
        action=rule.action,
        protocol=rule.protocol,
        source=rule.source if source is _UNSET else source,
        destination=rule.destination if destination is _UNSET else destination,
        port=rule.port,
        in_interface=rule.in_interface,
        out_interface=rule.out_interface,
        state=rule.state,
        comment=f"ID_{rule.id}",
        limit_rate=rule.limit_rate,
        limit_burst=rule.limit_burst,
        to_destination=rule.to_destination,
        to_source=rule.to_source,
        to_ports=rule.to_ports,
        log_prefix=rule.log_prefix,
        log_level=rule.log_level,
        reject_with=rule.reject_with,
        operation="-A"
    )
    return " ".join(args)


def restore_chains(table: str, chain_rules: Dict[str, List[str]]) -> bool:
    """
    Atomically flush and repopulate specific chains using iptables-restore --noflush.

    chain_rules: {chain_name: [list of restore-format rule lines ("-A chain ...")]}

    The -F and -A directives are committed as a single atomic kernel transaction,
    eliminating any window where chains are empty and traffic is unprotected.
    Does not touch built-in chains (INPUT, FORWARD, OUTPUT) or module chains.
    """
    if settings.mock_iptables:
        logger.debug(f"[MOCK] Would restore {len(chain_rules)} chains in table {table}")
        return True

    lines = [f"*{table}"]
    for chain in chain_rules:
        lines.append(f":{chain} - [0:0]")
    for chain, rules in chain_rules.items():
        lines.append(f"-F {chain}")
        lines.extend(rules)
    lines.append("COMMIT")
    restore_input = "\n".join(lines) + "\n"

    try:
        subprocess.run(
            ["iptables-restore", "--noflush"],
            input=restore_input,
            capture_output=True,
            text=True,
            check=True
        )
        logger.debug(f"Atomically restored chains in table {table}: {list(chain_rules.keys())}")
        return True
    except subprocess.CalledProcessError as e:
        logger.error(f"iptables-restore failed for table {table}: {e.stderr}")
        raise IptablesError(parse_iptables_error(e.stderr))
    except FileNotFoundError:
        logger.error("iptables-restore not found")
        raise IptablesError("Comando iptables-restore non trovato sul sistema")


def restore_parent_chain_jumps(
    table: str,
    parent_chain: str,
    target_chains: List[str]
) -> bool:
    """
    Atomically rebuild jump rules in a built-in chain (INPUT, FORWARD, etc.)
    using iptables-restore --noflush.

    Flushes parent_chain and re-adds jump rules to target_chains in order.
    All target_chains must already exist in iptables before calling this.
    Old jump rules are replaced atomically — no window where the chain is empty.
    """
    if settings.mock_iptables:
        logger.debug(f"[MOCK] Would restore jumps in {parent_chain} ({table}): {target_chains}")
        return True

    lines = [f"*{table}"]
    lines.append(f":{parent_chain} ACCEPT [0:0]")
    lines.append(f"-F {parent_chain}")
    for target in target_chains:
        lines.append(f"-A {parent_chain} -j {target}")
    lines.append("COMMIT")
    restore_input = "\n".join(lines) + "\n"

    try:
        subprocess.run(
            ["iptables-restore", "--noflush"],
            input=restore_input,
            capture_output=True,
            text=True,
            check=True
        )
        logger.debug(f"Atomically rebuilt jumps in {parent_chain} ({table}): {target_chains}")
        return True
    except subprocess.CalledProcessError as e:
        logger.error(f"iptables-restore failed for {parent_chain} ({table}): {e.stderr}")
        return False
    except FileNotFoundError:
        logger.error("iptables-restore not found")
        return False


def get_chain_rules(chain_name: str, table: str = "filter") -> List[str]:
    """Get all rules in a chain."""
    success, output = _run_iptables(table, ["-L", chain_name, "-n", "--line-numbers"])
    if not success:
        return []
    return output.strip().split("\n")


def ensure_jump_rule(
    source_chain: str,
    target_chain: str,
    table: str = "filter",
    position: Optional[int] = None
) -> bool:
    """
    Ensure a jump rule exists from source_chain to target_chain.
    If position is specified, insert at that position (1-indexed).
    Otherwise, insert before RETURN rule if present, or append.
    """
    if settings.mock_iptables:
        logger.debug(f"[MOCK] ensure jump {source_chain} -> {target_chain}")
        return True

    # Check if already exists using -C (exact match)
    result = subprocess.run(
        ["iptables", "-t", table, "-C", source_chain, "-j", target_chain],
        capture_output=True
    )
    if result.returncode == 0:
        logger.debug(f"Jump to {target_chain} already exists in {source_chain}")
        return True

    # Add the jump rule
    if position is not None:
        success = run_safe(table, ["-I", source_chain, str(position), "-j", target_chain])
    else:
        # Insert before RETURN if present
        return_pos = _find_return_position(table, source_chain)
        if return_pos is not None:
            success = run_safe(table, ["-I", source_chain, str(return_pos), "-j", target_chain])
        else:
            success = run_safe(table, ["-A", source_chain, "-j", target_chain])

    if success:
        logger.info(f"Added jump from {source_chain} to {target_chain} in table {table}")
    return success


def remove_jump_rule(source_chain: str, target_chain: str, table: str = "filter") -> bool:
    """Remove a jump rule from source_chain to target_chain."""
    success, _ = _run_iptables(table, ["-D", source_chain, "-j", target_chain], suppress_errors=True)
    return success


# =============================================================================
# SAFE WRAPPERS (bool return, never raise — for module use)
# =============================================================================

def run_safe(table: str, args: List[str], suppress_errors: bool = False) -> bool:
    """Execute iptables command, return bool. Never raises."""
    try:
        success, _ = _run_iptables(table, args, suppress_errors=suppress_errors)
        return success
    except IptablesError:
        return False
    except Exception as e:
        if not suppress_errors:
            logger.error(f"Unexpected iptables error: {e}")
        return False


def run_safe_with_output(
    table: str, args: List[str], suppress_errors: bool = False
) -> Tuple[bool, str]:
    """Execute iptables command, return (success, output). Never raises."""
    try:
        return _run_iptables(table, args, suppress_errors=suppress_errors)
    except IptablesError:
        return False, ""
    except Exception:
        return False, ""


# =============================================================================
# INTERFACE-FILTERED RULES (used by VPN modules)
# =============================================================================

def _find_return_position(table: str, chain: str) -> Optional[int]:
    """Find position of RETURN rule in chain (for inserting before it).

    Returns the iptables rule position (1-indexed offset from -S output,
    where line 0 is the -N/-P declaration).
    """
    if settings.mock_iptables:
        return None
    result = subprocess.run(
        ["iptables", "-t", table, "-S", chain],
        capture_output=True, text=True
    )
    if result.returncode != 0:
        return None
    lines = result.stdout.strip().split('\n')
    for i, line in enumerate(lines):
        if '-j RETURN' in line:
            return i
    return None


def ensure_interface_jump_rule(
    source_chain: str,
    target_chain: str,
    table: str = "filter",
    input_interface: Optional[str] = None,
    output_interface: Optional[str] = None
) -> bool:
    """Ensure interface-filtered jump rule exists. Inserts before RETURN."""
    if settings.mock_iptables:
        logger.debug(f"[MOCK] ensure interface jump {source_chain} -> {target_chain}")
        return True

    rule_args = []
    if input_interface:
        rule_args.extend(["-i", input_interface])
    if output_interface:
        rule_args.extend(["-o", output_interface])
    rule_args.extend(["-j", target_chain])

    # Check if already exists
    result = subprocess.run(
        ["iptables", "-t", table, "-C", source_chain] + rule_args,
        capture_output=True
    )
    if result.returncode == 0:
        return True

    # Insert before RETURN
    return_pos = _find_return_position(table, source_chain)
    if return_pos is not None:
        return run_safe(table, ["-I", source_chain, str(return_pos)] + rule_args)
    return run_safe(table, ["-A", source_chain] + rule_args)


def ensure_interface_rule(
    chain: str,
    action: str,
    table: str = "filter",
    input_interface: Optional[str] = None,
    output_interface: Optional[str] = None
) -> bool:
    """Ensure interface-filtered rule exists (e.g. -o wg0 -j ACCEPT). Inserts before RETURN."""
    if settings.mock_iptables:
        logger.debug(f"[MOCK] ensure interface rule {chain} -> {action}")
        return True

    rule_args = []
    if input_interface:
        rule_args.extend(["-i", input_interface])
    if output_interface:
        rule_args.extend(["-o", output_interface])
    rule_args.extend(["-j", action])

    result = subprocess.run(
        ["iptables", "-t", table, "-C", chain] + rule_args,
        capture_output=True
    )
    if result.returncode == 0:
        return True

    return_pos = _find_return_position(table, chain)
    if return_pos is not None:
        return run_safe(table, ["-I", chain, str(return_pos)] + rule_args)
    return run_safe(table, ["-A", chain] + rule_args)


def remove_interface_jump_rule(
    source_chain: str,
    target_chain: str,
    table: str = "filter",
    input_interface: Optional[str] = None,
    output_interface: Optional[str] = None
) -> bool:
    """Remove an interface-filtered jump rule."""
    rule_args = ["-D", source_chain]
    if input_interface:
        rule_args.extend(["-i", input_interface])
    if output_interface:
        rule_args.extend(["-o", output_interface])
    rule_args.extend(["-j", target_chain])
    return run_safe(table, rule_args, suppress_errors=True)


# =============================================================================
# RULE BUILDING
# =============================================================================

def build_rule_args(
    chain: str,
    action: str,
    protocol: Optional[str] = None,
    source: Optional[str] = None,
    destination: Optional[str] = None,
    port: Optional[str] = None,
    in_interface: Optional[str] = None,
    out_interface: Optional[str] = None,
    state: Optional[str] = None,
    comment: Optional[str] = None,
    limit_rate: Optional[str] = None,
    limit_burst: Optional[int] = None,
    to_destination: Optional[str] = None,
    to_source: Optional[str] = None,
    to_ports: Optional[str] = None,
    log_prefix: Optional[str] = None,
    log_level: Optional[str] = None,
    reject_with: Optional[str] = None,
    operation: str = "-A"
) -> List[str]:
    """
    Build iptables command arguments for a rule.
    
    Args:
        chain: Target chain name
        action: Rule action (ACCEPT, DROP, REJECT, MASQUERADE, etc.)
        protocol: Protocol (tcp, udp, icmp, all)
        source: Source IP/CIDR
        destination: Destination IP/CIDR
        port: Port or port range (e.g., "80" or "80:443")
        in_interface: Input interface
        out_interface: Output interface
        state: Connection state (NEW, ESTABLISHED, etc.)
        comment: Rule comment
        limit_rate: Rate limit (e.g., "10/second", "100/minute")
        to_destination: DNAT target
        to_source: SNAT target
        to_ports: REDIRECT/MASQUERADE target ports
        log_prefix: Log prefix
        log_level: Log level
        reject_with: Reject type (e.g. icmp-port-unreachable)
        operation: -A (append), -I (insert), -D (delete)

    Returns:
        List of command arguments
    """
    args = [operation, chain]

    if protocol:
        args.extend(["-p", protocol])

    # Source/destination may be a literal IP/CIDR or a "set:<name>" token. The
    # token translates to an ipset match against the resolved set (address
    # object/group, or per-rule aggregate) instead of a plain -s/-d.
    src_set = parse_set(source)
    if src_set:
        args.extend(["-m", "set", "--match-set", src_set, "src"])
    elif source:
        args.extend(["-s", source])

    dst_set = parse_set(destination)
    if dst_set:
        args.extend(["-m", "set", "--match-set", dst_set, "dst"])
    elif destination:
        args.extend(["-d", destination])
    
    if in_interface:
        args.extend(["-i", in_interface])
    
    if out_interface:
        args.extend(["-o", out_interface])
    
    if state:
        args.extend(["-m", "state", "--state", state])
    
    if port and protocol in ("tcp", "udp"):
        # Support both single port and range
        if "," in str(port):
             args.extend(["-m", "multiport", "--dports", str(port)])
        else:
             args.extend(["--dport", str(port)])
    
    if limit_rate:
        # Rate limiting: -m limit --limit <rate> [--limit-burst <burst>]
        args.extend(["-m", "limit", "--limit", limit_rate])
        if limit_burst:
            args.extend(["--limit-burst", str(limit_burst)])

    if comment:
        safe_comment = re.sub(r'[^a-zA-Z0-9_\-\. ]', '', comment)[:255]
        args.extend(["-m", "comment", "--comment", safe_comment])
    
    args.extend(["-j", action])

    if action == "DNAT" and to_destination:
        args.extend(["--to-destination", to_destination])
    
    if action == "SNAT" and to_source:
        args.extend(["--to-source", to_source])
        
    if action in ("REDIRECT", "MASQUERADE") and to_ports:
        args.extend(["--to-ports", to_ports])
        
    if action == "LOG":
        if log_prefix:
            # Sanitize log prefix (max 29 chars provided by user, but checks needed)
            safe_prefix = re.sub(r'[^a-zA-Z0-9_\-\. \[\]]', '', log_prefix)[:29]
            args.extend(["--log-prefix", safe_prefix])
        if log_level:
             args.extend(["--log-level", log_level])

    if action == "REJECT" and reject_with:
        args.extend(["--reject-with", reject_with])
    
    return args


def add_rule(
    table: str,
    chain: str,
    action: str,
    protocol: Optional[str] = None,
    source: Optional[str] = None,
    destination: Optional[str] = None,
    port: Optional[str] = None,
    in_interface: Optional[str] = None,
    out_interface: Optional[str] = None,
    state: Optional[str] = None,
    comment: Optional[str] = None,
    limit_rate: Optional[str] = None,
    limit_burst: Optional[int] = None,
    to_destination: Optional[str] = None,
    to_source: Optional[str] = None,
    to_ports: Optional[str] = None,
    log_prefix: Optional[str] = None,
    log_level: Optional[str] = None,
    reject_with: Optional[str] = None
) -> bool:
    """Add a firewall rule to a chain."""
    args = build_rule_args(
        chain=chain,
        action=action,
        protocol=protocol,
        source=source,
        destination=destination,
        port=port,
        in_interface=in_interface,
        out_interface=out_interface,
        state=state,
        comment=comment,
        limit_rate=limit_rate,
        limit_burst=limit_burst,
        to_destination=to_destination,
        to_source=to_source,
        to_ports=to_ports,
        log_prefix=log_prefix,
        log_level=log_level,
        reject_with=reject_with,
        operation="-A"
    )
    
    success, _ = _run_iptables(table, args)
    return success


def delete_rule_by_spec(
    table: str,
    chain: str,
    action: str,
    protocol: Optional[str] = None,
    source: Optional[str] = None,
    destination: Optional[str] = None,
    port: Optional[str] = None,
    in_interface: Optional[str] = None,
    out_interface: Optional[str] = None,
    state: Optional[str] = None,
    comment: Optional[str] = None,
    to_destination: Optional[str] = None,
    to_source: Optional[str] = None,
    to_ports: Optional[str] = None,
    log_prefix: Optional[str] = None,
    log_level: Optional[str] = None,
    reject_with: Optional[str] = None
) -> bool:
    """Delete a firewall rule by its specification."""
    args = build_rule_args(
        chain=chain,
        action=action,
        protocol=protocol,
        source=source,
        destination=destination,
        port=port,
        in_interface=in_interface,
        out_interface=out_interface,
        state=state,
        comment=comment,
        to_destination=to_destination,
        to_source=to_source,
        to_ports=to_ports,
        log_prefix=log_prefix,
        log_level=log_level,
        reject_with=reject_with,
        operation="-D"
    )
    
    success, _ = _run_iptables(table, args, suppress_errors=True)
    return success


# =============================================================================
# CONNTRACK SESSION TERMINATION
# =============================================================================

def flush_conntrack_for_rule(
    protocol: Optional[str] = None,
    source: Optional[str] = None,
    destination: Optional[str] = None,
    port: Optional[str] = None,
) -> int:
    """
    Flush conntrack entries matching the given rule criteria.

    Used after applying a DROP/REJECT rule to immediately terminate existing
    established sessions that would now be blocked by the new rule.

    Returns the number of flushed entries, or 0 if none found / error.
    """
    if settings.mock_iptables:
        logger.debug(
            f"[MOCK] Would flush conntrack: proto={protocol} src={source} "
            f"dst={destination} port={port}"
        )
        return 0

    args = ["conntrack", "-D"]

    if protocol in ("tcp", "udp", "icmp"):
        args.extend(["-p", protocol])
    if source:
        args.extend(["-s", source])
    if destination:
        args.extend(["-d", destination])
    # Only add dport filter for single numeric ports — conntrack does not support ranges
    if port and protocol in ("tcp", "udp"):
        port_str = str(port).strip()
        if re.match(r'^\d+$', port_str):
            args.extend(["--dport", port_str])

    # Safety guard: never flush the entire conntrack table with no filter
    if args == ["conntrack", "-D"]:
        logger.warning("flush_conntrack_for_rule: no filter criteria provided, skipping flush")
        return 0

    try:
        result = subprocess.run(
            args,
            capture_output=True,
            text=True,
            timeout=10
        )
        # conntrack -D exits 0 on success, 1 when no matching entries found (both are OK)
        if result.returncode in (0, 1):
            match = re.search(r'(\d+) flow entries have been deleted', result.stdout + result.stderr)
            count = int(match.group(1)) if match else 0
            logger.info(
                f"Flushed {count} conntrack entries: proto={protocol} "
                f"src={source} dst={destination} port={port}"
            )
            return count
        logger.warning(
            f"conntrack -D returned unexpected code {result.returncode}: {result.stderr.strip()}"
        )
        return 0
    except FileNotFoundError:
        logger.warning("conntrack command not found — install conntrack package for session termination")
        return 0
    except Exception as e:
        logger.error(f"Unexpected error flushing conntrack: {e}")
        return 0


# =============================================================================
# PERSISTENCE
# =============================================================================

def save_rules() -> bool:
    """
    Save current iptables rules to persistent storage.
    Uses iptables-save on Linux.
    """
    if settings.mock_iptables:
        logger.debug("[MOCK] Would save iptables rules")
        return True
    
    try:
        # Try using iptables-save via script
        result = subprocess.run(
            ["/opt/madmin/scripts/save-iptables.sh"],
            capture_output=True,
            text=True
        )
        if result.returncode == 0:
            logger.info("Iptables rules saved")
            return True
        logger.error(f"Failed to save rules: {result.stderr}")
        return False
    except FileNotFoundError:
        logger.warning("save-iptables.sh not found, trying iptables-save directly")
        try:
            result = subprocess.run(
                ["iptables-save"],
                capture_output=True,
                text=True
            )
            # Write to standard location
            with open("/etc/iptables/rules.v4", "w") as f:
                f.write(result.stdout)
            logger.info("Iptables rules saved to /etc/iptables/rules.v4")
            return True
        except Exception as e:
            logger.error(f"Failed to save rules: {e}")
            return False


# =============================================================================
# INITIALIZATION
# =============================================================================

# =============================================================================
# IPSET MANAGEMENT (used by gateway protection)
# =============================================================================

def ipset_name_for_iface(iface_name: str) -> str:
    """
    Build a deterministic ipset name for an interface.
    Example: eth1 → MADMIN_GW_ETH1, eth1.100 → MADMIN_GW_ETH1_100
    Max ipset name length is 31 chars; prefix is 10 chars, leaving 21 for iface.
    """
    sanitized = iface_name.upper().replace(".", "_").replace("-", "_")[:21]
    return f"MADMIN_GW_{sanitized}"


def _run_ipset(args: List[str], suppress_errors: bool = False) -> bool:
    """Execute an ipset command. Returns bool. Never raises."""
    if settings.mock_iptables:
        logger.debug(f"[MOCK ipset] Would execute: ipset {' '.join(args)}")
        return True
    try:
        result = subprocess.run(
            ["ipset"] + args,
            capture_output=True,
            text=True,
            check=True
        )
        return True
    except subprocess.CalledProcessError as e:
        if not suppress_errors:
            logger.error(f"ipset command failed: ipset {' '.join(args)}: {e.stderr.strip()}")
        return False
    except FileNotFoundError:
        logger.error("ipset command not found — install ipset package")
        return False


def ipset_exists(setname: str) -> bool:
    """Check if an ipset exists."""
    return _run_ipset(["list", setname, "-name"], suppress_errors=True)


def ipset_create(setname: str) -> bool:
    """Create an ipset of type hash:ip."""
    success = _run_ipset(["create", setname, "hash:ip"])
    if success:
        logger.debug(f"Created ipset {setname}")
    return success


def ipset_create_net(setname: str, maxelem: int = 131072) -> bool:
    """Create an ipset of type hash:net (CIDR ranges), used for geo-IP country sets."""
    success = _run_ipset(["create", setname, "hash:net", "maxelem", str(maxelem)])
    if success:
        logger.debug(f"Created ipset {setname} (hash:net)")
    return success


def ipset_flush(setname: str) -> bool:
    """Flush all entries from an ipset."""
    return _run_ipset(["flush", setname])


def ipset_restore_net(setname: str, cidrs: List[str]) -> bool:
    """
    Atomically (re)create a hash:net ipset and load all CIDRs in a single
    `ipset restore` transaction. Far faster than one `ipset add` subprocess per
    entry (which made loading a country list of thousands of CIDRs very slow).

    Creates the set if missing, flushes it, then adds every CIDR.
    """
    if settings.mock_iptables:
        logger.debug(f"[MOCK ipset] Would restore {len(cidrs)} CIDRs into {setname}")
        return True

    lines = [
        f"create {setname} hash:net maxelem 131072 -exist",
        f"flush {setname}",
    ]
    lines.extend(f"add {setname} {cidr}" for cidr in cidrs)
    restore_input = "\n".join(lines) + "\n"

    try:
        subprocess.run(
            ["ipset", "restore"],
            input=restore_input,
            capture_output=True,
            text=True,
            check=True,
        )
        logger.debug(f"ipset restore loaded {len(cidrs)} CIDRs into {setname}")
        return True
    except subprocess.CalledProcessError as e:
        logger.error(f"ipset restore failed for {setname}: {e.stderr.strip()}")
        return False
    except FileNotFoundError:
        logger.error("ipset command not found — install ipset package")
        return False


def ipset_create_list(setname: str, size: int = 1024) -> bool:
    """Create an ipset of type list:set (a set whose members are other ipsets)."""
    success = _run_ipset(["create", setname, "list:set", "size", str(size)])
    if success:
        logger.debug(f"Created ipset {setname} (list:set)")
    return success


def ipset_restore_list(setname: str, member_sets: List[str]) -> bool:
    """
    Atomically (re)create a list:set ipset and load all member set names in a
    single `ipset restore` transaction. Used for address groups and per-rule
    aggregates. The member sets MUST already exist (the restore fails otherwise),
    so callers build the leaf hash:net sets before the list:sets that reference
    them.

    Creates the set if missing, flushes it, then adds every member set.
    """
    if settings.mock_iptables:
        logger.debug(f"[MOCK ipset] Would restore {len(member_sets)} members into {setname}")
        return True

    lines = [
        f"create {setname} list:set size 1024 -exist",
        f"flush {setname}",
    ]
    lines.extend(f"add {setname} {m}" for m in member_sets)
    restore_input = "\n".join(lines) + "\n"

    try:
        subprocess.run(
            ["ipset", "restore"],
            input=restore_input,
            capture_output=True,
            text=True,
            check=True,
        )
        logger.debug(f"ipset restore loaded {len(member_sets)} members into {setname}")
        return True
    except subprocess.CalledProcessError as e:
        logger.error(f"ipset restore (list:set) failed for {setname}: {e.stderr.strip()}")
        return False
    except FileNotFoundError:
        logger.error("ipset command not found — install ipset package")
        return False


def ipset_add(setname: str, ip: str) -> bool:
    """Add an IP to an ipset (idempotent via --exist)."""
    return _run_ipset(["add", setname, ip, "--exist"])


def ipset_destroy(setname: str) -> bool:
    """Destroy an ipset."""
    return _run_ipset(["destroy", setname], suppress_errors=True)


def build_gateway_protect_lines(
    lan_interfaces: List[Tuple[str, List[str]]]
) -> List[str]:
    """
    Build iptables-restore format lines for MADMIN_GW_PROTECT.

    For each LAN interface, drops traffic that:
    - arrives on that interface (-i ethX)
    - is destined for a LOCAL address (-m addrtype --dst-type LOCAL)
    - but the destination is NOT in the interface's own ipset (! --match-set)

    This blocks cross-gateway access while allowing each client to reach
    its own gateway. Requires ipsets to be populated via _rebuild_gateway_ipsets().

    lan_interfaces: list of (iface_name, [ip, ...]) for each LAN interface.
    """
    chain = MADMIN_GW_PROTECT_CHAIN
    lines = []
    for iface_name, ips in lan_interfaces:
        if not ips:
            continue
        setname = ipset_name_for_iface(iface_name)
        if not ipset_exists(setname):
            logger.warning(
                f"Ipset {setname} for interface {iface_name} does not exist "
                f"(ipset not installed?); skipping gateway protection rule for this interface"
            )
            continue
        lines.append(
            f"-A {chain} -i {iface_name}"
            f" -m set ! --match-set {setname} dst"
            f" -m addrtype --dst-type LOCAL"
            f" -j DROP"
        )
    # If no LAN interfaces (or no ipsets ready): chain is empty, all traffic passes (safe default)
    return lines


def initialize_core_chains() -> bool:
    """
    Initialize all MADMIN core chains across all tables.
    
    Creates chains for:
    - filter: MADMIN_INPUT, MADMIN_OUTPUT, MADMIN_FORWARD
    - nat: MADMIN_PREROUTING, MADMIN_OUTPUT_NAT, MADMIN_POSTROUTING
    - mangle: MADMIN_*_MANGLE for all 5 chains
    - raw: MADMIN_PREROUTING_RAW, MADMIN_OUTPUT_RAW
    
    And sets up jump rules from each parent chain to its MADMIN chain.
    """
    logger.info("Initializing MADMIN core firewall chains for all tables...")
    success = True

    # Built-in iptables parent chains — only these have real jump rules from parent
    _BUILTIN_PARENTS = {"INPUT", "OUTPUT", "FORWARD", "PREROUTING", "POSTROUTING"}

    for table, chains in CHAIN_MAP.items():
        for parent_chain, madmin_chain in chains.items():
            # Create the MADMIN chain only if it doesn't exist — do NOT flush.
            # On restart, existing rules stay in place until apply_rules() replaces
            # them atomically via restore_chains(), which eliminates the flush window.
            if not create_chain(madmin_chain, table):
                logger.error(f"Failed to create chain {madmin_chain} in table {table}")
                success = False
                continue

            # Skip jump rule for virtual CHAIN_MAP keys (e.g. GW_EXCEPTIONS) —
            # these are not real iptables parent chains. Their jumps are managed
            # by rebuild_chain_jumps() in the orchestrator.
            if parent_chain not in _BUILTIN_PARENTS:
                continue

            # Ensure jump rule exists from parent to MADMIN chain
            # Try position 1 first (highest priority), fallback to append
            if not ensure_jump_rule(parent_chain, madmin_chain, table, position=1):
                logger.warning(f"Insert at position 1 failed for {madmin_chain}, trying append")
                if not ensure_jump_rule(parent_chain, madmin_chain, table, position=None):
                    logger.error(f"Failed to add jump from {parent_chain} to {madmin_chain} in table {table}")
                    success = False

    # Create gateway protection chains (not in CHAIN_MAP as they need no direct parent jump)
    for gw_chain in (MADMIN_GW_EXCEPTS_CHAIN, MADMIN_GW_PROTECT_CHAIN):
        if not create_chain(gw_chain, "filter"):
            logger.error(f"Failed to create gateway chain {gw_chain}")
            success = False
    
    if success:
        logger.info("All MADMIN core chains initialized successfully")
        logger.info(f"  filter: {list(CHAIN_MAP['filter'].values())}")
        logger.info(f"  nat: {list(CHAIN_MAP['nat'].values())}")
        logger.info(f"  mangle: {list(CHAIN_MAP['mangle'].values())}")
        logger.info(f"  raw: {list(CHAIN_MAP['raw'].values())}")
    else:
        logger.warning("Some MADMIN chains failed to initialize")
    
    return success

