"""
MADMIN System Router

API endpoints for system statistics.
"""
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import get_session
from core.auth.dependencies import get_current_user, require_permission
from core.auth.models import User

from .service import (
    system_service, save_stats_to_history, get_stats_history,
    get_network_traffic_history, get_system_alerts
)

router = APIRouter(prefix="/api/system", tags=["System"])


# ── Response Models ────────────────────────────────────────────────────

class CpuStats(BaseModel):
    percent: float
    count: int

class MemoryStats(BaseModel):
    percent: float
    used: int
    total: int

class DiskStats(BaseModel):
    percent: float
    used: int
    total: int

class SystemStatsResponse(BaseModel):
    available: bool
    cpu: Optional[CpuStats] = None
    memory: Optional[MemoryStats] = None
    disk: Optional[DiskStats] = None
    hostname: Optional[str] = None
    os_info: Optional[str] = None
    uptime: Optional[str] = None

class ServiceStatusItem(BaseModel):
    name: str
    status: str
    active: bool

class StatsHistoryItem(BaseModel):
    timestamp: str
    cpu: Optional[float] = None
    ram: Optional[float] = None
    disk: Optional[float] = None
    ram_used: Optional[int] = None
    ram_total: Optional[int] = None
    disk_used: Optional[int] = None
    disk_total: Optional[int] = None

class UptimeResponse(BaseModel):
    uptime: str
    since: Optional[str] = None

class NetworkTrafficInterface(BaseModel):
    interface: str
    bytes_sent: int
    bytes_recv: int
    packets_sent: int
    packets_recv: int

class AlertItem(BaseModel):
    type: str
    level: str
    message: str


@router.get("/stats")
async def get_system_stats(
    _user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session)
):
    """
    Get system statistics.
    
    Returns CPU, Memory, and Disk usage information.
    Also saves stats to history for graphs.
    """
    stats = system_service.get_stats()
    
    # Save to history if stats are available
    if stats.get("available"):
        try:
            await save_stats_to_history(
                session,
                cpu=stats["cpu"]["percent"],
                ram=stats["memory"]["percent"],
                disk=stats["disk"]["percent"],
                ram_used=stats["memory"]["used"],
                ram_total=stats["memory"]["total"],
                disk_used=stats["disk"]["used"],
                disk_total=stats["disk"]["total"]
            )
        except Exception as e:
            # Don't fail the request if history save fails
            pass
    
    return stats


@router.get("/services")
async def get_services_status(
    _user: User = Depends(get_current_user)
):
    """
    Get status of critical system services.
    
    Returns status for PostgreSQL, Nginx, MADMIN, iptables.
    """
    return system_service.get_services_status()


@router.get("/stats/history")
async def get_stats_history_endpoint(
    hours: int = Query(default=1, ge=1, le=24),
    _user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session)
) -> List[dict]:
    """
    Get historical system stats for graphs.
    
    Args:
        hours: Number of hours to look back (1-24, default 1)
    
    Returns:
        List of stats records with timestamp, cpu, ram, disk
    """
    return await get_stats_history(session, hours)


@router.get("/uptime")
async def get_uptime(
    _user: User = Depends(get_current_user)
):
    """Get system uptime formatted."""
    return system_service.get_uptime()


@router.get("/network")
async def get_network_traffic(
    _user: User = Depends(get_current_user)
):
    """Get current network traffic counters per interface."""
    return system_service.get_network_traffic()


@router.get("/network/history")
async def get_network_traffic_history_endpoint(
    hours: int = Query(default=1, ge=1, le=24),
    interface: Optional[str] = Query(default=None),
    _user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session)
) -> List[dict]:
    """
    Get historical network traffic rates per interface.
    
    Args:
        hours: Time range (1, 6, 24)
        interface: Optional, filter by interface name
    """
    return await get_network_traffic_history(session, hours, interface)


@router.get("/alerts")
async def get_alerts(
    _user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_session)
) -> List[dict]:
    """
    Get active system alerts.
    Checks CPU, RAM, and backup status.
    """
    return await get_system_alerts(session)


