"""
Enrollment: POST one-time token to Hub /api/agents/enroll,
receive agent_token + instance_id, persist encrypted.
"""
import base64
import hashlib
import logging
from datetime import datetime

import httpx

logger = logging.getLogger(__name__)


def _machine_fingerprint() -> str:
    """Stable per-machine identifier derived from /etc/machine-id + hostname."""
    import socket
    try:
        with open("/etc/machine-id") as f:
            machine_id = f.read().strip()
    except OSError:
        machine_id = "unknown"
    raw = f"{machine_id}:{socket.gethostname()}"
    return hashlib.sha256(raw.encode()).hexdigest()


async def enroll(hub_url: str, enrollment_token: str, instance_name: str) -> dict:
    """
    Call Hub enrollment endpoint with the one-time token.
    Returns dict with keys: success, error, instance_id.
    """
    import platform
    url = hub_url.rstrip("/") + "/api/agents/enroll"
    payload = {
        "enrollment_token": enrollment_token,
        "name": instance_name,
        "fingerprint": _machine_fingerprint(),
        "version": "1.0.0",
        "os_info": {
            "system": platform.system(),
            "release": platform.release(),
            "machine": platform.machine(),
        },
    }

    try:
        # Accept self-signed Hub cert (Hub is internal infrastructure)
        async with httpx.AsyncClient(verify=False, timeout=15.0) as client:
            resp = await client.post(url, json=payload)
    except httpx.ConnectError as e:
        return {"success": False, "error": f"Connessione rifiutata: {e}"}
    except httpx.TimeoutException:
        return {"success": False, "error": "Timeout connessione Hub"}
    except Exception as e:
        return {"success": False, "error": str(e)}

    if resp.status_code not in (200, 201):
        try:
            detail = resp.json().get("detail", resp.text[:200])
        except Exception:
            detail = resp.text[:200]
        return {"success": False, "error": f"Hub error {resp.status_code}: {detail}"}

    data = resp.json()
    agent_token = data.get("agent_token")
    instance_id = data.get("instance_id")

    if not agent_token or not instance_id:
        return {"success": False, "error": "Risposta Hub incompleta (mancano agent_token o instance_id)"}

    # Persist to DB
    await _save_enrollment(
        hub_url=hub_url,
        instance_id=instance_id,
        instance_name=instance_name,
        agent_token=agent_token,
    )

    return {"success": True, "instance_id": instance_id}


async def _save_enrollment(hub_url: str, instance_id: str, instance_name: str, agent_token: str):
    from core.database import async_session_maker
    from sqlalchemy import update
    from modules.agent.models import HubConfig

    enc = _encrypt_token(agent_token)

    async with async_session_maker() as session:
        await session.execute(
            update(HubConfig).where(HubConfig.id == 1).values(
                hub_url=hub_url,
                instance_id=instance_id,
                instance_name=instance_name,
                agent_token_enc=enc,
                enrollment_status="enrolled",
                enrolled_at=datetime.utcnow(),
                updated_at=datetime.utcnow(),
                # Clear setup defaults — one-time token consumed
                setup_hub_url=None,
                setup_enrollment_token_enc=None,
                setup_instance_name=None,
            )
        )
        await session.commit()
    logger.info(f"Enrolled as instance {instance_id} on {hub_url}")


async def revoke_local(notify_hub: bool = True):
    """
    Revoke local enrollment. Optionally notify Hub.
    Called on module disable or user-initiated disconnect.
    """
    from core.database import async_session_maker
    from sqlalchemy import select, update
    from modules.agent.models import HubConfig

    async with async_session_maker() as session:
        result = await session.execute(select(HubConfig).where(HubConfig.id == 1))
        config = result.scalar_one_or_none()
        if not config or config.enrollment_status == "not_enrolled":
            return

        if notify_hub and config.hub_url and config.agent_token_enc:
            await _notify_hub_revoke(config)

        await session.execute(
            update(HubConfig).where(HubConfig.id == 1).values(
                enrollment_status="not_enrolled",
                agent_token_enc=None,
                instance_id=None,
                ws_connected=False,
                updated_at=datetime.utcnow(),
            )
        )
        await session.commit()
    logger.info("Local enrollment revoked")


async def _notify_hub_revoke(config):
    """Best-effort: tell Hub this agent is disconnecting."""
    from modules.agent.ws.client import _decrypt_token
    token = _decrypt_token(config.agent_token_enc)
    if not token:
        return
    url = config.hub_url.rstrip("/") + "/api/agents/self/revoke"
    try:
        async with httpx.AsyncClient(verify=False, timeout=5.0) as client:
            await client.post(url, headers={"Authorization": f"Bearer {token}"})
    except Exception:
        pass  # best-effort


def _encrypt_token(raw: str) -> str:
    from config import get_settings
    from cryptography.fernet import Fernet
    s = get_settings()
    key_bytes = hashlib.sha256(f"{s.secret_key}|agent_token".encode()).digest()
    fernet = Fernet(base64.urlsafe_b64encode(key_bytes))
    return fernet.encrypt(raw.encode()).decode()
