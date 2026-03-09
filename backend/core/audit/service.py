"""
MADMIN Audit Service

Business logic for audit log operations:
- Exclusion path management
- Log querying with filters
- Cleanup of old records
- System log (journalctl) reading
"""
import re
import logging
import asyncio
from datetime import datetime, timedelta
from typing import Optional, List, Tuple
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, delete, and_, or_

from .models import AuditLog

logger = logging.getLogger(__name__)

# --- Exclusion Configuration ---

# Exact paths to exclude from DB persistence (polling/navigation endpoints)
EXCLUDED_PATHS: set = {
    "/api/system/stats",
    "/api/system/network",
    "/api/system/uptime",
    "/api/system/alerts",
    "/api/system/services",
    "/api/system/stats/history",
    "/api/system/network/history",
    "/api/health",
    "/api/ui/menu",
    "/api/auth/me",
    "/api/auth/me/2fa/status",
    "/api/settings/system",
    "/api/settings/backup",
    "/api/logs/audit",
    "/api/logs/system",
}

# Regex patterns for dynamic path exclusion
EXCLUDED_PATTERNS: list = [
    re.compile(r".*/status$"),      # Any /status polling endpoint
    re.compile(r".*/traffic$"),     # Traffic polling
    re.compile(r".*/widgets$"),     # Module widgets
]

# Default retention period in days
DEFAULT_RETENTION_DAYS = 90


def is_excluded(path: str, method: str = "GET") -> bool:
    """
    Check if a request should be excluded from DB persistence.
    
    Write operations (POST, PUT, PATCH, DELETE) are NEVER excluded —
    only GET requests to polling/navigation paths are skipped.
    
    Excluded requests are still logged to journalctl but not saved to the database.
    """
    # Never exclude write operations
    if method != "GET":
        return False
    
    # Strip query parameters for matching
    clean_path = path.split("?")[0]
    
    # Exact match
    if clean_path in EXCLUDED_PATHS:
        return True
    
    # Pattern match
    for pattern in EXCLUDED_PATTERNS:
        if pattern.match(clean_path):
            return True
    
    return False


# --- Query Functions ---

async def query_audit_logs(
    session: AsyncSession,
    page: int = 1,
    per_page: int = 50,
    username: Optional[str] = None,
    method: Optional[str] = None,
    category: Optional[str] = "write",
    search: Optional[str] = None,
    from_date: Optional[datetime] = None,
    to_date: Optional[datetime] = None,
) -> Tuple[List[AuditLog], int]:
    """
    Query audit logs with filters and pagination.
    
    Returns:
        Tuple of (logs list, total count)
    """
    # Build filter conditions
    conditions = []
    
    if username:
        conditions.append(AuditLog.username == username)
    if method:
        conditions.append(AuditLog.method == method)
    if category:
        conditions.append(AuditLog.category == category)
    if search:
        conditions.append(or_(
            AuditLog.path.ilike(f"%{search}%"),
            AuditLog.request_body.ilike(f"%{search}%")
        ))
    if from_date:
        conditions.append(AuditLog.timestamp >= from_date)
    if to_date:
        conditions.append(AuditLog.timestamp <= to_date)
    
    where_clause = and_(*conditions) if conditions else True
    
    # Get total count
    count_query = select(func.count(AuditLog.id)).where(where_clause)
    total = (await session.execute(count_query)).scalar()
    
    # Get paginated results
    offset = (page - 1) * per_page
    query = (
        select(AuditLog)
        .where(where_clause)
        .order_by(AuditLog.timestamp.desc())
        .offset(offset)
        .limit(per_page)
    )
    result = await session.execute(query)
    logs = result.scalars().all()
    
    return logs, total


async def get_distinct_users(session: AsyncSession) -> List[str]:
    """Get all distinct usernames from audit log for filter dropdown."""
    result = await session.execute(
        select(AuditLog.username)
        .distinct()
        .where(AuditLog.username != "anonymous")
        .order_by(AuditLog.username)
    )
    return [row[0] for row in result.all()]


# --- Cleanup ---

async def cleanup_old_logs(session: AsyncSession, retention_days: int = DEFAULT_RETENTION_DAYS) -> int:
    """
    Delete audit log entries older than retention_days.
    
    Returns:
        Number of deleted records
    """
    cutoff = datetime.utcnow() - timedelta(days=retention_days)
    
    result = await session.execute(
        delete(AuditLog).where(AuditLog.timestamp < cutoff)
    )
    await session.commit()
    
    deleted = result.rowcount
    if deleted > 0:
        logger.info(f"Audit log cleanup: deleted {deleted} records older than {retention_days} days")
    
    return deleted


# --- System Log (journalctl) ---

async def get_system_logs(lines: int = 200, search: Optional[str] = None) -> List[str]:
    """
    Read raw system logs from journalctl.
    
    Args:
        lines: Number of lines to retrieve (max 1000)
        search: Optional text filter (grep)
    
    Returns:
        List of raw log lines
    """
    lines = min(lines, 1000)
    
    cmd = ["journalctl", "-u", "madmin", "--no-pager", "-n", str(lines), "--output=cat"]
    
    if search:
        # Use grep to filter
        cmd_str = f"journalctl -u madmin --no-pager -n {lines} --output=cat | grep -i '{search}'"
        proc = await asyncio.create_subprocess_shell(
            cmd_str,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
    else:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
    
    stdout, stderr = await proc.communicate()
    
    if stdout:
        return stdout.decode("utf-8", errors="replace").strip().split("\n")
    
    return []
