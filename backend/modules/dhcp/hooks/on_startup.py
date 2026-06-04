"""
DHCP on_startup hook.

Restores the isc-dhcp-server service if it was running before the last restart
(desired-state reconciliation via DhcpSettings.service_enabled). Reuses
dhcp_service.apply_config so config + service are brought up exactly as the
/apply endpoint does.
"""
import logging
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger("hook_on_startup")


async def run(session: AsyncSession):
    """Start isc-dhcp-server if its persisted desired state is enabled."""
    from modules.dhcp.service import dhcp_service

    settings = await dhcp_service.get_or_create_settings(session)
    if not settings.service_enabled:
        logger.info("DHCP on_startup: service not enabled, nothing to restore")
        return

    success, msg = await dhcp_service.apply_config(session)
    if success:
        logger.info("DHCP on_startup: isc-dhcp-server restored")
    else:
        logger.error(f"DHCP on_startup: failed to restore isc-dhcp-server: {msg}")
