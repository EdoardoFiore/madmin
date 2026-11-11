"""
Resource and traffic history for the manager (stats.history).

The same data as the MADMIN dashboard graphs (system_stats_history and
network_traffic_history, one sample a minute, kept 24 hours), averaged down
to at most MAX_POINTS points so that 24 hours fit in a small frame. Read only:
nothing on the instance changes and nothing is audited.

Result (columns rather than rows, to keep the frame small):

    {"hours": 6,
     "system": {"t": [iso...], "cpu": [...], "ram": [...], "disk": [...],
                "ram_total": bytes, "disk_total": bytes},
     "network": {"eth0": {"t": [iso...], "rx": [bytes/s...], "tx": [...]}, ...}}
"""
import math
from typing import List

from pydantic import Field

from . import protocol
from .commands import CommandArgs, CommandContext, command

MAX_POINTS = 240


class StatsHistoryArgs(CommandArgs):
    hours: int = Field(default=1, ge=1, le=24)


def _chunks(rows: List[dict]) -> List[List[dict]]:
    """Consecutive groups, so that len(result) <= MAX_POINTS."""
    step = max(1, math.ceil(len(rows) / MAX_POINTS))
    return [rows[i:i + step] for i in range(0, len(rows), step)]


def _avg(group: List[dict], key: str, digits: int = 1) -> float:
    return round(sum(float(r.get(key) or 0) for r in group) / len(group), digits)


def _system(rows: List[dict]) -> dict:
    out = {"t": [], "cpu": [], "ram": [], "disk": [],
           "ram_total": rows[-1].get("ram_total", 0) if rows else 0,
           "disk_total": rows[-1].get("disk_total", 0) if rows else 0}
    for group in _chunks(rows):
        out["t"].append(group[-1]["timestamp"])
        out["cpu"].append(_avg(group, "cpu"))
        out["ram"].append(_avg(group, "ram"))
        out["disk"].append(_avg(group, "disk"))
    return out


def _network(rows: List[dict]) -> dict:
    by_iface: dict = {}
    for r in rows:
        by_iface.setdefault(r["interface"], []).append(r)
    out = {}
    for iface, iface_rows in sorted(by_iface.items()):
        series = {"t": [], "rx": [], "tx": []}
        for group in _chunks(iface_rows):
            series["t"].append(group[-1]["timestamp"])
            series["rx"].append(_avg(group, "rx_rate", 0))
            series["tx"].append(_avg(group, "tx_rate", 0))
        out[iface] = series
    return out


@command(protocol.CMD_STATS_HISTORY, StatsHistoryArgs, timeout=30, audit=False)
async def _stats_history(args: StatsHistoryArgs, ctx: CommandContext) -> dict:
    from core.database import async_session_maker
    from core.system.service import get_network_traffic_history, get_stats_history

    async with async_session_maker() as session:
        system = await get_stats_history(session, args.hours)
        network = await get_network_traffic_history(session, args.hours)
    return {"hours": args.hours, "system": _system(system), "network": _network(network)}
