"""
madmin.update: install a signed release the manager holds.

The manager names a release and its sha256, never a URL: the agent
downloads it from /agent/releases/<id> of its own manager (mutual TLS),
checks the hash and the signature (madmin-update verify, the check the
updater repeats), then starts `madmin-update install` in a transient
systemd unit, which outlives the restart of MADMIN. The command's result
only says the update started; its outcome is the updater's journal,
reported in hello.state.update and, when it changes, in update.status.

The updater's health gate waits for the manager: after the restart the
hello carries state.update {result: "verifying"}, the manager answers with
hello_ack.update_confirm = <release id>, and the agent writes it to
state/update-confirm. A release that starts but cannot reach the manager
is rolled back.
"""
import asyncio
import hashlib
import json
import os
from typing import Optional
from urllib.parse import quote

import httpx
from pydantic import Field

from config import INSTALL_ROOT, build_info

from . import protocol
from .commands import CommandArgs, CommandContext, CommandError, command

STATE_DIR = os.path.join(INSTALL_ROOT, "state")
JOURNAL = os.path.join(STATE_DIR, "update.json")
CONFIRM = os.path.join(STATE_DIR, "update-confirm")
DOWNLOADS = os.path.join(STATE_DIR, "downloads")
UPDATER = os.path.join(INSTALL_ROOT, "updater", "madmin-update")
_STATE_KEYS = ("update_id", "release_id", "from_release", "step", "result", "detail", "updated_at")


def update_state() -> Optional[dict]:
    """The updater's journal, as reported to the manager (None: no update yet)."""
    try:
        with open(JOURNAL) as f:
            j = json.load(f)
    except (OSError, ValueError):
        return None
    state = {k: j.get(k) for k in _STATE_KEYS}
    if j.get("result") in ("rolled_back", "failed") and j.get("log_tail"):
        state["log_tail"] = str(j["log_tail"])[-3000:]
    return state


def confirm(release_id: str) -> bool:
    """hello_ack.update_confirm: lets the updater's health gate pass when it
    is the release being verified."""
    state = update_state() or {}
    if state.get("result") != "verifying" or state.get("release_id") != release_id:
        return False
    tmp = CONFIRM + ".tmp"
    with open(tmp, "w") as f:
        f.write(release_id)
    os.replace(tmp, CONFIRM)
    return True


class UpdateArgs(CommandArgs):
    release_id: str = Field(pattern=r"^[0-9A-Za-z.+_-]{1,80}$")
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    # Health gate of the updater (seconds)
    deadline: Optional[int] = Field(default=None, ge=60, le=3600)


def _download(identity, release_id: str, sha256: str, dest: str, report) -> None:
    os.makedirs(DOWNLOADS, mode=0o700, exist_ok=True)
    part = dest + ".part"
    h = hashlib.sha256()
    with httpx.Client(verify=identity.ssl_context(), timeout=httpx.Timeout(60, read=300)) as client:
        with client.stream("GET", f"{identity.manager_url}/agent/releases/{quote(release_id, safe='')}") as r:
            if r.status_code != 200:
                raise CommandError(f"download rifiutato dal manager (HTTP {r.status_code})")
            total = int(r.headers.get("content-length") or 0)
            done, last = 0, -1
            fd = os.open(part, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(fd, "wb") as f:
                for chunk in r.iter_bytes(1 << 20):
                    f.write(chunk)
                    h.update(chunk)
                    done += len(chunk)
                    pct = done * 100 // total if total else None
                    if pct is not None and pct // 10 != last:
                        last = pct // 10
                        report(pct)
    if h.hexdigest() != sha256:
        os.unlink(part)
        raise CommandError("file scaricato diverso da quello annunciato dal manager (sha256)")
    os.replace(part, dest)


async def _run(*cmd: str) -> tuple:
    proc = await asyncio.create_subprocess_exec(*cmd, stdout=asyncio.subprocess.PIPE,
                                                stderr=asyncio.subprocess.STDOUT)
    out, _ = await proc.communicate()
    return proc.returncode, out.decode(errors="replace").strip()


# Persistent result: MADMIN restarts during the update, and the command
# re-sent after it must not start a second one
@command(protocol.CMD_UPDATE, UpdateArgs, timeout=1800, persist_result=True, progress=True)
async def _update(args: UpdateArgs, ctx: CommandContext) -> dict:
    from .client import manager_agent
    identity = manager_agent.identity
    if identity is None:
        raise CommandError("istanza non registrata", protocol.ERR_PRECONDITION)
    if build_info()["layout"] < 1 or not os.path.exists(UPDATER):
        raise CommandError("installazione senza updater (layout precedente): reinstallare l'istanza",
                           protocol.ERR_PRECONDITION)
    if (update_state() or {}).get("result") in ("running", "verifying"):
        raise CommandError("un aggiornamento è già in corso", protocol.ERR_BUSY)
    if build_info()["release_id"] == args.release_id:
        raise CommandError("questa release è già installata", protocol.ERR_PRECONDITION)

    dest = os.path.join(DOWNLOADS, f"{args.release_id}.release")
    ctx.report("download", 0)
    await asyncio.to_thread(_download, identity, args.release_id, args.sha256, dest,
                            lambda pct: ctx.report("download", pct))
    ctx.report("verify")
    code, out = await _run("/usr/bin/python3", UPDATER, "verify", dest)
    if code != 0:
        os.unlink(dest)
        raise CommandError(f"release rifiutata: {out[-500:]}")

    unit = f"madmin-update-{ctx.cmd_id[:8]}"
    cmd = ["systemd-run", f"--unit={unit}", "--collect", "--description=MADMIN update",
           "/usr/bin/python3", UPDATER, "install", dest, f"--command-id={ctx.cmd_id}"]
    if args.deadline:
        cmd.append(f"--deadline={args.deadline}")
    code, out = await _run(*cmd)
    if code != 0:
        raise CommandError(f"updater non avviato: {out[-300:]}")
    ctx.report("started", message=unit)
    return {"release_id": args.release_id, "unit": unit, "started": True}
