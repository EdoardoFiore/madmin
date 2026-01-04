"""
MADMIN System Service

Provides system statistics using psutil.
"""
import logging
import subprocess
import shutil
from typing import Optional, List
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

# Try to import psutil, provide fallback if not installed
try:
    import psutil
    PSUTIL_AVAILABLE = True
except ImportError:
    PSUTIL_AVAILABLE = False
    logger.warning("psutil not installed. System stats will be unavailable.")


class SystemService:
    """Service class for system statistics."""
    
    @staticmethod
    def get_stats() -> dict:
        """
        Get system statistics: CPU, Memory, Disk usage.
        
        Returns:
            dict with cpu, memory, and disk stats
        """
        if not PSUTIL_AVAILABLE:
            return {
                "available": False,
                "error": "psutil not installed"
            }
        
        try:
            # CPU usage (non-blocking, 0 interval returns cached value)
            cpu_percent = psutil.cpu_percent(interval=0.1)
            cpu_count = psutil.cpu_count()
            
            # Memory usage
            mem = psutil.virtual_memory()
            
            # Disk usage (root partition)
            disk = psutil.disk_usage('/')
            
            # System uptime
            boot_time = psutil.boot_time()
            
            return {
                "available": True,
                "cpu": {
                    "percent": cpu_percent,
                    "count": cpu_count
                },
                "memory": {
                    "total": mem.total,
                    "used": mem.used,
                    "available": mem.available,
                    "percent": mem.percent
                },
                "disk": {
                    "total": disk.total,
                    "used": disk.used,
                    "free": disk.free,
                    "percent": disk.percent
                },
                "boot_time": boot_time
            }
        except Exception as e:
            logger.error(f"Error getting system stats: {e}")
            return {
                "available": False,
                "error": str(e)
            }
    
    @staticmethod
    def get_services_status() -> dict:
        """
        Check status of critical system services.
        
        Returns:
            dict with service names and their status (active/inactive)
        """
        services = {}
        
        # Check systemd services
        service_names = ['postgresql', 'nginx', 'madmin']
        for svc in service_names:
            try:
                result = subprocess.run(
                    ['systemctl', 'is-active', svc],
                    capture_output=True,
                    timeout=5
                )
                status = result.stdout.decode().strip()
                services[svc] = {
                    "active": status == 'active',
                    "status": status
                }
            except Exception as e:
                services[svc] = {
                    "active": False,
                    "status": "unknown",
                    "error": str(e)
                }
        
        # Check iptables availability
        services['iptables'] = {
            "active": shutil.which('iptables') is not None,
            "status": "available" if shutil.which('iptables') else "not found"
        }
        
        return services
    
    @staticmethod
    def format_bytes(bytes_value: int) -> str:
        """Format bytes to human readable string."""
        for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
            if bytes_value < 1024:
                return f"{bytes_value:.1f} {unit}"
            bytes_value /= 1024
        return f"{bytes_value:.1f} PB"


# Async functions for database operations (called from router)
async def save_stats_to_history(
    session, 
    cpu: float, 
    ram: float, 
    disk: float,
    ram_used: int = 0,
    ram_total: int = 0,
    disk_used: int = 0,
    disk_total: int = 0
):
    """Save current stats to history table."""
    from core.settings.models import SystemStatsHistory
    
    try:
        record = SystemStatsHistory(
            cpu_percent=cpu,
            ram_percent=ram,
            ram_used=ram_used,
            ram_total=ram_total,
            disk_percent=disk,
            disk_used=disk_used,
            disk_total=disk_total
        )
        session.add(record)
        await session.commit()
        
        # Cleanup old records (keep only last 24h)
        await cleanup_old_stats(session)
    except Exception as e:
        await session.rollback()
        logger.error(f"Error saving stats to history: {e}")


async def cleanup_old_stats(session):
    """Remove stats older than 24 hours."""
    from sqlalchemy import delete
    from core.settings.models import SystemStatsHistory
    
    cutoff = datetime.utcnow() - timedelta(hours=24)
    await session.execute(
        delete(SystemStatsHistory).where(SystemStatsHistory.timestamp < cutoff)
    )
    await session.commit()


async def get_stats_history(session, hours: int = 1) -> List[dict]:
    """
    Get historical stats for the specified time range.
    
    Args:
        session: Database session
        hours: Number of hours to look back (1 or 24)
    
    Returns:
        List of stats records ordered by timestamp
    """
    from sqlalchemy import select
    from core.settings.models import SystemStatsHistory
    
    cutoff = datetime.utcnow() - timedelta(hours=hours)
    
    result = await session.execute(
        select(SystemStatsHistory)
        .where(SystemStatsHistory.timestamp >= cutoff)
        .order_by(SystemStatsHistory.timestamp.asc())
    )
    records = result.scalars().all()
    
    return [
        {
            "timestamp": r.timestamp.isoformat(),
            "cpu": r.cpu_percent,
            "ram": r.ram_percent,
            "ram_used": r.ram_used,
            "ram_total": r.ram_total,
            "disk": r.disk_percent,
            "disk_used": r.disk_used,
            "disk_total": r.disk_total
        }
        for r in records
    ]


system_service = SystemService()

