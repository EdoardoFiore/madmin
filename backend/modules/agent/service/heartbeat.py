"""
Collect telemetry batch from core SystemStatsHistory for hub heartbeat.
Also collects services_status, modules_status, os_info from live sources.
"""
import logging
import platform
from datetime import datetime
from typing import List, Optional

from config import MADMIN_VERSION

logger = logging.getLogger(__name__)


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
            })
            last_ts = r.timestamp

    return {
        "snapshots": snapshots,
        "services_status": _get_services_status(),
        "modules_status": _get_modules_status(),
        "version": MADMIN_VERSION,
        "os_info": _get_os_info(),
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
