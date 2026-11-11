"""
Facts this instance reports to the manager: what it is (version, modules, OS) and
where it is (hostname, interface addresses). The manager keeps the history of the
addresses; the identity is the certificate, so a changed IP or hostname is a
change of the same instance.
"""
import asyncio
import hashlib
import json
import logging
import platform
import socket

from config import build_info

logger = logging.getLogger(__name__)


def _read(path: str) -> str:
    try:
        with open(path) as f:
            return f.read().strip()
    except OSError:
        return ""


def _os_name() -> str:
    for line in _read("/etc/os-release").splitlines():
        if line.startswith("PRETTY_NAME="):
            return line.split("=", 1)[1].strip().strip('"')
    return platform.system()


def _system_facts() -> dict:
    from core.network.service import NetworkService
    from core.system.ssh import get_ssh_ports
    from core.system.service import SystemService

    interfaces = [
        {
            "name": i["name"],
            "mac": i.get("mac"),
            "is_up": bool(i.get("is_up")),
            "ipv4": [
                f"{a['address']}/{a['netmask']}" for a in i.get("addr_info", [])
            ],
            "ipv6": i.get("ipv6"),
        }
        for i in NetworkService.get_interfaces()
    ]
    uptime = SystemService.get_uptime()
    return {
        # version, build, release_id, layout
        **build_info(),
        "hostname": socket.gethostname(),
        "machine_id": _read("/etc/machine-id"),
        "os": _os_name(),
        "kernel": platform.release(),
        "boot_time": uptime.get("boot_time"),
        "interfaces": interfaces,
        "ssh_ports": get_ssh_ports(),
    }


async def _modules() -> list:
    from sqlmodel import select
    from core.database import async_session_maker
    from core.modules.models import InstalledModule

    async with async_session_maker() as session:
        rows = (await session.execute(select(InstalledModule))).scalars().all()
    return sorted(
        ({"id": m.id, "version": m.version, "enabled": m.enabled} for m in rows),
        key=lambda m: m["id"],
    )


async def collect_facts() -> dict:
    facts = await asyncio.to_thread(_system_facts)
    try:
        facts["modules"] = await _modules()
    except Exception as e:
        logger.warning("Manager inventory: modules not readable: %s", e)
        facts["modules"] = []
    return facts


def facts_digest(facts: dict) -> str:
    """Changes only when a reported fact changes (boot_time included)."""
    return hashlib.sha256(json.dumps(facts, sort_keys=True).encode()).hexdigest()


def _stats() -> dict:
    from core.system.service import SystemService
    s = SystemService.get_stats()
    if not s.get("available"):
        return {}
    return {
        "cpu_percent": s["cpu"]["percent"],
        "mem_percent": s["memory"]["percent"],
        "disk_percent": s["disk"]["percent"],
    }


async def collect_stats() -> dict:
    return await asyncio.to_thread(_stats)
