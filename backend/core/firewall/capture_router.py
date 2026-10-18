"""
MADMIN traffic capture API

Live tcpdump for troubleshooting (see capture.py). The capture streams as
NDJSON over a plain HTTP response read with fetch(): the JWT travels in the
Authorization header, which EventSource cannot send. X-Accel-Buffering keeps
nginx from buffering it.
"""
import json
import logging
import time

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse, StreamingResponse

from core.auth.dependencies import require_permission
from core.auth.models import User
from core.http import get_client_ip
from . import capture

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/firewall/capture", tags=["Firewall"])


async def _panel_port() -> int:
    from core.settings.service import NetworkService
    from .defaults import UI_PORT
    try:
        port = await NetworkService()._get_current_port()
    except Exception:
        port = None
    return port if port and port != 80 else int(UI_PORT)


async def _prepare(spec: capture.CaptureSpec, request: Request) -> str:
    """The checked BPF expression for spec, or HTTP 400."""
    if spec.interface not in capture.list_interfaces():
        raise HTTPException(status_code=400, detail=f"Interfaccia non trovata: {spec.interface}")
    try:
        expr = capture.build_filter(spec, await _panel_port(), get_client_ip(request))
        await capture.validate_filter(spec.interface, expr)
    except capture.CaptureError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return expr


def _owned(capture_id: str, user: User) -> capture.CaptureSession:
    sess = capture.get_session(capture_id)
    if sess is None or (sess.owner_id != str(user.id) and not user.is_superuser):
        raise HTTPException(status_code=404, detail="Cattura non trovata")
    return sess


@router.get("/interfaces")
async def capture_interfaces(current_user: User = Depends(require_permission("firewall.manage"))):
    """Interfaces a capture can listen on (VPN tunnels included), "any" first."""
    return capture.list_interfaces()


@router.post("/validate")
async def validate_capture(
    spec: capture.CaptureSpec,
    request: Request,
    current_user: User = Depends(require_permission("firewall.manage")),
):
    """The filter the capture would use, checked by tcpdump; nothing captured."""
    return {"filter": await _prepare(spec, request)}


@router.post("/stream")
async def stream_capture(
    spec: capture.CaptureSpec,
    request: Request,
    current_user: User = Depends(require_permission("firewall.manage")),
):
    """
    Start a capture and stream it as NDJSON, one event per line: start, pkt
    (batches of tcpdump lines), stats, hb (heartbeat), end (reason: duration,
    count, size, stopped, replaced, client, shutdown, error; pcap: whether the
    file can be downloaded). Leaving the stream stops the capture.
    """
    expr = await _prepare(spec, request)
    try:
        sess = await capture.start(spec, expr, str(current_user.id), current_user.username)
    except capture.CaptureBusy as e:
        raise HTTPException(status_code=429, detail=str(e))
    except capture.CaptureError as e:
        raise HTTPException(status_code=400, detail=str(e))

    async def body():
        async for ev in capture.events(sess):
            yield json.dumps(ev, ensure_ascii=False) + "\n"

    return StreamingResponse(
        body(),
        media_type="application/x-ndjson",
        headers={"X-Accel-Buffering": "no", "Cache-Control": "no-cache"},
    )


@router.delete("/{capture_id}")
async def stop_capture(
    capture_id: str,
    current_user: User = Depends(require_permission("firewall.manage")),
):
    """Stop a running capture (its stream ends with reason "stopped")."""
    sess = _owned(capture_id, current_user)
    await capture.stop(sess, "stopped")
    return {"status": "ok"}


@router.get("/{capture_id}/pcap")
async def download_capture(
    capture_id: str,
    current_user: User = Depends(require_permission("firewall.manage")),
):
    """The pcap of an ended capture, for Wireshark (kept for capture.PCAP_TTL)."""
    sess = _owned(capture_id, current_user)
    if sess.running:
        raise HTTPException(status_code=409, detail="Cattura ancora in corso")
    if not sess.has_pcap():
        raise HTTPException(status_code=404, detail="Nessun pacchetto catturato")
    stamp = time.strftime("%Y%m%d-%H%M%S", time.localtime(sess.started_at))
    return FileResponse(
        sess.pcap_path,
        media_type="application/vnd.tcpdump.pcap",
        filename=f"capture-{sess.interface}-{stamp}.pcap",
    )
