"""
WireGuard service_ports hook.

Reports the UDP listen ports of WireGuard server instances that are currently
up (desired-state). Consumed by the firewall protected-port guard so a port
forwarding rule cannot hijack an active WireGuard listener.
"""
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select


async def run(session: AsyncSession):
    from modules.wireguard.models import WgInstance

    result = await session.execute(
        select(WgInstance).where(
            WgInstance.enabled == True,            # noqa: E712
            WgInstance.direction == "server",
            WgInstance.port.is_not(None),
        )
    )
    return [
        {"proto": "udp", "port": inst.port, "name": f"WireGuard '{inst.name}'"}
        for inst in result.scalars().all()
    ]
