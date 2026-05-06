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


async def _resolve_agent_token() -> str:
    """Return plaintext agent token from HubConfig (Fernet-decrypted)."""
    from core.database import async_session_maker
    from modules.agent.models import HubConfig
    from modules.agent.ws.client import _decrypt_token
    from sqlalchemy import select

    async with async_session_maker() as session:
        res = await session.execute(select(HubConfig).where(HubConfig.id == 1))
        config = res.scalar_one_or_none()
    if not config or not config.agent_token_enc:
        return ""
    return _decrypt_token(config.agent_token_enc) or ""


async def run_backup(params: dict) -> Tuple[bool, dict]:
    """Trigger a MADMIN backup."""
    try:
        from core.database import async_session_maker
        from core.backup.service import run_backup as _run_backup

        # Replace sentinel with actual agent token for hub HTTP upload
        password = params.get("remote_password")
        if password == "__agent_self_token__":
            password = await _resolve_agent_token()

        async with async_session_maker() as session:
            result = await _run_backup(
                session=session,
                remote_protocol=params.get("remote_protocol"),
                remote_host=params.get("remote_host"),
                remote_port=params.get("remote_port", 22),
                remote_user=params.get("remote_user"),
                remote_password=password,
                remote_path=params.get("remote_path", "/backups"),
                retention_days=params.get("retention_days", 30),
            )
        return result.get("success", False), result
    except Exception as e:
        logger.exception(f"Backup failed: {e}")
        return False, {"error": str(e)}


async def run_restore(params: dict) -> Tuple[bool, dict]:
    """Download backup from hub or remote repo and restore via import_config."""
    import tempfile
    import os

    try:
        from core.database import async_session_maker
        from core.backup.service import import_config, download_remote_backup

        protocol = params.get("remote_protocol")
        host = params.get("remote_host", "")
        port = params.get("remote_port", 22)
        user = params.get("remote_user", "")
        filename = params.get("filename", "")

        password = params.get("remote_password", "")
        if password == "__agent_self_token__":
            password = await _resolve_agent_token()

        archive_path: str | None = None

        if protocol == "http":
            import httpx
            async with httpx.AsyncClient(verify=False, timeout=120) as client:
                resp = await client.get(
                    host,
                    headers={"Authorization": f"Bearer {password}"},
                )
            if resp.status_code != 200:
                return False, {"error": f"Download fallito: HTTP {resp.status_code}"}
            suffix = os.path.splitext(filename)[-1] or ".tar.gz"
            with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
                tmp.write(resp.content)
                archive_path = tmp.name

        elif protocol == "scp":
            import asyncssh, tempfile
            remote_path = params.get("remote_path", "/backups")
            remote_file = f"{remote_path}/{filename}".replace("\\", "/")
            with tempfile.NamedTemporaryFile(suffix=".tar.gz", delete=False) as tmp:
                archive_path = tmp.name
            async with asyncssh.connect(
                host, port=int(port), username=user, password=password, known_hosts=None
            ) as conn:
                await asyncssh.scp((conn, remote_file), archive_path)

        else:
            # sftp / ftp — use existing synchronous helpers (run in executor)
            import asyncio
            remote_path = params.get("remote_path", "/backups")
            loop = asyncio.get_event_loop()
            archive_path = await loop.run_in_executor(
                None,
                download_remote_backup,
                protocol, host, int(port), user, password, remote_path, filename,
            )

        if not archive_path or not os.path.exists(archive_path):
            return False, {"error": "Impossibile scaricare il backup"}

        async with async_session_maker() as session:
            result = await import_config(session, archive_path)

        # Cleanup temp file if we created one
        if protocol in ("http", "scp"):
            try:
                os.unlink(archive_path)
            except Exception:
                pass

        return result.get("success", False), result

    except Exception as e:
        logger.exception(f"Restore failed: {e}")
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
