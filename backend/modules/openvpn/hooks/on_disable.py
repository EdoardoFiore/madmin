"""
OpenVPN Module - on_disable Hook

Executed when the module is deactivated:
1. Stop and disable all openvpn-server@* services
2. Remove all iptables chains (instance, group, module)
3. Remove generated config files (server.conf, CCD)

Does NOT remove:
- /etc/openvpn/server/*/pki/ directories (PKI is irrecoverable)
- /etc/openvpn/server/ directory itself
- IP forwarding sysctl config
- apt packages
"""
import subprocess
import logging
from pathlib import Path

logger = logging.getLogger(__name__)


async def run():
    """on_disable hook for OpenVPN module."""
    logger.info("Running OpenVPN on_disable hook")
    
    # 1. Stop and disable all OpenVPN instances
    try:
        result = subprocess.run(
            ["systemctl", "list-units", "--type=service", "--state=running",
             "--plain", "--no-legend"],
            capture_output=True,
            text=True
        )
        for line in result.stdout.split('\n'):
            if 'openvpn-server@' in line:
                service = line.split()[0]
                subprocess.run(["systemctl", "stop", service], capture_output=True)
                subprocess.run(["systemctl", "disable", service], capture_output=True)
                logger.info(f"Stopped and disabled service: {service}")
    except Exception as e:
        logger.warning(f"Error stopping services: {e}")
    
    # 2. Remove all OpenVPN iptables chains
    _cleanup_iptables_chains()
    
    # 3. Remove generated config files but KEEP PKI
    server_dir = Path("/etc/openvpn/server")
    if server_dir.exists():
        for instance_dir in server_dir.iterdir():
            if not instance_dir.is_dir():
                continue
            
            # Remove server.conf
            server_conf = instance_dir / "server.conf"
            if server_conf.exists():
                try:
                    server_conf.unlink()
                    logger.info(f"Removed {server_conf}")
                except Exception as e:
                    logger.warning(f"Failed to remove {server_conf}: {e}")
            
            # Remove CCD directory (client-config-dir)
            ccd_dir = instance_dir / "ccd"
            if ccd_dir.exists():
                try:
                    import shutil
                    shutil.rmtree(ccd_dir)
                    logger.info(f"Removed CCD directory: {ccd_dir}")
                except Exception as e:
                    logger.warning(f"Failed to remove {ccd_dir}: {e}")
            
            # PKI directory is preserved intentionally
            pki_dir = instance_dir / "pki"
            if pki_dir.exists():
                logger.info(f"Preserving PKI directory: {pki_dir}")
    
    # Remove .conf files from /etc/openvpn/ root
    openvpn_root = Path("/etc/openvpn")
    if openvpn_root.exists():
        for conf_file in openvpn_root.glob("*.conf"):
            try:
                conf_file.unlink()
                logger.info(f"Removed config: {conf_file}")
            except Exception as e:
                logger.warning(f"Failed to remove {conf_file}: {e}")
    
    logger.info("OpenVPN on_disable complete")
    return True


def _cleanup_iptables_chains():
    """Remove all OpenVPN-related iptables chains from all tables."""
    for table in ["filter", "nat"]:
        try:
            result = subprocess.run(
                ["iptables", "-t", table, "-L", "-n"],
                capture_output=True, text=True
            )
            
            chains_to_remove = []
            for line in result.stdout.split('\n'):
                if line.startswith('Chain '):
                    chain_name = line.split()[1]
                    if chain_name.startswith(('OVPN_', 'MOD_OVPN_')):
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
