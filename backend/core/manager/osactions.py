"""
OS actions (ROADMAP 9.1): os.refresh, os.upgrade, os.reboot, os.reboot.cancel.

The manager names a category, never a package or a command line. The work
is done by the updater (/opt/madmin/updater/madmin-update, standard library
only), the upgrade in a transient systemd unit: a package upgrade may
restart MADMIN (needrestart), and must not die with it. The command follows
the unit through its job file (state/os-<command id>.json); a command
re-sent after MADMIN restarted attaches to the job already running instead
of starting a second one.

A reboot with a newer kernel installed boots it once on trial; the running
kernel stays the default until the manager confirms the new one
(hello_ack.kernel_confirm, after the reconnection). Not confirmed within
15 minutes of the boot, madmin-boot-check.timer reboots into the previous
kernel. The trial is reported in hello.state.kernel.
"""
import asyncio
import json
import logging
import os
from typing import Optional

from pydantic import Field

from config import INSTALL_ROOT, build_info

from . import protocol
from .commands import CommandArgs, CommandContext, CommandError, command

logger = logging.getLogger(__name__)

STATE_DIR = os.path.join(INSTALL_ROOT, "state")
UPDATER = os.path.join(INSTALL_ROOT, "updater", "madmin-update")
KERNEL_TRIAL = os.path.join(STATE_DIR, "kernel-trial.json")
JOB_POLL = 3
UPGRADE_TIMEOUT = 5400


def _read_json(path: str):
    try:
        with open(path) as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def kernel_state() -> Optional[dict]:
    """The kernel trial, as reported to the manager (None: never one)."""
    t = _read_json(KERNEL_TRIAL)
    if not t:
        return None
    return {k: t.get(k) for k in ("kernel", "previous", "result", "detail", "started_at", "confirmed_at",
                                  "failed_at", "reason")}


async def _run(*cmd: str, timeout: float = 120) -> tuple:
    proc = await asyncio.create_subprocess_exec(*cmd, stdout=asyncio.subprocess.PIPE,
                                                stderr=asyncio.subprocess.STDOUT,
                                                env={**os.environ, "LC_ALL": "C"})
    try:
        out, _ = await asyncio.wait_for(proc.communicate(), timeout)
    except asyncio.TimeoutError:
        proc.kill()
        raise CommandError(f"{cmd[0]} non terminato entro {int(timeout)}s", protocol.ERR_TIMEOUT)
    return proc.returncode, out.decode(errors="replace").strip()


async def kernel_confirm(kernel: str) -> bool:
    """hello_ack.kernel_confirm: the trial kernel came up and reconnected."""
    st = kernel_state() or {}
    if st.get("result") != "pending" or st.get("kernel") != kernel or os.uname().release != kernel:
        return False
    code, out = await _run("/usr/bin/python3", UPDATER, "kernel-confirm", f"--kernel={kernel}")
    if code != 0:
        logger.warning("Manager: kernel %s not confirmed: %s", kernel, out[-300:])
        return False
    return True


def _require_updater() -> None:
    if build_info()["layout"] < 1 or not os.path.exists(UPDATER):
        raise CommandError("installazione senza updater (layout precedente): reinstallare l'istanza",
                           protocol.ERR_PRECONDITION)


def _busy() -> Optional[str]:
    """Why an OS action cannot start now (an update, a restore), or None."""
    from .update import update_state
    if (update_state() or {}).get("result") in ("running", "verifying"):
        return "aggiornamento di MADMIN in corso"
    from core.concurrency import is_locked
    if is_locked("manager-backup"):
        return "backup o ripristino in corso"
    return None


def _prune(patterns: tuple, days: int = 30) -> None:
    """Job files and markers of old commands (the manager re-sends a command
    for a day at most)."""
    import glob
    import time
    limit = time.time() - days * 86400
    for pattern in patterns:
        for path in glob.glob(os.path.join(STATE_DIR, pattern)):
            try:
                if os.path.getmtime(path) < limit:
                    os.unlink(path)
            except OSError:
                pass


# --- os.refresh ---

@command(protocol.CMD_OS_REFRESH, timeout=900, progress=True)
async def _os_refresh(args: CommandArgs, ctx: CommandContext) -> dict:
    ctx.report("apt-update")
    code, out = await _run("apt-get", "-o", "DPkg::Lock::Timeout=300", "-q", "update", timeout=900)
    if code != 0:
        raise CommandError(f"apt-get update fallito: {out[-500:]}")
    from .inventory import os_status
    from .client import manager_agent
    manager_agent.facts_changed()
    return {"os_status": await asyncio.to_thread(os_status)}


# --- os.upgrade ---

class UpgradeArgs(CommandArgs):
    scope: str = Field(pattern="^(security|all)$")


@command(protocol.CMD_OS_UPGRADE, UpgradeArgs, timeout=UPGRADE_TIMEOUT, persist_result=True, progress=True)
async def _os_upgrade(args: UpgradeArgs, ctx: CommandContext) -> dict:
    _require_updater()
    job_path = os.path.join(STATE_DIR, f"os-{ctx.cmd_id}.json")
    job = _read_json(job_path)
    if job is None:
        reason = _busy()
        if reason:
            raise CommandError(reason, protocol.ERR_BUSY)
        os.makedirs(STATE_DIR, mode=0o700, exist_ok=True)
        unit = f"madmin-os-{ctx.cmd_id[:8]}"
        code, out = await _run("systemd-run", f"--unit={unit}", "--collect", "--description=MADMIN OS upgrade",
                               "/usr/bin/python3", UPDATER, "os-upgrade", f"--scope={args.scope}",
                               f"--job={job_path}")
        if code != 0:
            raise CommandError(f"upgrade non avviato: {out[-300:]}")
    # Follows the job (also after a restart of MADMIN in the middle)
    last_step = None
    loop = asyncio.get_running_loop()
    started = loop.time()
    while True:
        job = _read_json(job_path) or {}
        if job.get("state") in ("done", "failed"):
            break
        if job.get("step") != last_step:
            last_step = job.get("step")
            ctx.report(last_step or "start")
        if loop.time() - started > UPGRADE_TIMEOUT:
            raise CommandError("upgrade ancora in corso dopo il tempo massimo", protocol.ERR_TIMEOUT)
        await asyncio.sleep(JOB_POLL)
    from .client import manager_agent
    manager_agent.facts_changed()
    if job["state"] == "failed":
        raise CommandError(f"upgrade fallito: {job.get('detail', '')}"[:900],
                           protocol.ERR_BUSY if job.get("code") == "busy" else protocol.ERR_FAILED)
    return {k: job.get(k) for k in ("scope", "changed", "changes", "new_kernels", "reboot_required",
                                    "reboot_packages", "started_at", "finished_at")}


# --- os.reboot ---

class RebootArgs(CommandArgs):
    delay_minutes: int = Field(default=0, ge=0, le=protocol.REBOOT_DELAY_MAX)
    reason: str = Field(min_length=3, max_length=200)


@command(protocol.CMD_OS_REBOOT, RebootArgs, timeout=120, persist_result=True)
async def _os_reboot(args: RebootArgs, ctx: CommandContext) -> dict:
    _require_updater()
    # The reboot may come before the result is stored and sent: the command
    # re-sent after the boot must find it done, never reboot a second time
    marker = os.path.join(STATE_DIR, f"reboot-{ctx.cmd_id}.json")
    done = _read_json(marker)
    if done is not None:
        return {**done, "kernel": os.uname().release, "rebooted": True}
    os.makedirs(STATE_DIR, mode=0o700, exist_ok=True)
    _prune(("reboot-*.json", "os-*.json", "os-*.log"))
    with open(marker, "w") as f:
        json.dump({"delay_minutes": args.delay_minutes, "at": None, "kernel_trial": None}, f)
    reason = _busy()
    if reason:
        raise CommandError(reason, protocol.ERR_PRECONDITION)
    # One printable line: it ends up in the wall message
    text = " ".join(f"{args.reason} ({ctx.operator})".split())
    code, out = await _run("/usr/bin/python3", UPDATER, "reboot", f"--delay={args.delay_minutes}",
                           f"--reason={text}")
    if code != 0:
        os.unlink(marker)
        busy = "another update is running" in out
        raise CommandError(f"riavvio rifiutato: {out[-500:]}", protocol.ERR_BUSY if busy else protocol.ERR_PRECONDITION)
    try:
        data = json.loads(out.strip().splitlines()[-1])
    except (ValueError, IndexError):
        data = {}
    result = {"delay_minutes": args.delay_minutes, "at": data.get("at"), "kernel_trial": data.get("kernel_trial")}
    with open(marker, "w") as f:
        json.dump(result, f)
    return {**result, "kernel": os.uname().release}


@command(protocol.CMD_OS_REBOOT_CANCEL, timeout=60)
async def _os_reboot_cancel(args: CommandArgs, ctx: CommandContext) -> dict:
    _require_updater()
    code, out = await _run("/usr/bin/python3", UPDATER, "reboot-cancel")
    if code != 0:
        raise CommandError(f"annullamento fallito: {out[-300:]}")
    return {"cancelled": True}
