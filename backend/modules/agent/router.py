"""
Agent module UI endpoints.
Hub does NOT call these — they are for the local MADMIN UI only.
"""
import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select, desc
from sqlalchemy.ext.asyncio import AsyncSession

from core.auth.dependencies import require_permission
from core.auth.models import User
from core.database import get_session

from .models import AgentLog, HubConfig, PushedSSHKey

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/agent", tags=["Hub Agent"])


# --- Schemas ---

class EnrollRequest(BaseModel):
    hub_url: str
    enrollment_token: str
    instance_name: Optional[str] = None


class StatusResponse(BaseModel):
    enrollment_status: str
    hub_url: Optional[str]
    instance_id: Optional[str]
    instance_name: Optional[str]
    ws_connected: bool
    last_heartbeat_at: Optional[str]
    reconnect_attempt: int


# --- Endpoints ---

@router.get("/status")
async def get_status(
    _: User = Depends(require_permission("agent.view")),
    session: AsyncSession = Depends(get_session),
):
    """Return enrollment state + live WS connection status."""
    result = await session.execute(select(HubConfig).where(HubConfig.id == 1))
    config = result.scalar_one_or_none()

    from .ws.client import get_state
    ws_state = get_state()

    return {
        "enrollment_status": config.enrollment_status if config else "not_enrolled",
        "hub_url": config.hub_url if config else None,
        "instance_id": config.instance_id if config else None,
        "instance_name": config.instance_name if config else None,
        "ws_connected": ws_state["connected"],
        "last_heartbeat_at": config.last_heartbeat_at.isoformat() if config and config.last_heartbeat_at else None,
        "reconnect_attempt": ws_state["reconnect_attempt"],
        "last_connected_at": ws_state.get("last_connected_at"),
        "last_disconnected_at": ws_state.get("last_disconnected_at"),
    }


@router.post("/enroll")
async def enroll(
    body: EnrollRequest,
    user: User = Depends(require_permission("agent.manage")),
    session: AsyncSession = Depends(get_session),
):
    """
    Perform enrollment: call Hub with one-time token, save agent token,
    start WS connection.
    """
    result = await session.execute(select(HubConfig).where(HubConfig.id == 1))
    config = result.scalar_one_or_none()
    if config and config.enrollment_status == "enrolled":
        raise HTTPException(status_code=400, detail="Già enrollato. Esegui disconnect prima.")

    from .service.enrollment import enroll as do_enroll

    instance_name = body.instance_name or _get_hostname()
    res = await do_enroll(
        hub_url=body.hub_url,
        enrollment_token=body.enrollment_token,
        instance_name=instance_name,
    )
    if not res["success"]:
        raise HTTPException(status_code=400, detail=res["error"])

    # Restart WS client task to pick up new config immediately
    from .tasks import stop_agent_tasks, start_agent_tasks
    await stop_agent_tasks()
    await start_agent_tasks()

    return {"success": True, "instance_id": res["instance_id"]}


@router.post("/disconnect")
async def disconnect(
    _: User = Depends(require_permission("agent.manage")),
):
    """Revoke enrollment locally + notify Hub, stop WS."""
    from .tasks import stop_agent_tasks
    from .service.enrollment import revoke_local

    await stop_agent_tasks()
    await revoke_local(notify_hub=True)

    return {"success": True}


@router.get("/logs")
async def get_logs(
    limit: int = 100,
    _: User = Depends(require_permission("agent.view")),
    session: AsyncSession = Depends(get_session),
):
    """Return recent agent event log entries."""
    result = await session.execute(
        select(AgentLog).order_by(desc(AgentLog.ts)).limit(limit)
    )
    logs = result.scalars().all()
    return [
        {
            "ts": l.ts.isoformat(),
            "level": l.level,
            "event": l.event,
            "detail": l.detail,
        }
        for l in logs
    ]


@router.get("/ssh-keys")
async def get_pushed_keys(
    _: User = Depends(require_permission("agent.view")),
    session: AsyncSession = Depends(get_session),
):
    """List pushed SSH key assignments on this instance."""
    result = await session.execute(
        select(PushedSSHKey).where(PushedSSHKey.active == True)
    )
    keys = result.scalars().all()
    return [
        {
            "id": k.id,
            "assignment_id": k.assignment_id,
            "target_user": k.target_user,
            "pushed_at": k.pushed_at.isoformat(),
            "expires_at": k.expires_at.isoformat() if k.expires_at else None,
        }
        for k in keys
    ]


def _get_hostname() -> str:
    try:
        import platform
        return platform.node()
    except Exception:
        return "madmin-instance"
