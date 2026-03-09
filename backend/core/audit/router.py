"""
MADMIN Audit Log Router

API endpoints for viewing audit logs and system logs.
"""
import math
from typing import Optional
from datetime import datetime
from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from core.database import get_session
from core.auth.dependencies import require_permission
from core.auth.models import User

from .service import query_audit_logs, get_distinct_users, get_system_logs

router = APIRouter(prefix="/api/logs", tags=["logs"])


@router.get("/audit")
async def list_audit_logs(
    page: int = Query(default=1, ge=1),
    per_page: int = Query(default=50, ge=10, le=200),
    user: Optional[str] = Query(default=None, description="Filter by username"),
    method: Optional[str] = Query(default=None, description="Filter by HTTP method"),
    category: Optional[str] = Query(default="write", description="'write', 'read', or None for all"),
    search: Optional[str] = Query(default=None, description="Search in path"),
    from_date: Optional[str] = Query(default=None, description="From date (ISO format)"),
    to_date: Optional[str] = Query(default=None, description="To date (ISO format)"),
    current_user: User = Depends(require_permission("logs.view")),
    session: AsyncSession = Depends(get_session),
):
    """
    Get paginated audit logs with filters.
    
    Default: shows only 'write' operations (POST, PUT, PATCH, DELETE).
    Set category to None or empty to see all operations including reads.
    """
    # Parse dates
    parsed_from = None
    parsed_to = None
    if from_date:
        try:
            parsed_from = datetime.fromisoformat(from_date)
        except ValueError:
            pass
    if to_date:
        try:
            parsed_to = datetime.fromisoformat(to_date)
        except ValueError:
            pass
    
    # Treat empty string as None for category
    if category == "":
        category = None
    
    logs, total = await query_audit_logs(
        session,
        page=page,
        per_page=per_page,
        username=user,
        method=method,
        category=category,
        search=search,
        from_date=parsed_from,
        to_date=parsed_to,
    )
    
    return {
        "items": [
            {
                "id": str(log.id),
                "timestamp": log.timestamp.isoformat(),
                "username": log.username,
                "method": log.method,
                "path": log.path,
                "status_code": log.status_code,
                "duration_ms": log.duration_ms,
                "client_ip": log.client_ip,
                "category": log.category,
                "request_body": log.request_body,
            }
            for log in logs
        ],
        "total": total,
        "page": page,
        "pages": math.ceil(total / per_page) if total > 0 else 1,
        "per_page": per_page,
    }


@router.get("/audit/users")
async def list_audit_users(
    current_user: User = Depends(require_permission("logs.view")),
    session: AsyncSession = Depends(get_session),
):
    """Get distinct usernames from audit log for filter dropdown."""
    users = await get_distinct_users(session)
    return {"users": users}


@router.get("/system")
async def get_system_log(
    lines: int = Query(default=200, ge=10, le=1000),
    search: Optional[str] = Query(default=None, description="Filter text (grep)"),
    current_user: User = Depends(require_permission("logs.view")),
):
    """
    Get raw system logs from journalctl.
    
    Returns the raw output of journalctl -u madmin, useful for
    debugging system-level issues (restarts, errors, subprocess output).
    """
    log_lines = await get_system_logs(lines=lines, search=search)
    return {"lines": log_lines, "count": len(log_lines)}
