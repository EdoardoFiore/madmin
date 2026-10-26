"""
Reverse Proxy on_startup hook.

Desired-state reconciliation for the dedicated nginx instance:
- migrates installs that still have vhosts in the system nginx (shared layout
  used before the dedicated instance) and installs the instance;
- re-renders every managed file that no longer matches the DB/templates;
- starts the instance if it is down, otherwise reloads it only if something
  changed.
"""
import logging
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger("hook_on_startup")


async def run(session: AsyncSession):
    from modules.reverseproxy import service as svc
    from core.services.service import SystemdService

    blocked, reason = svc.is_blocked()
    if blocked:
        logger.info("Reverse Proxy on_startup: module blocked (%s), skipping", reason)
        return

    unit = f"{svc.SERVICE_NAME}.service"
    if unit not in SystemdService.ALLOWED_SERVICES:
        SystemdService.ALLOWED_SERVICES.append(unit)

    if svc.migrate_legacy_layout():
        logger.info("Reverse Proxy on_startup: legacy vhosts removed from system nginx")
    try:
        svc.install_instance()
    except Exception as e:
        logger.error("Reverse Proxy on_startup: instance setup failed: %s", e)
        return

    ok, msg = await svc.sync_all(session)
    if ok:
        logger.info("Reverse Proxy on_startup: %s", msg)
    else:
        logger.error("Reverse Proxy on_startup: sync failed: %s", msg)
