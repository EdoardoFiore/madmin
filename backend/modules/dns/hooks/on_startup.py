"""
DNS on_startup hook.

Restores the bind9 service if it was running before the last restart
(desired-state reconciliation via DnsSettings.service_enabled). Reuses
dns_service.apply_config so config + firewall + service are brought up exactly
as the /apply endpoint does.
"""
import logging
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger("hook_on_startup")


async def run(session: AsyncSession):
    """Start bind9 if its persisted desired state is enabled."""
    from modules.dns.service import dns_service

    settings = await dns_service.get_or_create_settings(session)
    if not settings.service_enabled:
        logger.info("DNS on_startup: service not enabled, nothing to restore")
        return

    success, msg = await dns_service.apply_config(session)
    if success:
        logger.info("DNS on_startup: bind9 restored")
    else:
        logger.error(f"DNS on_startup: failed to restore bind9: {msg}")
