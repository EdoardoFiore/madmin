"""
Ports the OpenSSH server listens on.

The installer moves SSH off 22 (setup-madmin.sh, MADMIN_SSH_PORT) so common
ports stay free for port forwarding to internal hosts; an operator may move it
again by hand. The port is therefore read from sshd's effective configuration
(`sshd -T`, which also resolves the sshd_config.d drop-ins and is what
Ubuntu's ssh.socket generator uses), never assumed.
"""
import asyncio
import logging
import os
import subprocess
import time
from typing import List, Optional, Tuple

logger = logging.getLogger(__name__)

SSHD_BIN = "/usr/sbin/sshd"
# With socket activation (Ubuntu 24.04) it exists only while ssh.service runs:
# until someone connects, `sshd -T` fails with "Missing privilege separation
# directory" and the real port would be lost
SSHD_RUN_DIR = "/run/sshd"
# Port sshd uses when the configuration cannot be read
SSH_DEFAULT_PORT = 22
_CACHE_TTL = 30.0

_cache: Optional[Tuple[float, List[int]]] = None


def parse_sshd_ports(output: str) -> List[int]:
    """`port N` lines of `sshd -T` output, sorted and without duplicates."""
    ports = set()
    for line in output.splitlines():
        parts = line.split()
        if len(parts) == 2 and parts[0].lower() == "port" and parts[1].isdigit():
            port = int(parts[1])
            if 1 <= port <= 65535:
                ports.add(port)
    return sorted(ports)


def _read_ssh_ports() -> List[int]:
    if not os.path.exists(SSHD_BIN):
        return []  # OpenSSH server not installed: no SSH port to protect
    try:
        os.makedirs(SSHD_RUN_DIR, mode=0o755, exist_ok=True)
    except OSError as e:
        logger.debug("cannot create %s: %s", SSHD_RUN_DIR, e)
    try:
        r = subprocess.run(
            [SSHD_BIN, "-T"], capture_output=True, text=True, timeout=10
        )
    except (OSError, subprocess.TimeoutExpired) as e:
        logger.warning("sshd -T failed (%s): assuming port %d", e, SSH_DEFAULT_PORT)
        return [SSH_DEFAULT_PORT]
    ports = parse_sshd_ports(r.stdout) if r.returncode == 0 else []
    if not ports:
        logger.warning(
            "sshd -T returned no port (%s): assuming port %d",
            (r.stderr or "").strip()[:200], SSH_DEFAULT_PORT,
        )
        return [SSH_DEFAULT_PORT]
    return ports


def get_ssh_ports() -> List[int]:
    """Ports sshd listens on ([] if it is not installed). Blocking, cached for
    a few seconds: from async code use ssh_ports()."""
    global _cache
    now = time.monotonic()
    if _cache is not None and now - _cache[0] < _CACHE_TTL:
        return list(_cache[1])
    ports = _read_ssh_ports()
    _cache = (now, ports)
    return list(ports)


async def ssh_ports() -> List[int]:
    return await asyncio.to_thread(get_ssh_ports)
