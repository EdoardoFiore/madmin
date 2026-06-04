"""
OpenVPN on_startup hook.

Restores instances that were UP before the last restart (desired-state
reconciliation). Reuses OpenVPNService.bring_instance_up so the firewall state
matches the /start endpoint exactly. Idempotent: skips instances already active.
"""
import logging
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

logger = logging.getLogger("hook_on_startup")


async def run(session: AsyncSession):
    """Bring up all OpenVPN instances marked enabled=True."""
    from modules.openvpn.models import OvpnInstance
    from modules.openvpn.service import OpenVPNService

    result = await session.execute(
        select(OvpnInstance).where(OvpnInstance.enabled == True)  # noqa: E712
    )
    instances = result.scalars().all()

    restored = 0
    for instance in instances:
        try:
            # Idempotent: skip if already active
            if instance.direction == "client":
                already_up = OpenVPNService.get_client_instance_status(instance.id)
            else:
                already_up = OpenVPNService.get_instance_status(instance.id)
            if already_up:
                instance.status = "running"
                continue

            if await OpenVPNService.bring_instance_up(instance, session):
                instance.status = "running"
                restored += 1
                logger.info(f"Restored OpenVPN instance {instance.name} ({instance.id})")
            else:
                logger.error(f"Failed to restore OpenVPN instance {instance.name} ({instance.id})")
        except Exception as e:
            logger.error(f"Error restoring OpenVPN instance {instance.name}: {e}", exc_info=True)

    await session.commit()
    logger.info(f"OpenVPN on_startup: {restored} instance(s) restored ({len(instances)} enabled)")
