"""
Agent on_disable hook.
Closes WS, revokes local enrollment, removes all pushed SSH keys + iptables rules.
"""
import logging

logger = logging.getLogger(__name__)


async def run():
    logger.info("Hub Agent on_disable: stopping agent tasks and revoking enrollment")

    # 1. Stop WS client task
    try:
        from modules.agent.tasks import stop_agent_tasks
        await stop_agent_tasks()
    except Exception as e:
        logger.warning(f"Failed to stop agent tasks: {e}")

    # 2. Revoke all pushed SSH keys
    try:
        from core.database import async_session_maker
        from sqlalchemy import select
        from modules.agent.models import PushedSSHKey
        from modules.agent.service.ssh import revoke_key

        async with async_session_maker() as session:
            result = await session.execute(
                select(PushedSSHKey).where(PushedSSHKey.active == True)
            )
            keys = result.scalars().all()

        for k in keys:
            try:
                await revoke_key(k.assignment_id)
            except Exception as e:
                logger.warning(f"Failed to revoke SSH key {k.assignment_id}: {e}")

        logger.info(f"Revoked {len(keys)} pushed SSH keys")
    except Exception as e:
        logger.warning(f"SSH key cleanup failed: {e}")

    # 3. Revoke local enrollment (notify Hub best-effort)
    try:
        from modules.agent.service.enrollment import revoke_local
        await revoke_local(notify_hub=True)
    except Exception as e:
        logger.warning(f"Enrollment revoke failed: {e}")

    logger.info("Hub Agent on_disable complete")
    return True
