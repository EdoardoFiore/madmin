"""
Reverse Proxy Module - post_restore Hook

After a config backup is restored, the DB rows exist again but the on-disk
htpasswd files and vhosts don't. Re-render everything from DB state.
"""
import logging

logger = logging.getLogger(__name__)


async def run(session):
    logger.info("Reverse Proxy post_restore: start")

    from modules.reverseproxy import service as svc

    # _execute_restore_hook passes the import's session, as to every module
    ok, msg = await svc.sync_all(session)
    if not ok:
        logger.warning("Reverse Proxy post_restore: %s", msg)

    logger.info("Reverse Proxy post_restore: complete")
    return True
