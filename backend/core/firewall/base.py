"""
MADMIN Firewall Backend — Abstract Interface

Defines the FirewallBackend protocol shared by IptablesBackend and NftablesBackend.
Chain name constants are defined here and re-exported from iptables.py for
backward compatibility with existing module code.
"""
from abc import ABC, abstractmethod
from typing import Dict, List, Optional, Tuple

# ---------------------------------------------------------------------------
# Shared MADMIN chain names — identical across backends
# ---------------------------------------------------------------------------

# Filter
MADMIN_INPUT_CHAIN = "MADMIN_INPUT"
MADMIN_OUTPUT_CHAIN = "MADMIN_OUTPUT"
MADMIN_FORWARD_CHAIN = "MADMIN_FORWARD"

# Gateway protection (filter-only, jumped from INPUT via rebuild_chain_jumps)
MADMIN_GW_EXCEPTS_CHAIN = "MADMIN_GW_EXCEPTS"
MADMIN_GW_PROTECT_CHAIN = "MADMIN_GW_PROTECT"

# NAT
MADMIN_PREROUTING_NAT_CHAIN = "MADMIN_PREROUTING"
MADMIN_POSTROUTING_NAT_CHAIN = "MADMIN_POSTROUTING"
MADMIN_OUTPUT_NAT_CHAIN = "MADMIN_OUTPUT_NAT"

# Mangle
MADMIN_PREROUTING_MANGLE_CHAIN = "MADMIN_PREROUTING_MANGLE"
MADMIN_INPUT_MANGLE_CHAIN = "MADMIN_INPUT_MANGLE"
MADMIN_FORWARD_MANGLE_CHAIN = "MADMIN_FORWARD_MANGLE"
MADMIN_OUTPUT_MANGLE_CHAIN = "MADMIN_OUTPUT_MANGLE"
MADMIN_POSTROUTING_MANGLE_CHAIN = "MADMIN_POSTROUTING_MANGLE"

# Raw
MADMIN_PREROUTING_RAW_CHAIN = "MADMIN_PREROUTING_RAW"
MADMIN_OUTPUT_RAW_CHAIN = "MADMIN_OUTPUT_RAW"

# ---------------------------------------------------------------------------
# Logical chain map: (iptables-table, parent-chain) → MADMIN chain name
# Shared by both backends — MADMIN chain names are backend-agnostic.
# "GW_EXCEPTIONS" is a virtual key: rules land in MADMIN_GW_EXCEPTS but the
# jump from INPUT is managed by rebuild_chain_jumps(), not initialize_core_chains().
# ---------------------------------------------------------------------------
CHAIN_MAP: Dict[str, Dict[str, str]] = {
    "filter": {
        "INPUT": MADMIN_INPUT_CHAIN,
        "OUTPUT": MADMIN_OUTPUT_CHAIN,
        "FORWARD": MADMIN_FORWARD_CHAIN,
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


class FirewallError(Exception):
    """Backend-agnostic firewall error."""
    pass


class FirewallBackend(ABC):
    """
    Abstract firewall backend.

    Orchestrator uses this interface exclusively; concrete implementations are
    IptablesBackend (iptables.py) and NftablesBackend (nftables.py).
    Modules that need low-level firewall ops (e.g. ensure_interface_jump_rule)
    still import iptables.py directly until per-backend module support lands.
    """

    # ------------------------------------------------------------------
    # Shared data — same for all backends
    # ------------------------------------------------------------------

    @property
    def chain_map(self) -> Dict[str, Dict[str, str]]:
        return CHAIN_MAP

    @property
    def gw_protect_chain(self) -> str:
        return MADMIN_GW_PROTECT_CHAIN

    @property
    def gw_excepts_chain(self) -> str:
        return MADMIN_GW_EXCEPTS_CHAIN

    def get_madmin_chain(self, table: str, parent_chain: str) -> Optional[str]:
        return CHAIN_MAP.get(table, {}).get(parent_chain)

    # ------------------------------------------------------------------
    # Initialization
    # ------------------------------------------------------------------

    @abstractmethod
    def initialize_core_chains(self) -> bool:
        """Create all MADMIN core chains and wire parent → MADMIN jumps."""

    # ------------------------------------------------------------------
    # Chain operations
    # ------------------------------------------------------------------

    @abstractmethod
    def chain_exists(self, chain_name: str, table: str = "filter") -> bool: ...

    @abstractmethod
    def create_chain(self, chain_name: str, table: str = "filter") -> bool:
        """Create chain if absent; no-op if already exists."""

    @abstractmethod
    def create_or_flush_chain(self, chain_name: str, table: str = "filter") -> bool:
        """Create chain if absent, otherwise flush its rules."""

    @abstractmethod
    def delete_chain(self, chain_name: str, table: str = "filter") -> bool:
        """Flush then delete chain; tolerant of non-existent chains."""

    @abstractmethod
    def remove_jump_rule(
        self, source_chain: str, target_chain: str, table: str = "filter"
    ) -> bool: ...

    # ------------------------------------------------------------------
    # Atomic rule application
    # ------------------------------------------------------------------

    @abstractmethod
    def restore_chains(
        self, table: str, chain_rules: Dict[str, List[str]]
    ) -> bool:
        """
        Atomically flush + repopulate chains.
        chain_rules: {chain_name: [backend-format rule lines]}
        """

    @abstractmethod
    def restore_parent_chain_jumps(
        self, table: str, parent_chain: str, target_chains: List[str]
    ) -> bool:
        """
        Atomically rebuild jump rules in a built-in/dispatcher chain.
        Flushes parent_chain and re-adds -j <target> in order.
        """

    # ------------------------------------------------------------------
    # Rule formatting (backend-specific syntax)
    # ------------------------------------------------------------------

    @abstractmethod
    def rule_to_restore_line(self, madmin_chain: str, rule) -> str:
        """Convert a MachineFirewallRule to a backend-format rule line."""

    # ------------------------------------------------------------------
    # Gateway protection
    # ------------------------------------------------------------------

    @abstractmethod
    def build_gateway_protect_lines(
        self, lan_interfaces: List[Tuple[str, List[str]]]
    ) -> List[str]:
        """Build backend-format lines for the MADMIN_GW_PROTECT chain."""

    # ------------------------------------------------------------------
    # Set operations  (ipset on iptables backend; nft set on nftables)
    # ------------------------------------------------------------------

    @abstractmethod
    def set_name_for_iface(self, iface_name: str) -> str: ...

    @abstractmethod
    def set_exists(self, setname: str) -> bool: ...

    @abstractmethod
    def set_create(self, setname: str) -> bool: ...

    @abstractmethod
    def set_flush(self, setname: str) -> bool: ...

    @abstractmethod
    def set_add(self, setname: str, ip: str) -> bool: ...

    @abstractmethod
    def set_destroy(self, setname: str) -> bool: ...

    # ------------------------------------------------------------------
    # Conntrack session termination
    # ------------------------------------------------------------------

    @abstractmethod
    def flush_conntrack_for_rule(
        self,
        protocol: Optional[str] = None,
        source: Optional[str] = None,
        destination: Optional[str] = None,
        port: Optional[str] = None,
    ) -> int:
        """Flush conntrack entries matching rule criteria. Returns count flushed."""
