"""
WireGuard on_startup hook.

Restores instances that were UP before the last restart (desired-state
reconciliation). Reuses WireGuardService.bring_instance_up so the firewall
state matches the /start endpoint exactly. Idempotent: skips instances whose
interface is already running.
"""
import logging
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

logger = logging.getLogger("hook_on_startup")


async def run(session: AsyncSession):
    """Bring up all WireGuard instances marked enabled=True."""
    from modules.wireguard.models import WgInstance
    from modules.wireguard.service import WireGuardService

    result = await session.execute(
        select(WgInstance).where(WgInstance.enabled == True)  # noqa: E712
    )
    instances = result.scalars().all()

    restored = 0
    for instance in instances:
        try:
            # Idempotent: skip if interface already up
            if WireGuardService.get_interface_status(instance.interface):
                instance.status = "running"
                continue
            if await WireGuardService.bring_instance_up(instance, session):
                instance.status = "running"
                restored += 1
                logger.info(f"Restored WireGuard instance {instance.name} ({instance.interface})")
            else:
                logger.error(f"Failed to restore WireGuard instance {instance.name} ({instance.interface})")
        except Exception as e:
            logger.error(f"Error restoring WireGuard instance {instance.name}: {e}", exc_info=True)

    await session.commit()
    logger.info(f"WireGuard on_startup: {restored} instance(s) restored ({len(instances)} enabled)")
