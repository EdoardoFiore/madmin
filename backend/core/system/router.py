"""
MADMIN System Router

API endpoints for system statistics.
"""
from fastapi import APIRouter, Depends
from core.auth.dependencies import get_current_user, require_permission
from core.auth.models import User

from .service import system_service

router = APIRouter(prefix="/api/system", tags=["system"])


@router.get("/stats")
async def get_system_stats(
    _user: User = Depends(get_current_user)
):
    """
    Get system statistics.
    
    Returns CPU, Memory, and Disk usage information.
    No special permission required, just authentication.
    """
    return system_service.get_stats()
