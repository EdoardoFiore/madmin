"""
strongSwan on_startup hook.

Re-initiates IPsec tunnels that were UP before the last restart. The charon
daemon auto-starts at boot but does not necessarily initiate the tunnels, so we
reconcile from the persisted desired state (IpsecTunnel.enabled). Reuses
StrongSwanService.bring_tunnel_up so behaviour matches the /start endpoint.
Idempotent: skips tunnels already ESTABLISHED.
"""
import logging
import asyncio
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

logger = logging.getLogger("hook_on_startup")


async def run(session: AsyncSession):
    """Re-initiate all IPsec tunnels marked enabled=True."""
    from modules.strongswan.models import IpsecTunnel
    from modules.strongswan.service import strongswan_service

    result = await session.execute(
        select(IpsecTunnel).where(IpsecTunnel.enabled == True)  # noqa: E712
    )
    tunnels = result.scalars().all()

    restored = 0
    for tunnel in tunnels:
        try:
            # Idempotent: skip if already established
            status = await asyncio.to_thread(strongswan_service.get_tunnel_status, tunnel.name)
            if status and status.get("ike_state") == "ESTABLISHED":
                tunnel.status = "established"
                continue

            if await strongswan_service.bring_tunnel_up(tunnel, session):
                restored += 1
                logger.info(f"Restored IPsec tunnel {tunnel.name}")
            else:
                logger.error(f"Failed to restore IPsec tunnel {tunnel.name}")
        except Exception as e:
            logger.error(f"Error restoring IPsec tunnel {tunnel.name}: {e}", exc_info=True)

    await session.commit()
    logger.info(f"strongSwan on_startup: {restored} tunnel(s) restored ({len(tunnels)} enabled)")
