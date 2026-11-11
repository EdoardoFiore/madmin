"""
Configuration backups kept by the manager.

The archive goes only to the manager this instance is enrolled with, over the
same mutual-TLS identity as the control channel: the manager cannot name another
destination. It is encrypted with the per-instance passphrase agreed at
enrollment (archive_crypto), so the manager can restore it on a reinstalled
instance as well.

A restore downloads the archive from the manager (which serves only this
instance's backups) and runs the normal import_config, restart included.
"""
import asyncio
import hashlib
import os
import uuid

import httpx
from pydantic import Field

from core.concurrency import resource_lock

from . import protocol
from .commands import CommandArgs, CommandContext, CommandError, NoArgs, command

_TIMEOUT = httpx.Timeout(600.0, connect=15.0)
_CHUNK = 1024 * 1024


def _identity():
    from .client import manager_agent
    identity = manager_agent.identity
    if identity is None:
        raise CommandError("istanza non registrata", protocol.ERR_PRECONDITION)
    if not identity.backup_passphrase:
        raise CommandError("passphrase di backup assente: ripetere l'enrollment", protocol.ERR_PRECONDITION)
    return identity


def _sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(_CHUNK), b""):
            h.update(chunk)
    return h.hexdigest()


def _upload(identity, path: str, digest: str, cmd_id: str) -> dict:
    with httpx.Client(verify=identity.ssl_context(), timeout=_TIMEOUT) as client, open(path, "rb") as f:
        r = client.post(
            f"{identity.manager_url}/agent/backups",
            content=f,
            headers={
                "Content-Type": "application/octet-stream",
                "X-Content-SHA256": digest,
                "X-Command-Id": cmd_id,
                "X-Archive-Name": os.path.basename(path),
            },
        )
    if r.status_code != 200:
        raise CommandError(f"upload rifiutato dal manager (HTTP {r.status_code})")
    return r.json()


def _download(identity, backup_id: str, dest: str) -> None:
    h = hashlib.sha256()
    with httpx.Client(verify=identity.ssl_context(), timeout=_TIMEOUT) as client:
        with client.stream("GET", f"{identity.manager_url}/agent/backups/{backup_id}") as r:
            if r.status_code != 200:
                raise CommandError(f"download rifiutato dal manager (HTTP {r.status_code})")
            expected = r.headers.get("X-Content-SHA256", "")
            fd = os.open(dest, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "wb") as f:
                for chunk in r.iter_bytes(_CHUNK):
                    h.update(chunk)
                    f.write(chunk)
    if not expected or h.hexdigest() != expected:
        raise CommandError("archivio scaricato corrotto (sha256 non corrispondente)")


@command(protocol.CMD_BACKUP_RUN, NoArgs, timeout=1800)
async def _backup_run(args: NoArgs, ctx: CommandContext) -> dict:
    from core.backup.service import export_config
    from core.database import async_session_maker

    identity = _identity()
    async with resource_lock("manager-backup"):
        async with async_session_maker() as session:
            path = await export_config(session, passphrase=identity.backup_passphrase)
        try:
            digest = await asyncio.to_thread(_sha256, path)
            size = os.path.getsize(path)
            stored = await asyncio.to_thread(_upload, identity, path, digest, ctx.cmd_id)
        finally:
            try:
                os.remove(path)
            except OSError:
                pass
    return {"backup_id": stored.get("backup_id"), "size": size, "sha256": digest}


class RestoreArgs(CommandArgs):
    backup_id: str = Field(pattern=r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")


# Persistent result: a restore ends with a restart of MADMIN, and a command
# re-sent after it must not restore twice (see client.py)
@command(protocol.CMD_BACKUP_RESTORE, RestoreArgs, timeout=1800, persist_result=True)
async def _backup_restore(args: RestoreArgs, ctx: CommandContext) -> dict:
    from core.backup.service import ensure_imports_dir, import_config
    from core.database import async_session_maker

    identity = _identity()
    async with resource_lock("manager-backup"):
        dest = os.path.join(ensure_imports_dir(), f"manager-{uuid.uuid4().hex}.tar.gz.enc")
        try:
            await asyncio.to_thread(_download, identity, args.backup_id, dest)
            async with async_session_maker() as session:
                result = await import_config(session, dest, identity.backup_passphrase)
        finally:
            try:
                os.remove(dest)
            except OSError:
                pass
    if not result.get("success"):
        raise CommandError("; ".join(str(e) for e in result.get("errors", [])[:5]) or "ripristino fallito")
    return {
        "users_imported": result.get("users_imported"),
        "warnings": [str(w) for w in result.get("warnings", [])[:10]],
        "restart": True,
    }
