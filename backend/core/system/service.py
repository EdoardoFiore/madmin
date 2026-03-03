"""
MADMIN System Service

Provides system statistics using psutil.
"""
import logging
import subprocess
import shutil
import os
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
    def restart_madmin(delay_seconds: int = 1) -> None:
        """
        Restart the MADMIN backend safely.
        
        Uses a detached background shell command to avoid the restart command
        being killed (SIGTERM) when the MADMIN service itself stops.
        
        Args:
            delay_seconds: Seconds to wait before restarting, to allow API responses
        """
        logger.info(f"Scheduling MADMIN restart in {delay_seconds}s...")
        # Note: os.system("... &") forks a shell in the background detached from the API
        os.system(f"sleep {delay_seconds} && systemctl restart madmin &")
    
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

    @staticmethod
    def get_network_traffic() -> dict:
        """
        Get current network traffic counters per interface.
        Excludes loopback (lo).
        """
        if not PSUTIL_AVAILABLE:
            return {"available": False, "error": "psutil not installed"}
        
        try:
            counters = psutil.net_io_counters(pernic=True)
            result = {}
            for iface, stats in counters.items():
                if iface == 'lo':
                    continue
                result[iface] = {
                    "bytes_sent": stats.bytes_sent,
                    "bytes_recv": stats.bytes_recv,
                    "packets_sent": stats.packets_sent,
                    "packets_recv": stats.packets_recv,
                }
            return {"available": True, "interfaces": result}
        except Exception as e:
            logger.error(f"Error getting network traffic: {e}")
            return {"available": False, "error": str(e)}

    @staticmethod
    def get_uptime() -> dict:
        """Get system uptime formatted."""
        if not PSUTIL_AVAILABLE:
            return {"available": False, "error": "psutil not installed"}
        
        try:
            boot = datetime.fromtimestamp(psutil.boot_time())
            delta = datetime.now() - boot
            total_seconds = int(delta.total_seconds())
            
            days = total_seconds // 86400
            hours = (total_seconds % 86400) // 3600
            minutes = (total_seconds % 3600) // 60
            
            parts = []
            if days > 0:
                parts.append(f"{days}g")
            if hours > 0:
                parts.append(f"{hours}h")
            parts.append(f"{minutes}m")
            
            return {
                "available": True,
                "boot_time": boot.isoformat(),
                "uptime_seconds": total_seconds,
                "uptime_formatted": " ".join(parts)
            }
        except Exception as e:
            logger.error(f"Error getting uptime: {e}")
            return {"available": False, "error": str(e)}


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
        hours: Number of hours to look back (1, 6, or 24)
    
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


async def save_network_traffic(session):
    """Save current network traffic counters to history."""
    from core.settings.models import NetworkTrafficHistory
    
    if not PSUTIL_AVAILABLE:
        return
    
    try:
        counters = psutil.net_io_counters(pernic=True)
        now = datetime.utcnow()
        
        for iface, stats in counters.items():
            if iface == 'lo':
                continue
            record = NetworkTrafficHistory(
                timestamp=now,
                interface=iface,
                bytes_sent=stats.bytes_sent,
                bytes_recv=stats.bytes_recv,
            )
            session.add(record)
        
        await session.commit()
        
        # Cleanup old records (keep only last 24h)
        await cleanup_old_network_traffic(session)
    except Exception as e:
        await session.rollback()
        logger.error(f"Error saving network traffic: {e}")


async def cleanup_old_network_traffic(session):
    """Remove network traffic records older than 24 hours."""
    from sqlalchemy import delete
    from core.settings.models import NetworkTrafficHistory
    
    cutoff = datetime.utcnow() - timedelta(hours=24)
    await session.execute(
        delete(NetworkTrafficHistory).where(NetworkTrafficHistory.timestamp < cutoff)
    )
    await session.commit()


async def get_network_traffic_history(session, hours: int = 1, interface: str = None) -> List[dict]:
    """
    Get historical network traffic data.
    Returns rate (bytes/sec) calculated from cumulative counters.
    
    Args:
        session: Database session
        hours: Time range (1, 6, 24)
        interface: Optional, filter by interface name
    """
    from sqlalchemy import select
    from core.settings.models import NetworkTrafficHistory
    
    cutoff = datetime.utcnow() - timedelta(hours=hours)
    
    query = (
        select(NetworkTrafficHistory)
        .where(NetworkTrafficHistory.timestamp >= cutoff)
    )
    if interface:
        query = query.where(NetworkTrafficHistory.interface == interface)
    query = query.order_by(NetworkTrafficHistory.timestamp.asc())
    
    result = await session.execute(query)
    records = result.scalars().all()
    
    # Convert cumulative counters to rates (bytes/sec)
    rates = []
    prev = {}
    for r in records:
        key = r.interface
        if key in prev:
            dt = (r.timestamp - prev[key]["ts"]).total_seconds()
            if dt > 0:
                rates.append({
                    "timestamp": r.timestamp.isoformat(),
                    "interface": r.interface,
                    "tx_rate": max(0, (r.bytes_sent - prev[key]["sent"]) / dt),
                    "rx_rate": max(0, (r.bytes_recv - prev[key]["recv"]) / dt),
                })
        prev[key] = {"ts": r.timestamp, "sent": r.bytes_sent, "recv": r.bytes_recv}
    
    return rates


async def get_system_alerts(session) -> List[dict]:
    """
    Get active system alerts.
    Checks CPU (5-min avg > 90%), RAM (> 80%), backup status.
    """
    from sqlalchemy import select
    from core.settings.models import SystemStatsHistory, BackupSettings
    
    alerts = []
    
    # --- CPU check: average of last 5 minutes ---
    try:
        cutoff_5m = datetime.utcnow() - timedelta(minutes=5)
        result = await session.execute(
            select(SystemStatsHistory)
            .where(SystemStatsHistory.timestamp >= cutoff_5m)
        )
        recent_stats = result.scalars().all()
        
        if recent_stats:
            avg_cpu = sum(r.cpu_percent for r in recent_stats) / len(recent_stats)
            if avg_cpu > 90:
                alerts.append({
                    "type": "cpu_high",
                    "severity": "danger",
                    "icon": "ti-cpu",
                    "message": f"CPU elevata: {avg_cpu:.0f}% (media 5min)"
                })
    except Exception:
        pass
    
    # --- RAM check: current usage ---
    try:
        if PSUTIL_AVAILABLE:
            mem = psutil.virtual_memory()
            if mem.percent > 80:
                severity = "danger" if mem.percent > 90 else "warning"
                alerts.append({
                    "type": "ram_high",
                    "severity": severity,
                    "icon": "ti-device-desktop",
                    "message": f"RAM elevata: {mem.percent:.0f}%"
                })
    except Exception:
        pass
    
    # --- Backup checks ---
    try:
        result = await session.execute(
            select(BackupSettings).where(BackupSettings.id == 1)
        )
        bk = result.scalar_one_or_none()
        
        if bk:
            if not bk.enabled:
                alerts.append({
                    "type": "backup_not_configured",
                    "severity": "warning",
                    "icon": "ti-settings",
                    "message": "Backup periodico non abilitato"
                })
            
            if bk.last_run_time:
                days_ago = (datetime.utcnow() - bk.last_run_time).days
                if days_ago > 7:
                    alerts.append({
                        "type": "backup_stale",
                        "severity": "warning",
                        "icon": "ti-clock",
                        "message": f"Ultimo backup: {days_ago} giorni fa"
                    })
                if bk.last_run_status == "failed":
                    alerts.append({
                        "type": "backup_failed",
                        "severity": "danger",
                        "icon": "ti-alert-triangle",
                        "message": "Ultimo backup fallito"
                    })
                elif bk.last_run_status == "upload_failed":
                    alerts.append({
                        "type": "backup_upload_failed",
                        "severity": "warning",
                        "icon": "ti-cloud-off",
                        "message": "Upload remoto fallito (backup locale OK)"
                    })
        else:
            alerts.append({
                "type": "backup_not_configured",
                "severity": "warning",
                "icon": "ti-settings",
                "message": "Backup non configurato"
            })
    except Exception:
        pass
    
    return alerts


system_service = SystemService()


