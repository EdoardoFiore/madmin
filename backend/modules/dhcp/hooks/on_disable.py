"""
DHCP Module - on_disable Hook

Executed when the module is deactivated:
1. Stop and disable isc-dhcp-server service
2. Reset dhcpd.conf to empty header
3. Reset /etc/default/isc-dhcp-server to empty interfaces

Does NOT remove:
- /etc/dhcp/ directory
- Lease files
- apt packages
"""
import subprocess
import logging
from pathlib import Path

logger = logging.getLogger(__name__)


def run():
    """on_disable hook for DHCP module."""
    logger.info("Running DHCP on_disable hook")
    
    # 1. Stop and disable isc-dhcp-server
    try:
        subprocess.run(
            ["systemctl", "stop", "isc-dhcp-server"],
            capture_output=True, text=True, timeout=15
        )
        logger.info("isc-dhcp-server stopped")
    except Exception as e:
        logger.warning(f"Failed to stop service: {e}")
    
    try:
        subprocess.run(
            ["systemctl", "disable", "isc-dhcp-server"],
            capture_output=True, text=True
        )
        logger.info("isc-dhcp-server disabled")
    except Exception as e:
        logger.warning(f"Could not disable service: {e}")
    
    # 2. Reset dhcpd.conf to initial empty state
    conf_path = Path("/etc/dhcp/dhcpd.conf")
    try:
        conf_path.write_text(
            "# DHCP Server Configuration\n"
            "# Managed by MADMIN DHCP Module\n"
            "# Configuration will be generated when subnets are created.\n"
            "\n"
            "# No subnets configured yet.\n"
        )
        logger.info(f"Reset {conf_path} to initial state")
    except Exception as e:
        logger.warning(f"Failed to reset config: {e}")
    
    # 3. Reset defaults file to empty interfaces
    defaults_path = Path("/etc/default/isc-dhcp-server")
    try:
        defaults_path.write_text('INTERFACESv4=""\nINTERFACESv6=""\n')
        logger.info(f"Reset {defaults_path} to empty interfaces")
    except Exception as e:
        logger.warning(f"Failed to reset defaults: {e}")
    
    logger.info("DHCP on_disable complete")
    return True
