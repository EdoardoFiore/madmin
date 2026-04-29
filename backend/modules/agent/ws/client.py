"""
Persistent WebSocket client.
Opens WSS connection to Hub, keeps it alive with ping/pong,
auto-reconnects with exponential backoff (1s → 60s).
Dispatches inbound command frames to handlers.
Sends heartbeat frames on a timer.
"""
import asyncio
import json
import logging
import ssl
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger(__name__)

_PING_INTERVAL = 20  # seconds between keep-alive pings
_RECONNECT_MIN = 1
_RECONNECT_MAX = 60

# Module-level connection state (readable by router/status endpoint)
_state = {
    "connected": False,
    "reconnect_attempt": 0,
    "last_connected_at": None,
    "last_disconnected_at": None,
}


def get_state() -> dict:
    return dict(_state)


async def run_ws_client():
    """
    Main loop: connect → serve → disconnect → backoff → repeat.
    Cancelled on module disable / app shutdown.
    """
    from modules.agent.service.heartbeat import collect_heartbeat_payload
    from modules.agent.ws.handlers import dispatch_command

    delay = _RECONNECT_MIN

    while True:
        config = await _load_config()
        if not config or config.enrollment_status != "enrolled" or not config.hub_url or not config.agent_token_enc:
            logger.debug("Agent not enrolled or token missing — waiting 30s before retry")
            await asyncio.sleep(30)
            continue

        token = _decrypt_token(config.agent_token_enc)
        if not token:
            logger.error("Failed to decrypt agent token — aborting WS connect")
            await asyncio.sleep(30)
            continue

        ws_url = config.hub_url.rstrip("/") + "/api/agents/ws"
        # Convert https:// → wss://, http:// → ws://
        ws_url = ws_url.replace("https://", "wss://").replace("http://", "ws://")

        ssl_ctx = _build_ssl_context(config.hub_ca_fingerprint)

        try:
            import websockets
            logger.info(f"Connecting to Hub WS: {ws_url}")
            async with websockets.connect(
                ws_url,
                additional_headers={"Authorization": f"Bearer {token}"},
                ssl=ssl_ctx,
                ping_interval=_PING_INTERVAL,
                ping_timeout=10,
                close_timeout=5,
                max_size=1 * 1024 * 1024,  # 1 MB max frame
            ) as ws:
                _state["connected"] = True
                _state["reconnect_attempt"] = 0
                _state["last_connected_at"] = datetime.now(timezone.utc).isoformat()
                delay = _RECONNECT_MIN
                await _set_ws_connected(True)
                await _log_event("ws_connected", "info", "Connessione Hub stabilita")
                logger.info("Hub WS connected")

                heartbeat_task = asyncio.create_task(
                    _heartbeat_loop(ws, collect_heartbeat_payload)
                )

                try:
                    async for raw in ws:
                        try:
                            frame = json.loads(raw)
                        except json.JSONDecodeError:
                            logger.warning(f"Non-JSON frame: {raw[:80]}")
                            continue

                        ftype = frame.get("type")
                        payload = frame.get("payload", {})

                        if ftype == "command":
                            asyncio.create_task(dispatch_command(ws, payload))
                        elif ftype == "config_update":
                            await _handle_config_update(payload)
                        elif ftype == "pong":
                            pass
                        else:
                            logger.debug(f"Unknown frame type: {ftype}")
                finally:
                    heartbeat_task.cancel()
                    try:
                        await heartbeat_task
                    except asyncio.CancelledError:
                        pass

        except asyncio.CancelledError:
            logger.info("WS client task cancelled")
            raise
        except Exception as e:
            logger.warning(f"WS connection lost: {e}")
        finally:
            _state["connected"] = False
            _state["last_disconnected_at"] = datetime.now(timezone.utc).isoformat()
            await _set_ws_connected(False)
            await _log_event("ws_disconnected", "warning", f"Connessione Hub persa — retry in {delay}s")

        _state["reconnect_attempt"] += 1
        logger.info(f"Reconnecting in {delay}s (attempt {_state['reconnect_attempt']})")
        await asyncio.sleep(delay)
        delay = min(delay * 2, _RECONNECT_MAX)


async def _heartbeat_loop(ws, collect_fn):
    """Send heartbeat every 60s (overridable via config_update)."""
    interval = 60
    while True:
        await asyncio.sleep(interval)
        try:
            payload = await asyncio.get_event_loop().run_in_executor(None, collect_fn)
            await ws.send(json.dumps({"type": "heartbeat", "payload": payload}))
            await _update_last_heartbeat()
            logger.debug("Heartbeat sent")
        except Exception as e:
            logger.warning(f"Heartbeat send failed: {e}")
            break


async def _handle_config_update(payload: dict):
    """Handle config_update frame: new token, heartbeat interval, etc."""
    from core.database import async_session_maker
    from sqlalchemy import select, update
    from modules.agent.models import HubConfig

    if "agent_token" in payload:
        new_token = payload["agent_token"]
        enc = _encrypt_token(new_token)
        async with async_session_maker() as session:
            await session.execute(
                update(HubConfig).where(HubConfig.id == 1).values(
                    agent_token_enc=enc,
                    updated_at=datetime.utcnow(),
                )
            )
            await session.commit()
        logger.info("Agent token rotated via config_update")
        await _log_event("token_rotated", "info", "Token agent aggiornato dall'Hub")


async def _load_config():
    from core.database import async_session_maker
    from sqlalchemy import select
    from modules.agent.models import HubConfig

    try:
        async with async_session_maker() as session:
            result = await session.execute(select(HubConfig).where(HubConfig.id == 1))
            return result.scalar_one_or_none()
    except Exception as e:
        logger.error(f"Failed to load HubConfig: {e}")
        return None


async def _set_ws_connected(connected: bool):
    from core.database import async_session_maker
    from sqlalchemy import update
    from modules.agent.models import HubConfig

    try:
        async with async_session_maker() as session:
            await session.execute(
                update(HubConfig).where(HubConfig.id == 1).values(
                    ws_connected=connected,
                    updated_at=datetime.utcnow(),
                )
            )
            await session.commit()
    except Exception as e:
        logger.debug(f"_set_ws_connected failed: {e}")


async def _update_last_heartbeat():
    from core.database import async_session_maker
    from sqlalchemy import update
    from modules.agent.models import HubConfig

    try:
        async with async_session_maker() as session:
            await session.execute(
                update(HubConfig).where(HubConfig.id == 1).values(
                    last_heartbeat_at=datetime.utcnow(),
                    updated_at=datetime.utcnow(),
                )
            )
            await session.commit()
    except Exception:
        pass


async def _log_event(event: str, level: str = "info", detail: str = None):
    from core.database import async_session_maker
    from modules.agent.models import AgentLog
    from sqlalchemy import delete, func, select

    try:
        async with async_session_maker() as session:
            session.add(AgentLog(level=level, event=event, detail=detail))
            await session.commit()
            # Keep only last 500 log rows
            count_result = await session.execute(select(func.count()).select_from(AgentLog))
            count = count_result.scalar()
            if count > 500:
                subq = (
                    select(AgentLog.id)
                    .order_by(AgentLog.ts.asc())
                    .limit(count - 500)
                    .scalar_subquery()
                )
                await session.execute(delete(AgentLog).where(AgentLog.id.in_(subq)))
                await session.commit()
    except Exception:
        pass


def _decrypt_token(enc: str) -> Optional[str]:
    try:
        from config import get_settings
        from cryptography.fernet import Fernet
        import base64, hashlib
        s = get_settings()
        key_bytes = hashlib.sha256(f"{s.secret_key}|agent_token".encode()).digest()
        fernet = Fernet(base64.urlsafe_b64encode(key_bytes))
        return fernet.decrypt(enc.encode()).decode()
    except Exception as e:
        logger.error(f"Token decrypt failed: {e}")
        return None


def _encrypt_token(raw: str) -> str:
    from config import get_settings
    from cryptography.fernet import Fernet
    import base64, hashlib
    s = get_settings()
    key_bytes = hashlib.sha256(f"{s.secret_key}|agent_token".encode()).digest()
    fernet = Fernet(base64.urlsafe_b64encode(key_bytes))
    return fernet.encrypt(raw.encode()).decode()


def _build_ssl_context(ca_fingerprint: Optional[str]) -> Optional[ssl.SSLContext]:
    """Build SSL context. Accepts self-signed certs unless ca_fingerprint pinning configured."""
    ctx = ssl.create_default_context()
    if not ca_fingerprint:
        # Accept self-signed Hub certs (Hub is internal infrastructure)
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
    return ctx
