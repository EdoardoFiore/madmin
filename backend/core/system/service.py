"""
MADMIN System Service

Provides system statistics using psutil.
"""
import logging
from typing import Optional

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
    def format_bytes(bytes_value: int) -> str:
        """Format bytes to human readable string."""
        for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
            if bytes_value < 1024:
                return f"{bytes_value:.1f} {unit}"
            bytes_value /= 1024
        return f"{bytes_value:.1f} PB"


system_service = SystemService()
