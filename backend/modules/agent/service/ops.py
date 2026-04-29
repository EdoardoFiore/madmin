"""
Wrappers for service control, backup trigger, firewall reload.
Called from ws/handlers.py.
"""
import logging
from typing import Tuple

logger = logging.getLogger(__name__)


async def service_action(service_name: str, op: str) -> Tuple[bool, str]:
    """start | stop | restart a systemd service."""
    import asyncio, subprocess

    allowed_ops = {"start", "stop", "restart"}
    if op not in allowed_ops:
        return False, f"Invalid op: {op}"

    # Basic allowlist to prevent arbitrary service manipulation
    ALLOWED_SERVICES = {
        "madmin", "nginx", "postgresql",
        "isc-dhcp-server", "named", "bind9",
        "openvpn", "wg-quick@*", "strongswan",
    }

    def _is_allowed(name: str) -> bool:
        for pat in ALLOWED_SERVICES:
            if pat.endswith("*"):
                if name.startswith(pat[:-1]):
                    return True
            elif name == pat:
                return True
        return False

    if not _is_allowed(service_name):
        return False, f"Service '{service_name}' not in allowlist"

    try:
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            None,
            lambda: subprocess.run(
                ["systemctl", op, service_name],
                capture_output=True,
                text=True,
                timeout=30,
            ),
        )
        if result.returncode == 0:
            logger.info(f"Service {service_name} {op} OK")
            return True, f"systemctl {op} {service_name}: OK"
        else:
            err = result.stderr.strip()
            logger.warning(f"Service {service_name} {op} failed: {err}")
            return False, err
    except Exception as e:
        return False, str(e)


async def run_backup(params: dict) -> Tuple[bool, dict]:
    """Trigger a MADMIN backup."""
    try:
        from core.database import async_session_maker
        from core.backup.service import run_backup as _run_backup

        async with async_session_maker() as session:
            result = await _run_backup(
                session=session,
                remote_protocol=params.get("remote_protocol"),
                remote_host=params.get("remote_host"),
                remote_port=params.get("remote_port", 22),
                remote_user=params.get("remote_user"),
                remote_password=params.get("remote_password"),
                remote_path=params.get("remote_path", "/backups"),
                retention_days=params.get("retention_days", 30),
            )
        return result.get("success", False), result
    except Exception as e:
        logger.exception(f"Backup failed: {e}")
        return False, {"error": str(e)}


async def reload_firewall() -> Tuple[bool, str]:
    """Re-apply firewall rules from DB."""
    try:
        from core.database import async_session_maker
        from core.firewall.orchestrator import firewall_orchestrator

        async with async_session_maker() as session:
            await firewall_orchestrator.apply_rules(session)
        return True, "Firewall rules reloaded"
    except Exception as e:
        logger.exception(f"Firewall reload failed: {e}")
        return False, str(e)
