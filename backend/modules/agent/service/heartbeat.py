"""
Collect telemetry batch from core SystemStatsHistory for hub heartbeat.
Also collects services_status, modules_status, os_info from live sources.
"""
import logging
import platform
from datetime import datetime, timedelta
from typing import List, Optional

from config import MADMIN_VERSION

logger = logging.getLogger(__name__)

# Cache public IP for 10 minutes to avoid hitting external services every heartbeat
_public_ip_cache: Optional[str] = None
_public_ip_cached_at: Optional[datetime] = None
_PUBLIC_IP_TTL = timedelta(minutes=10)


def _get_public_ip_cached() -> Optional[str]:
    global _public_ip_cache, _public_ip_cached_at
    now = datetime.utcnow()
    if _public_ip_cache and _public_ip_cached_at and (now - _public_ip_cached_at) < _PUBLIC_IP_TTL:
        return _public_ip_cache
    try:
        from core.network.utils import get_public_ip
        ip = get_public_ip()
        if ip:
            _public_ip_cache = ip
            _public_ip_cached_at = now
        return ip
    except Exception:
        return _public_ip_cache  # return stale on failure


async def _get_iface_bps_map(session, timestamps: list) -> dict:
    """
    Returns {datetime -> {iface -> {in_bps, out_bps}}} for each timestamp.
    Computes BPS from consecutive NetworkTrafficHistory rows per interface.
    """
    if not timestamps:
        return {}
    from collections import defaultdict
    from datetime import timedelta
    from sqlalchemy import select
    from core.settings.models import NetworkTrafficHistory

    min_ts = min(timestamps)
    max_ts = max(timestamps)
    try:
        res = await session.execute(
            select(NetworkTrafficHistory)
            .where(
                NetworkTrafficHistory.timestamp >= min_ts - timedelta(seconds=70),
                NetworkTrafficHistory.timestamp <= max_ts + timedelta(seconds=10),
            )
            .order_by(NetworkTrafficHistory.interface, NetworkTrafficHistory.timestamp)
        )
        rows = res.scalars().all()
    except Exception:
        return {}

    by_iface: dict = defaultdict(list)
    for r in rows:
        by_iface[r.interface].append(r)

    ts_set = set(timestamps)
    result: dict = {ts: {} for ts in ts_set}

    for iface, iface_rows in by_iface.items():
        for i in range(1, len(iface_rows)):
            prev = iface_rows[i - 1]
            curr = iface_rows[i]
            dt = (curr.timestamp - prev.timestamp).total_seconds()
            if dt <= 0:
                continue
            in_bps = max(0, int((curr.bytes_recv - prev.bytes_recv) / dt))
            out_bps = max(0, int((curr.bytes_sent - prev.bytes_sent) / dt))
            closest = min(ts_set, key=lambda t: abs((t - curr.timestamp).total_seconds()))
            if abs((closest - curr.timestamp).total_seconds()) < 70:
                result[closest][iface] = {"in_bps": in_bps, "out_bps": out_bps}

    return result


def _get_uptime_seconds() -> int:
    try:
        import time
        import psutil
        return int(time.time() - psutil.boot_time())
    except Exception:
        return 0


async def collect_telemetry_batch() -> dict:
    """
    Query SystemStatsHistory rows since last_telemetry_ts cursor stored in HubConfig.
    Returns payload for telemetry_batch WS frame.
    On first call (no cursor), sends the last row only to avoid flooding.
    """
    from core.database import async_session_maker
    from core.settings.models import SystemStatsHistory
    from modules.agent.models import HubConfig
    from sqlalchemy import select

    snapshots: List[dict] = []
    last_ts: Optional[datetime] = None

    async with async_session_maker() as session:
        result = await session.execute(select(HubConfig).where(HubConfig.id == 1))
        config = result.scalar_one_or_none()
        cursor = config.last_telemetry_ts if config else None

        if cursor is None:
            # First batch: send only the latest row to avoid flooding
            stmt = (
                select(SystemStatsHistory)
                .order_by(SystemStatsHistory.timestamp.desc())
                .limit(1)
            )
        else:
            stmt = (
                select(SystemStatsHistory)
                .where(SystemStatsHistory.timestamp > cursor)
                .order_by(SystemStatsHistory.timestamp.asc())
                .limit(500)
            )

        rows_result = await session.execute(stmt)
        rows = rows_result.scalars().all()

        iface_bps_map = await _get_iface_bps_map(session, [r.timestamp for r in rows])
        uptime_seconds = _get_uptime_seconds()
        for r in rows:
            snapshots.append({
                "ts": r.timestamp.isoformat(),
                "cpu_percent": r.cpu_percent,
                "ram_percent": r.ram_percent,
                "ram_used": r.ram_used,
                "ram_total": r.ram_total,
                "disk_percent": r.disk_percent,
                "disk_used": r.disk_used,
                "disk_total": r.disk_total,
                "net_in_bps": r.net_in_bps,
                "net_out_bps": r.net_out_bps,
                "net_interfaces": iface_bps_map.get(r.timestamp, {}),
                "uptime_seconds": uptime_seconds,
            })
            last_ts = r.timestamp

    return {
        "snapshots": snapshots,
        "services_status": _get_services_status(),
        "modules_status": _get_modules_status(),
        "version": MADMIN_VERSION,
        "os_info": _get_os_info(),
        "public_ip": _get_public_ip_cached(),
        "last_ts": last_ts.isoformat() if last_ts else None,
    }


async def advance_telemetry_cursor(last_ts_iso: Optional[str]) -> None:
    """Called after hub acks the batch — advances cursor so rows aren't re-sent."""
    if not last_ts_iso:
        return
    try:
        ts = datetime.fromisoformat(last_ts_iso)
        from core.database import async_session_maker
        from modules.agent.models import HubConfig
        from sqlalchemy import update

        async with async_session_maker() as session:
            await session.execute(
                update(HubConfig).where(HubConfig.id == 1).values(
                    last_telemetry_ts=ts,
                    updated_at=datetime.utcnow(),
                )
            )
            await session.commit()
    except Exception as e:
        logger.warning(f"advance_telemetry_cursor failed: {e}")


def _get_os_info() -> dict:
    info = {}
    try:
        with open("/etc/os-release") as f:
            for line in f:
                if line.startswith("PRETTY_NAME="):
                    info["os"] = line.split("=", 1)[1].strip().strip('"')
                    break
    except Exception:
        pass
    try:
        info["hostname"] = platform.node()
        info["kernel"] = platform.release()
    except Exception:
        pass
    return info


def _get_services_status() -> dict:
    from core.system.service import SystemService
    try:
        services = SystemService.get_services_status()
        return {svc: info.get("status", "unknown") for svc, info in services.items()}
    except Exception:
        return {}


def _get_modules_status() -> dict:
    try:
        from core.modules.loader import module_loader
        return {mid: "enabled" for mid in module_loader.loaded_modules.keys()}
    except Exception:
        return {}
