"""
WireGuard Module - on_disable Hook

Executed when the module is deactivated:
1. Stop all WireGuard interfaces
2. Remove all iptables chains (instance, group, client, module)
3. Remove generated config files from /etc/wireguard/

Does NOT remove:
- /etc/wireguard/ directory itself (post_install recreates it)
- IP forwarding sysctl config (shared, innocuous)
- apt packages (always pre-installed)
"""
import subprocess
import logging
from pathlib import Path

logger = logging.getLogger(__name__)


async def run():
    """on_disable hook for WireGuard module."""
    logger.info("Running WireGuard on_disable hook")
    
    # 1. Stop all WireGuard interfaces
    try:
        result = subprocess.run(
            ["wg", "show", "interfaces"],
            capture_output=True,
            text=True
        )
        
        if result.returncode == 0 and result.stdout.strip():
            interfaces = result.stdout.strip().split('\n')
            for iface in interfaces:
                if iface:
                    logger.info(f"Stopping WireGuard interface: {iface}")
                    subprocess.run(["wg-quick", "down", iface], capture_output=True)
    except Exception as e:
        logger.warning(f"Error stopping interfaces: {e}")
    
    # 2. Remove all WireGuard iptables chains
    _cleanup_iptables_chains()
    
    # 3. Remove generated config files from /etc/wireguard/
    wg_dir = Path("/etc/wireguard")
    if wg_dir.exists():
        for conf_file in wg_dir.glob("*.conf"):
            try:
                conf_file.unlink()
                logger.info(f"Removed config: {conf_file}")
            except Exception as e:
                logger.warning(f"Failed to remove {conf_file}: {e}")
    
    logger.info("WireGuard on_disable complete")
    return True


def _cleanup_iptables_chains():
    """Remove all WireGuard-related iptables chains from all tables."""
    for table in ["filter", "nat"]:
        try:
            result = subprocess.run(
                ["iptables", "-t", table, "-L", "-n"],
                capture_output=True,
                text=True
            )
            
            chains_to_remove = []
            for line in result.stdout.split('\n'):
                # Match WG_*, MOD_WG_*, WG_GRP_*, WG_CLI_*
                if line.startswith('Chain '):
                    chain_name = line.split()[1]
                    if chain_name.startswith(('WG_', 'MOD_WG_')):
                        chains_to_remove.append(chain_name)
            
            # Remove references first, then flush and delete
            for chain in chains_to_remove:
                _remove_references_to_chain(table, chain)
                subprocess.run(["iptables", "-t", table, "-F", chain], capture_output=True)
            
            for chain in chains_to_remove:
                subprocess.run(["iptables", "-t", table, "-X", chain], capture_output=True)
                logger.info(f"Removed chain: {chain} ({table})")
                
        except Exception as e:
            logger.warning(f"Error cleaning up {table} table: {e}")


def _remove_references_to_chain(table: str, chain_name: str):
    """Remove all jump rules pointing to a chain."""
    try:
        result = subprocess.run(
            ["iptables", "-t", table, "-S"],
            capture_output=True,
            text=True
        )
        
        for line in result.stdout.split('\n'):
            if f"-j {chain_name}" in line and line.startswith('-A '):
                parts = line.split()
                delete_cmd = ["iptables", "-t", table] + ["-D" if p == "-A" else p for p in parts]
                subprocess.run(delete_cmd, capture_output=True)
    except Exception as e:
        logger.debug(f"Error removing references to {chain_name}: {e}")
