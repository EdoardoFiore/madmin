"""
OpenVPN service_ports hook.

Reports the listen ports (tcp/udp per instance protocol) of OpenVPN server
instances that are currently up (desired-state). Consumed by the firewall
protected-port guard so a port forwarding rule cannot hijack an active listener.
"""
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select


async def run(session: AsyncSession):
    from modules.openvpn.models import OvpnInstance

    result = await session.execute(
        select(OvpnInstance).where(
            OvpnInstance.enabled == True,           # noqa: E712
            OvpnInstance.direction == "server",
            OvpnInstance.port.is_not(None),
        )
    )
    ports = []
    for inst in result.scalars().all():
        proto = (inst.protocol or "udp").lower()
        if proto not in ("tcp", "udp"):
            proto = "udp"
        ports.append({"proto": proto, "port": inst.port, "name": f"OpenVPN '{inst.name}'"})
    return ports
