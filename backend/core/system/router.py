"""
MADMIN System Router

API endpoints for system statistics.
"""
from typing import List
from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import get_session
from core.auth.dependencies import get_current_user, require_permission
from core.auth.models import User

from .service import system_service, save_stats_to_history, get_stats_history

router = APIRouter(prefix="/api/system", tags=["system"])


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

