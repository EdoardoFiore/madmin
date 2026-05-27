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
    from sqlalchemy import select
    from modules.reverseproxy.models import RevproxyHost, RevproxyAccessList

    async with async_session_maker() as session:
        acls = (await session.execute(select(RevproxyAccessList.id))).scalars().all()
        hosts = (await session.execute(select(RevproxyHost.id))).scalars().all()

        for acl_id in acls:
            ok, msg = await svc.apply_access_list(session, acl_id)
            if not ok:
                logger.warning("apply_access_list(%s) failed: %s", acl_id, msg)
        for hid in hosts:
            ok, msg = await svc.apply_host(session, hid)
            if not ok:
                logger.warning("apply_host(%s) failed: %s", hid, msg)

    ok, msg = svc.nginx_reload()
    if not ok:
        logger.warning("nginx reload after restore failed: %s", msg)

    logger.info("Reverse Proxy post_restore: complete")
    return True
