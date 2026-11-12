"""
Facts this instance reports to the manager: what it is (version, modules, OS) and
where it is (hostname, interface addresses). The manager keeps the history of the
addresses; the identity is the certificate, so a changed IP or hostname is a
change of the same instance.
"""
import asyncio
import glob
import hashlib
import json
import logging
import os
import platform
import re
import socket
import subprocess
import time
from importlib import metadata

from config import build_info

logger = logging.getLogger(__name__)


def _read(path: str) -> str:
    try:
        with open(path) as f:
            return f.read().strip()
    except OSError:
        return ""


def _os_id() -> str:
    """ID-VERSION_ID, as release manifests list it (ubuntu-24.04)."""
    info = {k: v.strip('"') for k, v in (line.split("=", 1) for line in
                                          _read("/etc/os-release").splitlines() if "=" in line)}
    return f"{info.get('ID', '')}-{info.get('VERSION_ID', '')}"


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
        "os_id": _os_id(),
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


# --- OS state and heavy sections (ROADMAP 8.1) ---

_APT_CACHE_SECONDS = 3600
_apt_cache: dict = {"at": 0.0, "stamp": None, "data": {}}


def _kernel_key(name: str) -> tuple:
    return tuple(int(n) if n.isdigit() else n for n in re.split(r"[.\-+~]", name))


def _installed_kernels() -> list:
    names = [os.path.basename(p)[len("vmlinuz-"):] for p in glob.glob("/boot/vmlinuz-*")]
    return sorted(names, key=_kernel_key)


def _apt_stamp() -> float:
    """When the package lists were last refreshed (apt-get update)."""
    times = [os.path.getmtime(p) for p in ("/var/lib/apt/periodic/update-success-stamp",
                                           "/var/lib/apt/lists/partial") if os.path.exists(p)]
    times += [os.path.getmtime(p) for p in glob.glob("/var/lib/apt/lists/*_InRelease")]
    return max(times) if times else 0.0


def _pending_updates() -> dict:
    """apt-get -s dist-upgrade: what an upgrade would install, and how much of
    it comes from the security pocket. Cached: it takes seconds."""
    stamp = _apt_stamp()
    dpkg = os.path.getmtime("/var/lib/dpkg/status") if os.path.exists("/var/lib/dpkg/status") else 0
    if time.monotonic() - _apt_cache["at"] < _APT_CACHE_SECONDS and _apt_cache["stamp"] == (stamp, dpkg):
        return _apt_cache["data"]
    data = {}
    try:
        out = subprocess.run(["apt-get", "-s", "-o", "Debug::NoLocking=1", "dist-upgrade"],
                             capture_output=True, text=True, timeout=120,
                             env={**os.environ, "LC_ALL": "C"}).stdout
        lines = [l for l in out.splitlines() if l.startswith("Inst ")]
        data = {"pending_updates": len(lines),
                "pending_security": sum(1 for l in lines if "-security" in l)}
    except (OSError, subprocess.SubprocessError) as e:
        logger.warning("Manager inventory: apt simulation failed: %s", e)
    _apt_cache.update(at=time.monotonic(), stamp=(stamp, dpkg), data=data)
    return data


def _unattended_upgrades() -> bool:
    conf = "".join(_read(p) for p in glob.glob("/etc/apt/apt.conf.d/*"))
    return bool(re.search(r'APT::Periodic::Unattended-Upgrade\s+"1"', conf)) and \
        os.path.exists("/usr/bin/unattended-upgrade")


def os_status() -> dict:
    kernels = _installed_kernels()
    stamp = _apt_stamp()
    return {
        "running_kernel": platform.release(),
        "newest_kernel": kernels[-1] if kernels else "",
        "kernels": kernels,
        "reboot_required": os.path.exists("/var/run/reboot-required"),
        "reboot_packages": sorted(set(_read("/var/run/reboot-required.pkgs").split())),
        "unattended_upgrades": _unattended_upgrades(),
        "apt_updated_at": int(stamp) if stamp else None,
        **_pending_updates(),
    }


def section_packages() -> list:
    """Installed Debian packages, with their source package (what the Ubuntu
    security data is indexed by)."""
    out = subprocess.run(
        ["dpkg-query", "-W", "-f", "${db:Status-Abbrev}\t${Package}\t${Version}\t${Architecture}\t"
                                   "${source:Package}\t${source:Version}\n"],
        capture_output=True, text=True, timeout=60, env={**os.environ, "LC_ALL": "C"},
    ).stdout
    items = []
    for line in out.splitlines():
        parts = line.split("\t")
        if len(parts) != 6 or not parts[0].startswith("ii"):
            continue
        _, name, version, arch, source, source_version = parts
        items.append({"name": name, "version": version, "arch": arch,
                      "source": source or name, "source_version": source_version or version})
    return sorted(items, key=lambda i: (i["name"], i["arch"]))


def section_python() -> list:
    """Packages of the venv MADMIN runs in."""
    seen = {}
    for dist in metadata.distributions():
        name = (dist.metadata.get("Name") or "").strip()
        if name:
            seen[name.lower()] = {"name": name, "version": dist.version}
    return [seen[k] for k in sorted(seen)]


SECTIONS = {"packages": section_packages, "python": section_python}


def section_digest(items: list) -> str:
    return hashlib.sha256(json.dumps(items, sort_keys=True).encode()).hexdigest()


async def collect_section(name: str) -> list:
    return await asyncio.to_thread(SECTIONS[name])


async def collect_facts() -> dict:
    facts = await asyncio.to_thread(_system_facts)
    try:
        facts["modules"] = await _modules()
    except Exception as e:
        logger.warning("Manager inventory: modules not readable: %s", e)
        facts["modules"] = []
    # os_status, sections: protocol revision 1 additions (an older manager
    # ignores unknown facts)
    try:
        facts["os_status"] = await asyncio.to_thread(os_status)
    except Exception as e:
        logger.warning("Manager inventory: OS state not readable: %s", e)
    sections = {}
    for name in SECTIONS:
        try:
            sections[name] = section_digest(await collect_section(name))
        except Exception as e:
            logger.warning("Manager inventory: section %s not readable: %s", name, e)
    facts["sections"] = sections
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
