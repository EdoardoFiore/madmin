"""
Collect system stats for heartbeat payload.
Synchronous — called via run_in_executor from async context.
"""
import logging
import os
import subprocess
from config import MADMIN_VERSION

logger = logging.getLogger(__name__)


def collect_heartbeat_payload() -> dict:
    """Build heartbeat dict from core/system service."""
    from core.system.service import SystemService

    stats = SystemService.get_stats()
    net = SystemService.get_network_traffic()
    services = SystemService.get_services_status()

    payload: dict = {
        "version": MADMIN_VERSION,
        "os_info": _get_os_info(),
    }

    if stats.get("available"):
        cpu = stats["cpu"]
        mem = stats["memory"]
        disk = stats["disk"]
        payload["cpu_percent"] = cpu["percent"]
        payload["ram_percent"] = mem["percent"]
        payload["ram_total"] = mem["total"]
        payload["disk_percent"] = disk["percent"]
        payload["disk_total"] = disk["total"]

    # Network traffic: sum across all non-loopback interfaces
    if net and isinstance(net, dict):
        in_bps, out_bps = 0, 0
        for iface, counters in net.items():
            if isinstance(counters, dict):
                in_bps += counters.get("bytes_recv_rate", 0)
                out_bps += counters.get("bytes_sent_rate", 0)
        payload["net_in_bps"] = in_bps
        payload["net_out_bps"] = out_bps

    payload["services_status"] = {
        svc: info.get("status", "unknown")
        for svc, info in services.items()
    }

    payload["modules_status"] = _get_modules_status()

    return payload


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
        import platform
        info["hostname"] = platform.node()
        info["kernel"] = platform.release()
    except Exception:
        pass
    return info


def _get_modules_status() -> dict:
    """Return dict of enabled module IDs → 'enabled'."""
    try:
        from core.modules.loader import module_loader
        return {mid: "enabled" for mid in module_loader.loaded_modules.keys()}
    except Exception:
        return {}
