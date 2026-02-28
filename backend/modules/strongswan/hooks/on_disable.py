"""
strongSwan Module - on_disable Hook

Executed when the module is deactivated:
1. Terminate all active IPsec tunnels
2. Remove all iptables chains (per-tunnel, module)
3. Remove MADMIN-managed config files (madmin_*.conf)
4. Reload swanctl to clear in-memory state
5. Stop strongswan service

Does NOT remove:
- Certificates (/etc/swanctl/x509*, /etc/swanctl/private/)
- /etc/swanctl/ directory structure
- charon-systemd.conf logging config
- IP forwarding sysctl config
- apt packages
"""
import subprocess
import logging
from pathlib import Path

logger = logging.getLogger(__name__)


async def run():
    """on_disable hook for strongSwan module."""
    logger.info("Running strongSwan on_disable hook")
    
    # 1. Terminate all active tunnels
    try:
        result = subprocess.run(
            ['swanctl', '--terminate', '--ike', '*'],
            capture_output=True,
            text=True
        )
        if result.returncode == 0:
            logger.info("All tunnels terminated")
        else:
            logger.info(f"Tunnel termination result: {result.stderr.strip()}")
    except FileNotFoundError:
        logger.warning("swanctl not found, skipping tunnel termination")
    except Exception as e:
        logger.warning(f"Failed to terminate tunnels: {e}")
    
    # 2. Remove all IPsec iptables chains
    _cleanup_iptables_chains()
    
    # 3. Remove MADMIN-managed config files only
    conf_dir = Path("/etc/swanctl/conf.d")
    if conf_dir.exists():
        for conf_file in conf_dir.glob("madmin_*.conf"):
            try:
                conf_file.unlink()
                logger.info(f"Removed {conf_file}")
            except Exception as e:
                logger.warning(f"Failed to remove {conf_file}: {e}")
    
    # 4. Reload swanctl to clear in-memory connections
    try:
        subprocess.run(
            ['swanctl', '--load-all'],
            capture_output=True,
            text=True
        )
        logger.info("swanctl configuration reloaded")
    except FileNotFoundError:
        logger.warning("swanctl not found, skipping reload")
    except Exception as e:
        logger.warning(f"Failed to reload swanctl: {e}")
    
    # 5. Stop strongswan service (don't disable — might be re-activated)
    try:
        subprocess.run(
            ['systemctl', 'stop', 'strongswan'],
            capture_output=True,
            text=True
        )
        logger.info("strongswan service stopped")
    except Exception as e:
        logger.warning(f"Failed to stop strongswan: {e}")
    
    logger.info("strongSwan on_disable complete")
    return True


def _cleanup_iptables_chains():
    """Remove all IPsec-related iptables chains from all tables."""
    for table in ["filter", "nat"]:
        try:
            result = subprocess.run(
                ['iptables', '-t', table, '-L', '-n'],
                capture_output=True,
                text=True
            )
            
            chains_to_remove = []
            for line in result.stdout.split('\n'):
                if line.startswith('Chain '):
                    chain_name = line.split()[1]
                    if chain_name.startswith(('IPSEC_', 'MOD_IPSEC_')):
                        chains_to_remove.append(chain_name)
            
            for chain in chains_to_remove:
                _remove_references_to_chain(table, chain)
                subprocess.run(['iptables', '-t', table, '-F', chain], capture_output=True)
            
            for chain in chains_to_remove:
                subprocess.run(['iptables', '-t', table, '-X', chain], capture_output=True)
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
