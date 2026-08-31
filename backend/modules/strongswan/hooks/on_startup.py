"""
strongSwan on_startup hook.

Re-initiates IPsec tunnels that were UP before the last restart. The charon
daemon auto-starts at boot but does not necessarily initiate the tunnels, so we
reconcile from the persisted desired state (IpsecTunnel.enabled). Reuses
StrongSwanService.bring_tunnel_up so behaviour matches the /start endpoint.
Idempotent: skips tunnels already ESTABLISHED.

Runs a reconciliation pass first, so the runtime state charon and iptables were
left in always matches the database — including anything an older build left
behind, whose names were derived from the (mutable) tunnel name.
"""
import logging
import asyncio
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

logger = logging.getLogger("hook_on_startup")


async def _clean_stale_state(session: AsyncSession) -> None:
    """Drop every config file, chain and SA the database no longer accounts for.

    Everything MADMIN writes is named after a primary key, so whatever does not
    map back to a live row is by definition a leftover: a tunnel deleted while
    the service was down, a restored archive that replaced the whole set, or the
    madmin_<name>.conf fragments and IPSEC_<name>_<idx>_* chains of a build that
    still keyed on the tunnel name.

    Reloading afterwards makes charon forget the connections whose files are
    gone. The SAs they leave behind are terminated explicitly: an orphan SA keeps
    its kernel policies installed, and the connection that should own those
    traffic selectors then cannot install its own.
    """
    from modules.strongswan.models import IpsecTunnel
    from modules.strongswan.service import CONN_PREFIX, conn_name, strongswan_service

    await strongswan_service.prune_orphan_firewall_objects(session)
    await asyncio.to_thread(strongswan_service.load_all_connections)

    result = await session.execute(select(IpsecTunnel))
    expected = {conn_name(t.id) for t in result.scalars().all()}

    active = await asyncio.to_thread(strongswan_service.list_active_conn_names)
    for conn in active:
        if conn.startswith(CONN_PREFIX) and conn not in expected:
            logger.info(f"Terminating stale IPsec connection {conn}")
            await asyncio.to_thread(strongswan_service.terminate_connection_by_name, conn)


async def run(session: AsyncSession):
    """Re-initiate all IPsec tunnels marked enabled=True."""
    from modules.strongswan.models import IpsecTunnel
    from modules.strongswan.service import strongswan_service

    try:
        await _clean_stale_state(session)
    except Exception as e:
        logger.error(f"IPsec stale-state cleanup failed: {e}", exc_info=True)

    result = await session.execute(
        select(IpsecTunnel).where(IpsecTunnel.enabled == True)  # noqa: E712
    )
    tunnels = result.scalars().all()

    restored = 0
    for tunnel in tunnels:
        try:
            # Idempotent: skip re-initiation if already established (charon
            # auto-started the SA at boot). But its firewall chains / NAT
            # exemptions are NOT persisted, so rebuild them from code here —
            # otherwise an already-UP tunnel keeps stale/missing rules after boot.
            status = await asyncio.to_thread(strongswan_service.get_tunnel_status, tunnel.id)
            if status and status.get("ike_state") == "ESTABLISHED":
                tunnel.status = "established"
                try:
                    await strongswan_service.apply_tunnel_firewall(tunnel, session)
                except Exception as e:
                    logger.error(f"Firewall setup for established tunnel {tunnel.name} failed: {e}")
                continue

            if await strongswan_service.bring_tunnel_up(tunnel, session):
                restored += 1
                logger.info(f"Restored IPsec tunnel {tunnel.name}")
            else:
                logger.error(
                    f"Failed to restore IPsec tunnel {tunnel.name}: "
                    f"{strongswan_service.last_initiate_error or 'unknown error'}"
                )
        except Exception as e:
            logger.error(f"Error restoring IPsec tunnel {tunnel.name}: {e}", exc_info=True)

    await session.commit()
    logger.info(f"strongSwan on_startup: {restored} tunnel(s) restored ({len(tunnels)} enabled)")
