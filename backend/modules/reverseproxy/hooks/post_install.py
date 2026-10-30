"""
Reverse Proxy Module - Post Install Hook

- Removes vhosts left in the system nginx by the old shared layout.
- Verifies that no other service/rule occupies ports 80/443.
- Installs the dedicated nginx instance (config, systemd unit, logrotate).
- Whitelists the instance for systemd control.
- Idempotent: regenerates all DB-tracked vhosts on re-enable and starts the
  instance.
Note: firewall rules (80/443) are applied by router.py at import time.
"""
import asyncio
import logging

logger = logging.getLogger(__name__)


async def run():
    logger.info("Reverse Proxy post-install: start")

    from modules.reverseproxy import service as svc
    from core.database import async_session_maker
    from core.services.service import SystemdService

    # 1) Legacy layout: vhosts in the system nginx would hold ports 80/443
    if await asyncio.to_thread(svc.migrate_legacy_layout):
        logger.info("Reverse Proxy post-install: legacy vhosts removed from system nginx")

    # 2) Preflight: port conflicts
    async with async_session_maker() as session:
        preflight = await svc.preflight_check(session)

    if not preflight["ok"]:
        details = "; ".join(c["detail"] for c in preflight["conflicts"])
        reason = f"Porte 80/443 in conflitto: {details}"
        logger.error("Reverse Proxy post-install: %s", reason)
        svc.write_sentinel(reason)
        return False

    svc.clear_sentinel()

    # 3) Dedicated nginx instance: directories, nginx.conf, ACME vhost,
    #    systemd unit (enabled at boot), logrotate policy and certbot
    #    deploy hook (reloads the instance after every renewal)
    try:
        await asyncio.to_thread(svc.install_instance)
    except Exception as e:
        logger.error("Reverse Proxy post-install: instance setup failed: %s", e)
        return False
    logger.info("Reverse Proxy post-install: instance %s installed", svc.SERVICE_NAME)

    # 4) Whitelist the instance for systemd control
    unit = f"{svc.SERVICE_NAME}.service"
    if unit not in SystemdService.ALLOWED_SERVICES:
        SystemdService.ALLOWED_SERVICES.append(unit)

    # 5) Firewall rules (80/443) are applied by router.py at import time on
    #    every startup. post_install runs before register_module_chains() which
    #    would flush any rules added here, so rule setup belongs in the router.

    # 6) Render every DB-tracked vhost/ACL (re-enable case) and start the instance
    async with async_session_maker() as session:
        ok, msg = await svc.sync_all(session)
    if not ok:
        logger.error("Reverse Proxy post-install: %s", msg)
        return False

    logger.info("Reverse Proxy post-install: complete (%s)", msg)
    return True
