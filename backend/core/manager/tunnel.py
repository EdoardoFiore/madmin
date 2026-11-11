"""
Support tunnels: how the manager reaches the panel and SSH of an instance that
accepts no inbound connection.

For every TCP connection an operator makes to the manager's support port, the manager
sends tunnel.open {conn_id, target} on the control channel; the agent connects
to the local endpoint, then opens a dedicated WSS (same client certificate) to
<manager>/agent/tunnel/<conn_id> and copies bytes both ways as binary frames.
One WebSocket per TCP connection: TCP's own flow control applies end to end,
and a busy tunnel never delays the control channel.

Targets are names, mapped here: the manager cannot ask for any other host or
port. A target is served only while the matching support access is open
(an unexpired support account for "ui", an SSH grant for "ssh").
"""
import asyncio
import logging
from typing import Literal

from pydantic import Field
from websockets.asyncio.client import connect
from websockets.exceptions import ConnectionClosed

from . import protocol
from .commands import CommandArgs, CommandContext, CommandError, command

logger = logging.getLogger(__name__)

UI_ENDPOINT = ("127.0.0.1", 7443)   # nginx of this instance (setup-madmin.sh)
MAX_TUNNELS = 64
_READ_CHUNK = 64 * 1024
_tunnels: set = set()


class TunnelOpenArgs(CommandArgs):
    conn_id: str = Field(pattern=r"^[A-Za-z0-9_-]{16,64}$")
    target: Literal["ui", "ssh"]


async def _endpoint(target: str) -> tuple:
    from .support import ssh_grant_active, ui_session_active
    if target == "ui":
        if not await ui_session_active():
            raise CommandError("nessuna sessione di supporto UI attiva")
        return UI_ENDPOINT
    if not await asyncio.to_thread(ssh_grant_active):
        raise CommandError("nessun accesso SSH di supporto attivo")
    from core.system.ssh import ssh_ports
    ports = await ssh_ports()
    if not ports:
        raise CommandError("OpenSSH server non installato")
    return ("127.0.0.1", ports[0])


async def _pump(ws, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    async def tcp_to_ws():
        while data := await reader.read(_READ_CHUNK):
            await ws.send(data)

    async def ws_to_tcp():
        async for msg in ws:
            if isinstance(msg, str):
                return  # text frames are not part of a tunnel
            writer.write(msg)
            await writer.drain()

    tasks = [asyncio.create_task(tcp_to_ws()), asyncio.create_task(ws_to_tcp())]
    try:
        await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
    finally:
        for t in tasks:
            t.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)


async def _run_tunnel(ws, reader, writer, conn_id: str) -> None:
    try:
        await _pump(ws, reader, writer)
    except (ConnectionClosed, OSError):
        pass
    finally:
        writer.close()
        try:
            await ws.close()
        except Exception:
            pass
        _tunnels.discard(conn_id)


@command(protocol.CMD_TUNNEL_OPEN, TunnelOpenArgs, timeout=30, audit=False)
async def _tunnel_open(args: TunnelOpenArgs, ctx: CommandContext) -> dict:
    from core.concurrency import spawn_background
    from .client import manager_agent

    identity = manager_agent.identity
    if identity is None:
        raise CommandError("istanza non registrata")
    if len(_tunnels) >= MAX_TUNNELS:
        raise CommandError("troppi tunnel aperti")
    host, port = await _endpoint(args.target)
    try:
        reader, writer = await asyncio.wait_for(asyncio.open_connection(host, port), 10)
    except (OSError, asyncio.TimeoutError) as e:
        raise CommandError(f"endpoint locale {args.target} non raggiungibile: {e}")
    try:
        ssl_ctx = await asyncio.to_thread(identity.ssl_context)
        url = identity.ws_url.rsplit("/ws", 1)[0] + f"/tunnel/{args.conn_id}"
        ws = await connect(url, ssl=ssl_ctx, open_timeout=15, ping_interval=20,
                           ping_timeout=20, max_size=protocol.MAX_FRAME, compression=None)
    except Exception as e:
        writer.close()
        raise CommandError(f"tunnel verso il manager non aperto: {type(e).__name__}")
    _tunnels.add(args.conn_id)
    spawn_background(_run_tunnel(ws, reader, writer, args.conn_id), f"manager-tunnel-{args.conn_id[:8]}")
    return {}
