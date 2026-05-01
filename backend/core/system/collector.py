"""
Periodic system stats collector.
Writes one SystemStatsHistory row every INTERVAL_SECONDS (default 60).
Computes network rates from cumulative counter deltas.
Also writes to NetworkTrafficHistory for dashboard history graphs.
Replaces the inline collect_stats_periodically task in main.py.
"""
import asyncio
import logging
from datetime import datetime, timedelta
from typing import Dict

logger = logging.getLogger(__name__)

INTERVAL_SECONDS = 60

_prev_net: Dict[str, dict] = {}


async def run_collector() -> None:
    """Infinite loop. First iteration primes _prev_net without writing a row."""
    from core.system.service import SystemService
    logger.info(f"System stats collector started (interval={INTERVAL_SECONDS}s)")

    # Prime net counters so first real collection has a delta to compute
    net = SystemService.get_network_traffic()
    now = datetime.utcnow()
    if net.get("available") and "interfaces" in net:
        global _prev_net
        _prev_net = {
            iface: {"bytes_recv": c["bytes_recv"], "bytes_sent": c["bytes_sent"], "ts": now}
            for iface, c in net["interfaces"].items()
        }

    while True:
        await asyncio.sleep(INTERVAL_SECONDS)
        try:
            await _collect_once()
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.warning(f"Collector iteration failed: {e}")


async def _collect_once() -> None:
    from core.database import async_session_maker
    from core.settings.models import NetworkTrafficHistory, SystemStatsHistory
    from core.system.service import SystemService

    stats = SystemService.get_stats()
    net = SystemService.get_network_traffic()
    now = datetime.utcnow()

    in_bps, out_bps = 0, 0
    net_rows = []
    if net.get("available") and "interfaces" in net:
        global _prev_net
        new_prev: Dict[str, dict] = {}
        for iface, c in net["interfaces"].items():
            prev = _prev_net.get(iface)
            if prev:
                dt = (now - prev["ts"]).total_seconds()
                if dt > 0:
                    in_bps += max(0, int((c["bytes_recv"] - prev["bytes_recv"]) / dt))
                    out_bps += max(0, int((c["bytes_sent"] - prev["bytes_sent"]) / dt))
            new_prev[iface] = {"bytes_recv": c["bytes_recv"], "bytes_sent": c["bytes_sent"], "ts": now}
            net_rows.append(NetworkTrafficHistory(
                timestamp=now, interface=iface,
                bytes_sent=c["bytes_sent"], bytes_recv=c["bytes_recv"],
            ))
        _prev_net = new_prev

    if not stats.get("available"):
        return

    mem = stats["memory"]
    disk = stats["disk"]
    cutoff = now - timedelta(hours=24)

    async with async_session_maker() as session:
        session.add(SystemStatsHistory(
            timestamp=now,
            cpu_percent=stats["cpu"]["percent"],
            ram_percent=mem["percent"],
            ram_used=mem["used"],
            ram_total=mem["total"],
            disk_percent=disk["percent"],
            disk_used=disk["used"],
            disk_total=disk["total"],
            net_in_bps=in_bps,
            net_out_bps=out_bps,
        ))
        for row in net_rows:
            session.add(row)
        await session.commit()

        # Prune old rows
        from sqlalchemy import delete
        await session.execute(
            delete(SystemStatsHistory).where(SystemStatsHistory.timestamp < cutoff)
        )
        await session.execute(
            delete(NetworkTrafficHistory).where(NetworkTrafficHistory.timestamp < cutoff)
        )
        await session.commit()
