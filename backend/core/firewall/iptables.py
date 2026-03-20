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
    """Delete an empty chain."""
    # First flush the chain
    flush_chain(chain_name, table)
    # Then delete it
    success, _ = _run_iptables(table, ["-X", chain_name], suppress_errors=True)
    return success


def create_or_flush_chain(chain_name: str, table: str = "filter") -> bool:
    """Create a chain if it doesn't exist, or flush it if it does."""
    if chain_exists(chain_name, table):
        return flush_chain(chain_name, table)
    else:
        return create_chain(chain_name, table)


def rule_to_restore_line(madmin_chain: str, rule) -> str:
    """Convert a MachineFirewallRule to an iptables-restore format line (-A ...)."""
    args = build_rule_args(
        chain=madmin_chain,
        action=rule.action,
        protocol=rule.protocol,
        source=rule.source,
        destination=rule.destination,
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
    Otherwise, append to the chain.
    """
    # Check if jump already exists
    success, output = _run_iptables(table, ["-L", source_chain, "-n"])
    if success and target_chain in output:
        logger.debug(f"Jump to {target_chain} already exists in {source_chain}")
        return True
    
    # Add the jump rule
    if position is not None:
        args = ["-I", source_chain, str(position), "-j", target_chain]
    else:
        args = ["-A", source_chain, "-j", target_chain]
    
    success, _ = _run_iptables(table, args)
    if success:
        logger.info(f"Added jump from {source_chain} to {target_chain} in table {table}")
    return success


def remove_jump_rule(source_chain: str, target_chain: str, table: str = "filter") -> bool:
    """Remove a jump rule from source_chain to target_chain."""
    success, _ = _run_iptables(table, ["-D", source_chain, "-j", target_chain], suppress_errors=True)
    return success


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
    
    if source:
        args.extend(["-s", source])
    
    if destination:
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
    
    for table, chains in CHAIN_MAP.items():
        for parent_chain, madmin_chain in chains.items():
            # Create the MADMIN chain only if it doesn't exist — do NOT flush.
            # On restart, existing rules stay in place until apply_rules() replaces
            # them atomically via restore_chains(), which eliminates the flush window.
            if not create_chain(madmin_chain, table):
                logger.error(f"Failed to create chain {madmin_chain} in table {table}")
                success = False
                continue

            # Ensure jump rule exists from parent to MADMIN chain
            # Try position 1 first (highest priority), fallback to append
            if not ensure_jump_rule(parent_chain, madmin_chain, table, position=1):
                logger.warning(f"Insert at position 1 failed for {madmin_chain}, trying append")
                if not ensure_jump_rule(parent_chain, madmin_chain, table, position=None):
                    logger.error(f"Failed to add jump from {parent_chain} to {madmin_chain} in table {table}")
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

