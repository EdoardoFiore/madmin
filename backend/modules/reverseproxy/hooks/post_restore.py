"""
Reverse Proxy Module - post_restore Hook

After a config backup is restored, the DB rows exist again but the on-disk
htpasswd files and vhosts don't. Re-render everything from DB state.
"""
import logging

logger = logging.getLogger(__name__)


async def run():
    logger.info("Reverse Proxy post_restore: start")

    from modules.reverseproxy import service as svc
    from core.database import async_session_maker

    async with async_session_maker() as session:
        ok, msg = await svc.sync_all(session)
    if not ok:
        logger.warning("Reverse Proxy post_restore: %s", msg)

    logger.info("Reverse Proxy post_restore: complete")
    return True
