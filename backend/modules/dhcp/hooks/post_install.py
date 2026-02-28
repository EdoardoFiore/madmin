"""
DHCP Module - Post-install Hook

Executes after module installation to configure system for DHCP:
1. Create /etc/dhcp directory
2. Stop any running isc-dhcp-server to avoid conflicts
3. Write initial empty config header
"""
import subprocess
import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)


def run():
    """
    Post-installation system configuration for DHCP.

    This hook is executed after:
    - apt packages are installed (isc-dhcp-server)
    - Database migrations are complete
    """
    logger.info("Running DHCP post-install hook...")
    errors = []

    # 1. Create /etc/dhcp directory
    dhcp_dir = Path("/etc/dhcp")
    try:
        dhcp_dir.mkdir(parents=True, exist_ok=True)
        logger.info(f"Ensured {dhcp_dir} exists")
    except PermissionError:
        errors.append(f"Permission denied creating {dhcp_dir}")
    except Exception as e:
        errors.append(f"Failed to create {dhcp_dir}: {e}")

    # 2. Stop isc-dhcp-server if running (avoid conflicts during setup)
    try:
        subprocess.run(
            ["systemctl", "stop", "isc-dhcp-server"],
            capture_output=True, text=True
        )
        logger.info("Stopped isc-dhcp-server (if was running)")
    except Exception as e:
        logger.warning(f"Could not stop isc-dhcp-server: {e}")

    # 3. Write initial config header
    conf_path = Path("/etc/dhcp/dhcpd.conf")
    try:
        if not conf_path.exists() or conf_path.stat().st_size == 0:
            conf_path.write_text(
                "# DHCP Server Configuration\n"
                "# Managed by MADMIN DHCP Module\n"
                "# Configuration will be generated when subnets are created.\n"
                "\n"
                "# No subnets configured yet.\n"
            )
            logger.info(f"Wrote initial config to {conf_path}")
    except PermissionError:
        errors.append(f"Permission denied writing to {conf_path}")
    except Exception as e:
        errors.append(f"Failed to write initial config: {e}")

    # 4. Create leases directory
    leases_dir = Path("/var/lib/dhcp")
    try:
        leases_dir.mkdir(parents=True, exist_ok=True)
        leases_file = leases_dir / "dhcpd.leases"
        if not leases_file.exists():
            leases_file.touch()
            logger.info(f"Created empty leases file {leases_file}")
    except PermissionError:
        errors.append(f"Permission denied creating {leases_dir}")
    except Exception as e:
        errors.append(f"Failed to create leases dir: {e}")

    # 5. Configure defaults file
    defaults_path = Path("/etc/default/isc-dhcp-server")
    try:
        # Set empty interfaces initially (will be updated when subnets are created)
        defaults_path.write_text('INTERFACESv4=""\nINTERFACESv6=""\n')
        logger.info(f"Wrote defaults to {defaults_path}")
    except PermissionError:
        errors.append(f"Permission denied writing to {defaults_path}")
    except Exception as e:
        errors.append(f"Failed to write defaults: {e}")

    # Report results
    if errors:
        for err in errors:
            logger.error(f"Post-install error: {err}")
        logger.warning("DHCP post-install completed with warnings")
    else:
        logger.info("DHCP post-install completed successfully")

    return True
