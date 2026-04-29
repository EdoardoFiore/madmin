"""
Background tasks for the agent module.
Registered in madmin's lifespan when module is enabled.
"""
import asyncio
import logging

logger = logging.getLogger(__name__)

_ws_task: asyncio.Task = None
_ssh_cleanup_task: asyncio.Task = None


async def start_agent_tasks():
    """Start all agent background tasks. Called from main.py lifespan."""
    global _ws_task, _ssh_cleanup_task

    from modules.agent.ws.client import run_ws_client

    _ws_task = asyncio.create_task(run_ws_client(), name="agent_ws_client")
    _ssh_cleanup_task = asyncio.create_task(_ssh_cleanup_loop(), name="agent_ssh_cleanup")

    logger.info("Agent tasks started (ws_client, ssh_cleanup)")


async def stop_agent_tasks():
    """Cancel all agent background tasks. Called from main.py lifespan shutdown."""
    global _ws_task, _ssh_cleanup_task

    for task in (_ws_task, _ssh_cleanup_task):
        if task and not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

    _ws_task = None
    _ssh_cleanup_task = None
    logger.info("Agent tasks stopped")


async def _ssh_cleanup_loop():
    """Revoke expired SSH keys every 5 minutes."""
    from modules.agent.service.ssh import cleanup_expired_keys

    while True:
        try:
            await asyncio.sleep(300)
            await cleanup_expired_keys()
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.error(f"SSH cleanup error: {e}")
