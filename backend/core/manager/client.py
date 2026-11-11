"""
Manager agent: the outbound control connection of this instance to its manager.

One background task (started from the lifespan) keeps a WSS connection with
mutual TLS to <manager>/agent/ws. Nothing listens on the instance: the manager reaches
it only through this connection, and through the per-connection tunnels the
agent opens on request (tunnel.py).

A session is three tasks (reader, writer, heartbeat); when any of them ends
the others are cancelled and the agent reconnects with an exponential backoff
(1 s to 60 s, jittered so a manager restart is not hit by every instance at once).
Close code 4401 means the manager revoked this instance: the agent removes the
support access the manager opened, stops and waits for a new enrollment instead
of retrying forever. 4403 (suspended) keeps everything and retries every
15 minutes; 4429 (manager busy) waits the seconds given in the close reason.
Any other close code is a lost connection: reconnect with backoff.

Commands are deduplicated by id and their results cached: the manager re-sends
the commands it has no result for after a reconnect, and gets the cached
result instead of a second execution.

Every hello carries the state the manager must not lose track of (open
support access, installed licenses, running and finished commands): events
are best effort, the manager reconciles with this state at each connection.

The manager tunes the agent through hello_ack.config (heartbeat and facts
intervals, longest backoff), each value clamped to protocol.CONFIG_LIMITS;
frames, fields and config keys this agent does not know are ignored.

Without an enrollment (DATA_DIR/manager/state.json) the task only watches that
file, so `python -m core.manager enroll` takes effect without a restart. With a
registration waiting for approval (pending.json) it polls the manager every
minute until the request is approved, rejected or expired.
"""
import asyncio
import json
import logging
import random
import time
from collections import OrderedDict
from datetime import datetime, timezone
from typing import Optional
from urllib.parse import urlsplit

from websockets.asyncio.client import connect
from websockets.exceptions import ConnectionClosed, InvalidStatus

from config import MADMIN_VERSION
from core.concurrency import spawn_background

from . import commands, identity as ident, protocol
from .identity import ManagerIdentity, ManagerIdentityError
from .inventory import collect_facts, collect_stats, facts_digest

logger = logging.getLogger("madmin.manager")

RENEW_CHECK_INTERVAL = 6 * 3600
STATE_POLL_INTERVAL = 30
_RESULT_CACHE = 500
_PERSISTED_RESULTS = 50
_HANDSHAKE_TIMEOUT = 15

# Abilities of this agent that are not commands (hello.features)
FEATURES: list = []


class _Revoked(Exception):
    pass


class _Wait(Exception):
    """The manager asked to come back later (suspended, busy)."""

    def __init__(self, seconds: float, why: str):
        super().__init__(why)
        self.seconds = seconds


def _check_close(code, reason) -> None:
    """Raise what a close code from the manager means for the main loop."""
    if code == protocol.CLOSE_REVOKED:
        raise _Revoked()
    if code == protocol.CLOSE_SUSPENDED:
        raise _Wait(protocol.SUSPENDED_RETRY, "istanza sospesa dal manager")
    if code == protocol.CLOSE_TRY_LATER:
        raise _Wait(protocol.try_later_delay(reason), "manager occupato")


class ManagerAgent:
    def __init__(self) -> None:
        self.identity: Optional[ManagerIdentity] = None
        self.connected = False
        self._outbox: Optional[asyncio.Queue] = None
        self._results: "OrderedDict[str, dict]" = OrderedDict()
        self._running: set = set()
        self._state_mtime: tuple = ()
        self._last_renew_check = 0.0
        self._facts_digest: Optional[str] = None
        # Set by the manager in hello_ack (kept across sessions, reset by a restart)
        self.config = {key: default for key, (_, _, default) in protocol.CONFIG_LIMITS.items()}
        self.revision = 0
        self.manager_features: set = set()
        # Trusted CAs as last reported (hello.state.ca, then ca.updated)
        self._reported_ca: Optional[list] = None
        # Updater journal as last reported (hello.state.update, then update.status)
        self._reported_update: Optional[dict] = None

    # --- Status file (read by `python -m core.manager status`) ---

    def _write_status(self, error: Optional[str] = None) -> None:
        try:
            ident.write_private("status.json", json.dumps({
                "connected": self.connected,
                "at": datetime.now(timezone.utc).isoformat(),
                "error": error,
            }).encode())
        except OSError:
            pass

    # --- Main loop ---

    async def run(self) -> None:
        await asyncio.to_thread(self._load_persisted_results)
        backoff = 1.0
        failing = False
        while True:
            try:
                self._state_mtime = await asyncio.to_thread(ident.state_mtime)
                identity = await asyncio.to_thread(ident.load_identity)
            except ManagerIdentityError as e:
                logger.error("Manager identity unreadable: %s", e)
                identity = None
            if identity is None or identity.revoked:
                self.identity = None
                interval = await self._poll_pending()
                if interval == 0:
                    continue  # approved: identity saved, connect now
                await self._wait_state_change(timeout=interval)
                continue
            self.identity = identity

            await self._maybe_renew(identity)
            started = time.monotonic()
            error = None
            try:
                await self._session(identity)
            except asyncio.CancelledError:
                raise
            except _Revoked:
                logger.error(
                    "Manager: this instance was revoked by the manager. The agent stays stopped "
                    "until a new enrollment (python -m core.manager enroll)."
                )
                await asyncio.to_thread(ident.mark_revoked)
                await asyncio.to_thread(self._write_status, "revocata dal manager")
                # Support access opened by the manager goes now, not at its expiry:
                # hidden accounts, SSH grant and the sshd CA/drop-in (a new
                # enrollment installs them again at the next grant)
                try:
                    from .support import cleanup_all
                    await cleanup_all()
                    logger.info("Manager: support access removed after the revocation")
                except Exception:
                    logger.exception("Manager: support access not removed after the revocation")
                continue
            except _Wait as w:
                logger.warning("Manager: %s, next attempt in %ds", w, int(w.seconds))
                await asyncio.to_thread(self._write_status, str(w))
                backoff = 1.0
                failing = False
                await self._wait_state_change(timeout=w.seconds)
                continue
            except InvalidStatus as e:
                error = f"handshake rifiutato (HTTP {e.response.status_code})"
            except (OSError, ConnectionClosed, asyncio.TimeoutError, protocol.ProtocolError,
                    ManagerIdentityError) as e:
                error = f"{type(e).__name__}: {e}"
            except Exception as e:
                logger.exception("Manager agent session error")
                error = f"{type(e).__name__}: {e}"

            if time.monotonic() - started > 60:
                # The session was up: a new streak of failures starts here
                backoff = 1.0
                failing = False
            if error:
                # The first failure of a streak is a warning, the retries are debug
                (logger.debug if failing else logger.warning)("Manager: connection lost/failed: %s", error)
                failing = True
                await asyncio.to_thread(self._write_status, error)
            delay = backoff * random.uniform(0.5, 1.0)
            backoff = min(self.config["backoff_max"], backoff * 2)
            await self._wait_state_change(timeout=delay)

    async def _poll_pending(self) -> Optional[float]:
        """
        A registration waiting for approval: check it. Returns 0 once
        approved, the seconds to the next check while pending, None when there
        is nothing to wait for (only a CLI change wakes the agent then).
        """
        pending = await asyncio.to_thread(ident.load_pending)
        if not pending or pending.get("status") != "pending":
            return None
        from .enroll import poll_registration
        try:
            status = await poll_registration()
        except Exception as e:
            logger.debug("Manager: registration check failed: %s", e)
            return self.config["backoff_max"]
        if status == "approved":
            logger.info("Manager: registration approved, connecting")
            return 0
        if status in ("rejected", "expired"):
            logger.error("Manager: registration %s by the manager. Register again with "
                         "python -m core.manager register --url ...", status)
            await asyncio.to_thread(self._write_status, f"registrazione {status}")
            return None
        return max(30, int(pending.get("poll_interval") or 60))

    async def _wait_state_change(self, timeout: Optional[float] = None) -> None:
        """Sleep `timeout` seconds (forever if None), returning early when the
        enrollment state file changes."""
        deadline = None if timeout is None else time.monotonic() + timeout
        while True:
            step = STATE_POLL_INTERVAL if deadline is None else min(STATE_POLL_INTERVAL, deadline - time.monotonic())
            if step <= 0:
                return
            await asyncio.sleep(step)
            if await asyncio.to_thread(ident.state_mtime) != self._state_mtime:
                return

    async def _maybe_renew(self, identity: ManagerIdentity) -> None:
        if time.monotonic() - self._last_renew_check < RENEW_CHECK_INTERVAL and self._last_renew_check:
            return
        self._last_renew_check = time.monotonic()
        from .enroll import renew, renewal_due
        try:
            if await asyncio.to_thread(identity.cert_expired):
                logger.error("Manager: client certificate expired, a new enrollment is required")
                return
            if await asyncio.to_thread(renewal_due, identity):
                await renew(identity)
        except Exception as e:
            logger.warning("Manager: certificate renewal failed (retried later): %s", e)
            self._last_renew_check = time.monotonic() - RENEW_CHECK_INTERVAL + 600

    # --- Session ---

    def _end_move(self, identity: ManagerIdentity, url: str, ok: bool) -> None:
        """manager.relocate: keep the address that answered, or drop it."""
        if ok:
            identity.manager_url = url
            logger.info("Manager: now connected through %s", url)
        else:
            logger.error("Manager: %s did not answer, staying on %s", url, identity.manager_url)
        identity.manager_url_next = ""
        ident.save_state(identity)
        # Our own change: not a reason to end the session
        self._state_mtime = ident.state_mtime()

    async def _session(self, identity: ManagerIdentity) -> None:
        ssl_ctx = await asyncio.to_thread(identity.ssl_context)
        # A move being tried (manager.relocate) is one attempt: kept after a
        # hello_ack from there, dropped on any failure before it
        trying = identity.manager_url_next
        settled = not trying
        try:
            async with connect(
                identity.ws_url_of(trying or identity.manager_url),
                ssl=ssl_ctx,
                open_timeout=_HANDSHAKE_TIMEOUT,
                ping_interval=20,
                ping_timeout=20,
                close_timeout=5,
                max_size=protocol.MAX_FRAME,
                user_agent_header=f"madmin-agent/{MADMIN_VERSION}",
            ) as ws:
                await self._handshake(ws, identity)
                if not settled:
                    await asyncio.to_thread(self._end_move, identity, trying, True)
                    settled = True
                await self._serve(ws, identity)
        except ConnectionClosed as e:
            if e.rcvd is not None:
                _check_close(e.rcvd.code, e.rcvd.reason)
            raise
        finally:
            if not settled:
                await asyncio.to_thread(self._end_move, identity, trying, False)

    async def _state(self) -> dict:
        """hello.state: what the manager reconciles at each connection."""
        state: dict = {"commands": {"running": sorted(self._running), "finished": list(self._results)}}
        try:
            state["ca"] = await asyncio.to_thread(ident.trusted_ca_fingerprints)
            self._reported_ca = state["ca"]
        except Exception as e:
            logger.warning("Manager: trusted CAs not readable: %s", e)
        try:
            from .support import support_state
            state["support"] = await support_state()
        except Exception as e:
            logger.warning("Manager: support state not readable: %s", e)
        try:
            from .licenses import license_ids
            state["licenses"] = await asyncio.to_thread(license_ids)
        except Exception as e:
            logger.warning("Manager: licenses not readable: %s", e)
        from .update import update_state
        update = await asyncio.to_thread(update_state)
        if update is not None:
            state["update"] = update
        self._reported_update = update
        return state

    async def _report_update(self) -> None:
        """update.status when the updater's journal changed since the last
        report (the update was confirmed and committed, or rolled back)."""
        from .update import update_state
        current = await asyncio.to_thread(update_state)
        if current is not None and current != self._reported_update:
            if self.send_event(protocol.EVENT_UPDATE_STATUS, current):
                self._reported_update = current

    async def _report_ca(self) -> None:
        """ca.updated when the trusted CAs changed since the last report (a
        bundle accepted after the hello, or at a certificate renewal)."""
        try:
            current = await asyncio.to_thread(ident.trusted_ca_fingerprints)
        except Exception:
            return
        if self._reported_ca is not None and current != self._reported_ca:
            if self.send_event(protocol.EVENT_CA_UPDATED, {"ca": current}):
                self._reported_ca = current

    async def _handshake(self, ws, identity: ManagerIdentity) -> None:
        facts = await collect_facts()
        await ws.send(protocol.frame(protocol.HELLO, {
            "protocol": protocol.PROTOCOL_VERSION,
            "revision_min": protocol.PROTOCOL_REVISION_MIN,
            "revision_max": protocol.PROTOCOL_REVISION,
            "instance_id": identity.instance_id,
            "capabilities": commands.capabilities(),
            "features": FEATURES,
            "facts": facts,
            "state": await self._state(),
        }))
        msg = protocol.parse(await asyncio.wait_for(ws.recv(), _HANDSHAKE_TIMEOUT))
        if msg["type"] != protocol.HELLO_ACK:
            raise protocol.ProtocolError(f"expected hello_ack, got {msg['type']}")
        ack = msg["payload"]
        revision = ack.get("revision")
        if not isinstance(revision, int) or not (
                protocol.PROTOCOL_REVISION_MIN <= revision <= protocol.PROTOCOL_REVISION):
            raise protocol.ProtocolError(f"revision {revision!r} chosen by the manager not spoken here")
        self.revision = revision
        features = ack.get("features")
        self.manager_features = {str(f)[:50] for f in features[:200]} if isinstance(features, list) else set()
        self.config.update(protocol.clamp_config(ack.get("config")))
        if isinstance(ack.get("update_confirm"), str):
            from .update import confirm
            if await asyncio.to_thread(confirm, ack["update_confirm"]):
                logger.info("Manager: update to %s confirmed", ack["update_confirm"])
        if ack.get("ca_bundle"):
            try:
                added = await asyncio.to_thread(ident.accept_ca_bundle, str(ack["ca_bundle"]).encode())
                if added:
                    logger.info("Manager: new CA trusted (%s)", ", ".join(fp[:16] for fp in added))
            except ManagerIdentityError as e:
                logger.warning("Manager: CA bundle refused: %s", e)
        self._facts_digest = facts_digest(facts)

    async def _serve(self, ws, identity: ManagerIdentity) -> None:
        outbox: asyncio.Queue = asyncio.Queue(maxsize=1000)
        self._outbox = outbox
        self.connected = True
        await asyncio.to_thread(self._write_status)
        logger.info("Manager: connected to %s as %s", identity.manager_url, identity.instance_id)
        await self._report_ca()
        manager_host = urlsplit(identity.manager_url).hostname or ""
        tasks = [
            asyncio.create_task(self._reader(ws, manager_host), name="manager-reader"),
            asyncio.create_task(self._writer(ws, outbox), name="manager-writer"),
            asyncio.create_task(self._heartbeat(outbox, identity), name="manager-heartbeat"),
        ]
        try:
            done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            for t in done:
                t.result()  # re-raise what ended the session
        finally:
            self.connected = False
            self._outbox = None
            for t in tasks:
                t.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            await asyncio.to_thread(self._write_status)
        _check_close(ws.close_code, ws.close_reason)

    async def _reader(self, ws, manager_host: str) -> None:
        async for raw in ws:
            try:
                msg = protocol.parse(raw)
            except protocol.ProtocolError as e:
                await ws.close(protocol.CLOSE_PROTOCOL, str(e)[:100])
                raise
            if msg["type"] == protocol.CMD:
                self._dispatch(msg["id"], msg["payload"], manager_host)
            else:
                # Unknown types are ignored: a newer manager may send frames
                # this agent does not know
                logger.debug("Manager: ignored frame %s", msg["type"])

    async def _writer(self, ws, outbox: asyncio.Queue) -> None:
        while True:
            await ws.send(await outbox.get())

    async def _heartbeat(self, outbox: asyncio.Queue, identity: ManagerIdentity) -> None:
        last_facts = time.monotonic()
        while True:
            await asyncio.sleep(self.config["heartbeat_interval"])
            payload = {"stats": await collect_stats()}
            if time.monotonic() - last_facts >= self.config["facts_interval"]:
                last_facts = time.monotonic()
                facts = await collect_facts()
                digest = facts_digest(facts)
                if digest != self._facts_digest:
                    self._facts_digest = digest
                    payload["facts"] = facts
            self._send(protocol.frame(protocol.HEARTBEAT, payload))
            # Unenrolled / re-enrolled from the CLI: end this session
            if await asyncio.to_thread(ident.state_mtime) != self._state_mtime:
                return
            await self._maybe_renew(identity)
            await self._report_ca()
            await self._report_update()

    # --- Commands ---

    def _load_persisted_results(self) -> None:
        raw = ident.read_file("results.json")
        if not raw:
            return
        try:
            for cmd_id, result in json.loads(raw):
                self._results[cmd_id] = result
        except (ValueError, TypeError):
            pass

    def _persist_result(self, cmd_id: str, result: dict) -> None:
        raw = ident.read_file("results.json")
        try:
            kept = json.loads(raw) if raw else []
        except ValueError:
            kept = []
        kept = [e for e in kept if e[0] != cmd_id][-(_PERSISTED_RESULTS - 1):] + [[cmd_id, result]]
        ident.write_private("results.json", json.dumps(kept).encode())

    def _send(self, text: str) -> bool:
        outbox = self._outbox
        if outbox is None:
            return False
        try:
            outbox.put_nowait(text)
            return True
        except asyncio.QueueFull:
            logger.warning("Manager: outbox full, frame dropped")
            return False

    def send_event(self, name: str, data: Optional[dict] = None) -> bool:
        return self._send(protocol.frame(protocol.EVENT, {"name": name, "data": data or {}}))

    def _dispatch(self, cmd_id: str, payload: dict, manager_host: str) -> None:
        if cmd_id in self._results:
            self._send(protocol.frame(protocol.CMD_RESULT, self._results[cmd_id], cmd_id))
            return
        if cmd_id in self._running:
            # Re-sent while still running (a reconnect): the result follows
            self._send(protocol.frame(protocol.CMD_PROGRESS, {"state": "running"}, cmd_id))
            return
        self._running.add(cmd_id)
        spawn_background(self._run_command(cmd_id, payload, manager_host), f"manager-cmd-{cmd_id[:8]}")

    async def _run_command(self, cmd_id: str, payload: dict, manager_host: str) -> None:
        try:
            result = await commands.execute(
                cmd_id, payload, manager_host,
                progress=lambda data: self._send(protocol.frame(protocol.CMD_PROGRESS, data, cmd_id)))
        finally:
            self._running.discard(cmd_id)
        self._results[cmd_id] = result
        while len(self._results) > _RESULT_CACHE:
            self._results.popitem(last=False)
        if commands.persists_result(payload.get("name")):
            await asyncio.to_thread(self._persist_result, cmd_id, result)
        # Sent on the current session; if there is none, the manager re-sends the
        # command after the reconnect and gets the cached result
        self._send(protocol.frame(protocol.CMD_RESULT, result, cmd_id))


manager_agent = ManagerAgent()


def load_command_handlers() -> None:
    """Register the commands implemented by the other modules of the package."""
    from . import backups, licenses, relocate, stats, support, tunnel, update  # noqa: F401
