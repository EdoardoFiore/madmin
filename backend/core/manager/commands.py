"""
Commands the manager may run on this instance.

Only what is registered here exists: there is no generic shell, and every
command validates its arguments with a Pydantic model that forbids unknown
fields. Each execution is written to the local audit log (and forwarded to
syslog) as user "manager:<operator>", method MANAGER, path manager://<command>, so a
local administrator can always see what the manager did.

Handlers are registered by the modules of this package (backups, support,
licenses) when imported; capabilities() is what the agent advertises in its
hello ({name: version}), and the manager offers only those. A command's
version is bumped when its arguments or its result change: the manager keeps
sending the older shape to agents that advertise an older version.

A failure is {"ok": false, "error": {"code", "message"}} with a code from
protocol.ERR_*: the manager acts on the code, the message is for the operator.
"""
import asyncio
import json
import logging
import re
import time
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Dict, Optional, Type

from pydantic import BaseModel, ConfigDict, ValidationError

from . import protocol

logger = logging.getLogger(__name__)

# Commands running at once; the rest wait (a burst from the manager cannot
# start dozens of exports or restores in parallel)
MAX_CONCURRENT = 4

_OPERATOR_RE = re.compile(r"[^A-Za-z0-9._@-]")


class CommandArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")


class NoArgs(CommandArgs):
    pass


class CommandError(Exception):
    """A failure whose message is meant for the manager operator; `code` is
    one of protocol.ERR_* (precondition: the instance is not in a state where
    the command makes sense, busy: a limit is reached)."""

    def __init__(self, message: str, code: str = protocol.ERR_FAILED):
        super().__init__(message)
        self.code = code


@dataclass
class CommandContext:
    cmd_id: str
    operator: str          # manager user that issued the command (sanitized)
    manager_host: str      # where the manager is, for the audit client_ip


Handler = Callable[[Any, CommandContext], Awaitable[Optional[dict]]]


@dataclass
class _Command:
    name: str
    version: int
    args: Type[CommandArgs]
    handler: Handler
    timeout: float
    audit: bool
    persist_result: bool


_registry: Dict[str, _Command] = {}
_semaphore: Optional[asyncio.Semaphore] = None


def command(name: str, args: Type[CommandArgs] = NoArgs, timeout: float = 60,
            audit: bool = True, persist_result: bool = False, version: int = 1):
    """persist_result: the result survives a restart of MADMIN (commands that
    restart it, or must never run twice for the same id). version: bumped when
    the arguments or the result change."""
    def register(fn: Handler) -> Handler:
        if name in _registry:
            raise RuntimeError(f"manager command {name} registered twice")
        _registry[name] = _Command(name, version, args, fn, timeout, audit, persist_result)
        return fn
    return register


def capabilities() -> Dict[str, int]:
    return {name: cmd.version for name, cmd in sorted(_registry.items())}


def persists_result(name) -> bool:
    cmd = _registry.get(name)
    return bool(cmd and cmd.persist_result)


def sanitize_operator(value) -> str:
    return _OPERATOR_RE.sub("", str(value or ""))[:60] or "unknown"


def _audit(ctx: CommandContext, name: str, ok: bool, duration_ms: int,
           args: dict, error: Optional[str]) -> None:
    try:
        from core.audit.middleware import _sanitize_dict
        from core.audit.models import AuditLog
        from core.audit.writer import audit_writer
        from core.audit.syslog import syslog_forwarder

        entry = AuditLog(
            username=f"manager:{ctx.operator}"[:100],
            method="MANAGER",
            path=f"manager://{name}"[:500],
            status_code=200 if ok else 500,
            duration_ms=duration_ms,
            client_ip=ctx.manager_host[:45],
            category="write",
            request_body=json.dumps(_sanitize_dict(args)) if args else None,
            response_summary=(error or None) and error[:500],
        )
        audit_writer.submit(entry)
        syslog_forwarder.submit(
            timestamp=entry.timestamp, username=entry.username, method="MANAGER",
            path=entry.path, status_code=entry.status_code, duration_ms=duration_ms,
            client_ip=entry.client_ip, category="write",
        )
    except Exception as e:
        logger.error("Manager command not audited: %s", e)


async def execute(cmd_id: str, payload: dict, manager_host: str) -> dict:
    """Run one cmd frame; returns the cmd_result payload (never raises)."""
    global _semaphore
    if _semaphore is None:
        _semaphore = asyncio.Semaphore(MAX_CONCURRENT)

    name = payload.get("name")
    raw_args = payload.get("args") or {}
    ctx = CommandContext(cmd_id, sanitize_operator(payload.get("operator")), manager_host)

    exp = payload.get("exp")
    if isinstance(exp, (int, float)) and exp < time.time():
        return protocol.error_result(protocol.ERR_EXPIRED, "comando scaduto")
    cmd = _registry.get(name)
    if cmd is None:
        return protocol.error_result(protocol.ERR_UNSUPPORTED, f"comando non supportato: {name!r}")
    if not isinstance(raw_args, dict):
        return protocol.error_result(protocol.ERR_INVALID_ARGS, "argomenti non validi")
    try:
        args = cmd.args(**raw_args)
    except ValidationError as e:
        return protocol.error_result(protocol.ERR_INVALID_ARGS,
                                     f"argomenti non validi: {e.errors(include_url=False)[:3]}")

    start = time.monotonic()
    error = None
    data = None
    async with _semaphore:
        try:
            data = await asyncio.wait_for(cmd.handler(args, ctx), timeout=cmd.timeout)
        except asyncio.TimeoutError:
            error = (protocol.ERR_TIMEOUT, f"timeout dopo {int(cmd.timeout)}s")
        except CommandError as e:
            error = (e.code, str(e))
        except Exception as e:
            logger.exception("Manager command %s failed", name)
            error = (protocol.ERR_INTERNAL, f"errore interno: {type(e).__name__}")
    duration_ms = int((time.monotonic() - start) * 1000)
    if cmd.audit:
        _audit(ctx, name, error is None, duration_ms, raw_args, error and error[1])
    if error is not None:
        return protocol.error_result(*error)
    return {"ok": True, "data": data or {}}


# --- Built-in commands ---

@command(protocol.CMD_PING, audit=False, timeout=10)
async def _ping(args: NoArgs, ctx: CommandContext) -> dict:
    return {"pong": int(time.time())}


@command(protocol.CMD_INVENTORY, audit=False, timeout=60)
async def _inventory(args: NoArgs, ctx: CommandContext) -> dict:
    from .inventory import collect_facts
    return {"facts": await collect_facts()}
