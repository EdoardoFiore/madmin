"""
DHCP Module - Pre-uninstall Hook

Executes before module uninstallation:
1. Stop isc-dhcp-server service
2. Backup current configuration
"""
import subprocess
import logging
import shutil
from pathlib import Path
from datetime import datetime

logger = logging.getLogger(__name__)


def run():
    """
    Pre-uninstallation cleanup for DHCP module.

    This hook is executed before:
    - Module files are removed
    - Database tables are dropped
    """
    logger.info("Running DHCP pre-uninstall hook...")
    errors = []

    # 1. Stop isc-dhcp-server
    logger.info("Stopping isc-dhcp-server...")
    try:
        subprocess.run(
            ["systemctl", "stop", "isc-dhcp-server"],
            capture_output=True, text=True, timeout=15
        )
        logger.info("isc-dhcp-server stopped")
    except Exception as e:
        errors.append(f"Failed to stop service: {e}")

    # 2. Disable isc-dhcp-server
    try:
        subprocess.run(
            ["systemctl", "disable", "isc-dhcp-server"],
            capture_output=True, text=True
        )
        logger.info("isc-dhcp-server disabled")
    except Exception as e:
        logger.warning(f"Could not disable service: {e}")

    # 3. Backup current config
    conf_path = Path("/etc/dhcp/dhcpd.conf")
    if conf_path.exists():
        try:
            timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
            backup_path = conf_path.with_name(
                f"dhcpd.conf.madmin_backup_{timestamp}"
            )
            shutil.copy2(conf_path, backup_path)
            logger.info(f"Config backed up to {backup_path}")
        except Exception as e:
            errors.append(f"Failed to backup config: {e}")

    # 4. Clean up lease files
    for lease_file in [
        Path("/var/lib/dhcp/dhcpd.leases"),
        Path("/var/lib/dhcp/dhcpd.leases~"),
    ]:
        if lease_file.exists():
            try:
                lease_file.unlink()
                logger.info(f"Removed {lease_file}")
            except Exception as e:
                logger.warning(f"Could not remove {lease_file}: {e}")

    # Report results
    if errors:
        for err in errors:
            logger.error(f"Pre-uninstall error: {err}")
        logger.warning("DHCP pre-uninstall completed with warnings")
    else:
        logger.info("DHCP pre-uninstall completed successfully")

    return True
