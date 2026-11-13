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
from typing import Dict, List

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

_apt_cache: dict = {"stamp": None, "data": {}}


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


_INST_RE = re.compile(r"^Inst (\S+) (?:\[([^\]]*)\] )?\((\S+) ([^\[]*)\[([^\]]+)\]\)")
_POLICY_VER_RE = re.compile(r"^ (\*\*\*| {3}) (\S+) (-?\d+)(?: \(phased (\d+)%\))?$")
_SECURITY_SUITE_RE = re.compile(r"-(security|infra-security|apps-security)/")
# Packages whose upgrade needs a reboot to take effect (besides the kernel's)
_REBOOT_PACKAGES = {"libc6", "systemd", "dbus", "linux-base", "linux-firmware", "intel-microcode", "amd64-microcode"}


def _run_c(*cmd: str, timeout: int = 120) -> str:
    return subprocess.run(list(cmd), capture_output=True, text=True, timeout=timeout,
                          env={**os.environ, "LC_ALL": "C"}).stdout


def _list_after(out: str, header: str) -> List[str]:
    """Package names listed (indented) after a header line of apt-get output."""
    lines = out.splitlines()
    for n, line in enumerate(lines):
        if line.startswith(header):
            names = []
            for l in lines[n + 1:]:
                if not l.startswith(" "):
                    break
                names += l.split()
            return names
    return []


def _policy(names: List[str]) -> Dict[str, dict]:
    """apt-cache policy: for each package the security version newer than the
    installed one (the newest from a -security suite) and the phasing of the
    candidate."""
    out: Dict[str, dict] = {}
    if not names:
        return out
    text = _run_c("apt-cache", "policy", *names)
    pkg, info, version, past_installed = None, None, None, False
    for line in text.splitlines():
        if line and not line.startswith(" ") and line.endswith(":"):
            pkg = line[:-1]
            info = out.setdefault(pkg, {"security_version": "", "phased": None, "security_phased": None})
            version, past_installed = None, False
            continue
        if info is None:
            continue
        if line.strip().startswith("Candidate:"):
            info["candidate"] = line.split(":", 1)[1].strip()
            continue
        m = _POLICY_VER_RE.match(line)
        if m:
            version = m.group(2)
            if m.group(1) == "***":
                past_installed = True
            phased = int(m.group(4)) if m.group(4) else None
            if version == info.get("candidate"):
                info["phased"] = phased
            info.setdefault("_phased", {})[version] = phased
            continue
        if version and not past_installed and not info["security_version"] and _SECURITY_SUITE_RE.search(line):
            info["security_version"] = version
            info["security_phased"] = info.get("_phased", {}).get(version)
    for info in out.values():
        info.pop("_phased", None)
    return out


def section_upgrades() -> list:
    """What each OS action would install (ROADMAP 9.1), one item per package:

        all        installed by "Aggiorna tutto" (apt-get upgrade --with-new-pkgs)
        security   installed by "Aggiornamenti di sicurezza" (unattended-upgrade:
                   the newest version from a -security suite, ESM included)
        reason     why it is not installed now: phased (Ubuntu's gradual release,
                   'phased' = percent of machines that get it), held (apt-mark
                   hold), kept (kept back: it would remove or need something else)

    Cached until the package lists or the installed packages change."""
    stamp = _apt_stamp()
    dpkg = os.path.getmtime("/var/lib/dpkg/status") if os.path.exists("/var/lib/dpkg/status") else 0
    if _apt_cache["stamp"] == (stamp, dpkg) and "upgrades" in _apt_cache["data"]:
        return _apt_cache["data"]["upgrades"]
    sim = _run_c("apt-get", "-s", "-o", "Debug::NoLocking=1", "--with-new-pkgs", "upgrade")
    items: Dict[str, dict] = {}
    for line in sim.splitlines():
        m = _INST_RE.match(line)
        if not m:
            continue
        name, old, new, origins, arch = m.groups()
        items[f"{name}:{arch}"] = {"name": name, "arch": arch, "installed": old or "", "candidate": new,
                                   "origin": "security" if "-security" in origins else "updates",
                                   "all": True, "security": False, "security_version": "", "reason": "",
                                   "phased": None}
    phased = set(_list_after(sim, "The following upgrades have been deferred due to phasing:"))
    kept = set(_list_after(sim, "The following packages have been kept back:"))
    held = set(_run_c("apt-mark", "showhold").split())
    for line in _run_c("apt", "list", "--upgradable").splitlines():
        m = re.match(r"^([^/\s]+)/\S+ (\S+) (\S+) \[upgradable from: ([^\]]+)\]", line)
        if not m:
            continue
        name, candidate, arch, installed = m.groups()
        key = f"{name}:{arch}"
        if key in items:
            continue
        reason = "held" if name in held else "phased" if name in phased else "kept" if name in kept else "kept"
        items[key] = {"name": name, "arch": arch, "installed": installed, "candidate": candidate, "origin": "updates",
                      "all": False, "security": False, "security_version": "", "reason": reason, "phased": None}
    policy = _policy(sorted({i["name"] for i in items.values() if i["installed"]}))
    for item in items.values():
        pol = policy.get(item["name"]) or {}
        item["phased"] = pol.get("phased")
        sec = pol.get("security_version", "")
        if not item["installed"]:
            # a new package pulled in by the upgrade (a new kernel): its own suite decides
            item["security"] = item["origin"] == "security"
            item["security_version"] = item["candidate"] if item["security"] else ""
        elif sec and item["name"] not in held and not pol.get("security_phased"):
            item["security"] = True
            item["security_version"] = sec
        # security: the newest version is a security one; mixed: the security
        # one is older than the candidate (only "all" installs the candidate)
        item["origin"] = ("security" if item["security_version"] == item["candidate"] else "mixed") \
            if item["security"] else "updates"
        name = item["name"]
        item["reboot"] = name.startswith(("linux-image-", "linux-modules-")) or name in _REBOOT_PACKAGES
    result = sorted(items.values(), key=lambda i: (i["name"], i["arch"]))
    _apt_cache["stamp"] = (stamp, dpkg)
    _apt_cache["data"] = {"upgrades": result}
    return result


def _pending_updates() -> dict:
    """Counts for the facts, from section_upgrades (same simulation)."""
    try:
        items = section_upgrades()
    except (OSError, subprocess.SubprocessError) as e:
        logger.warning("Manager inventory: apt simulation failed: %s", e)
        return {}
    return {"pending_updates": sum(1 for i in items if i["all"]),
            "pending_security": sum(1 for i in items if i["security"]),
            "pending_held_back": sum(1 for i in items if i["reason"])}


def _unattended_upgrades() -> bool:
    conf = "".join(_read(p) for p in glob.glob("/etc/apt/apt.conf.d/*"))
    return bool(re.search(r'APT::Periodic::Unattended-Upgrade\s+"1"', conf)) and \
        os.path.exists("/usr/bin/unattended-upgrade")


def _scheduled_reboot():
    """Epoch of a pending `shutdown -r`, or None."""
    data = dict(l.split("=", 1) for l in _read("/run/systemd/shutdown/scheduled").splitlines() if "=" in l)
    if data.get("MODE") != "reboot" or not data.get("USEC", "").isdigit():
        return None
    return int(data["USEC"]) // 1_000_000


def os_status() -> dict:
    from .osactions import kernel_state
    kernels = _installed_kernels()
    stamp = _apt_stamp()
    return {
        "reboot_scheduled_at": _scheduled_reboot(),
        "kernel_trial": kernel_state(),
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


SECTIONS = {"packages": section_packages, "python": section_python, "upgrades": section_upgrades}


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
