"""
Temporary support access opened by the hub.

UI: a hidden superuser account (User.is_hub_support) that expires with the
support session. It has an unusable random password: the only way in is a
one-time ticket (32 random bytes, valid 2 minutes, kept here only as a hash)
that the operator exchanges at POST /api/auth/token/hub-ticket. The account
does not appear in user management or in backups; what it does is in the
audit log under its name (hub-<operator>-<suffix>).

SSH: see sshd.py (certificate + principal for root while the grant is open).

A sweeper removes expired accounts and grants every minute, and tells the
hub; the expiry is also enforced on every request (get_current_user) and by
sshd itself (certificate validity, expiry-time on the principal).
"""
import asyncio
import hashlib
import json
import logging
import os
import secrets
import time
from datetime import datetime, timedelta, timezone
from typing import Dict, Optional, Tuple
import uuid

from pydantic import Field
from sqlmodel import select

from . import identity as ident, protocol, sshd
from .commands import CommandArgs, CommandContext, CommandError, command

logger = logging.getLogger(__name__)

TICKET_TTL = 120
SWEEP_INTERVAL = 60
MAX_SUPPORT_MINUTES = 8 * 60

# sha256(ticket) -> (user_id, monotonic expiry)
_tickets: Dict[str, Tuple[uuid.UUID, float]] = {}


def _hash(ticket: str) -> str:
    return hashlib.sha256(ticket.encode()).hexdigest()


def _new_ticket(user_id: uuid.UUID) -> str:
    ticket = secrets.token_urlsafe(32)
    _tickets[_hash(ticket)] = (user_id, time.monotonic() + TICKET_TTL)
    return ticket


def redeem_ticket(ticket: str) -> Optional[uuid.UUID]:
    """The account a ticket opens, once: the ticket is consumed either way."""
    if not ticket or len(ticket) > 100:
        return None
    entry = _tickets.pop(_hash(ticket), None)
    if entry is None or entry[1] < time.monotonic():
        return None
    return entry[0]


def _purge_tickets() -> None:
    now = time.monotonic()
    for key in [k for k, (_, exp) in _tickets.items() if exp < now]:
        _tickets.pop(key, None)


# --- UI accounts ---

class UiOpenArgs(CommandArgs):
    minutes: int = Field(default=60, ge=5, le=MAX_SUPPORT_MINUTES)
    # Ask a new ticket for an account already open (link lost, ticket expired)
    username: Optional[str] = Field(default=None, pattern=r"^hub-[a-z0-9._-]{1,45}$")


@command(protocol.CMD_SUPPORT_UI_OPEN, UiOpenArgs, timeout=30)
async def _ui_open(args: UiOpenArgs, ctx: CommandContext) -> dict:
    from core.auth.models import User
    from core.auth.service import get_password_hash
    from core.database import async_session_maker

    async with async_session_maker() as session:
        if args.username:
            user = (await session.execute(select(User).where(
                User.username == args.username, User.is_hub_support == True))).scalar_one_or_none()  # noqa: E712
            if user is None or user.expires_at is None or user.expires_at <= datetime.utcnow():
                raise CommandError("sessione di supporto non trovata o scaduta")
        else:
            name = ctx.operator.lower().replace("@", ".")[:30]
            user = User(
                username=f"hub-{name}-{secrets.token_hex(3)}",
                hashed_password=await asyncio.to_thread(get_password_hash, secrets.token_urlsafe(48)),
                is_active=True,
                is_superuser=True,
                is_hub_support=True,
                expires_at=datetime.utcnow() + timedelta(minutes=args.minutes),
            )
            session.add(user)
            await session.commit()
            await session.refresh(user)
        ticket = _new_ticket(user.id)
        return {
            "username": user.username,
            "ticket": ticket,
            "ticket_ttl": TICKET_TTL,
            "expires_at": user.expires_at.replace(tzinfo=timezone.utc).isoformat(),
            "login_path": "/login.html",
        }


class UiCloseArgs(CommandArgs):
    username: Optional[str] = Field(default=None, pattern=r"^hub-[a-z0-9._-]{1,45}$")


async def _delete_support_users(username: Optional[str] = None, only_expired: bool = False) -> list:
    from core.auth.models import User
    from core.database import async_session_maker

    async with async_session_maker() as session:
        query = select(User).where(User.is_hub_support == True)  # noqa: E712
        if username:
            query = query.where(User.username == username)
        if only_expired:
            query = query.where(User.expires_at <= datetime.utcnow())
        users = (await session.execute(query)).scalars().all()
        names = [u.username for u in users]
        ids = {u.id for u in users}
        for u in users:
            await session.delete(u)
        if users:
            await session.commit()
    # A ticket not yet redeemed must not outlive its account
    for key in [k for k, (u_id, _) in _tickets.items() if u_id in ids]:
        _tickets.pop(key, None)
    return names


@command(protocol.CMD_SUPPORT_UI_CLOSE, UiCloseArgs, timeout=30)
async def _ui_close(args: UiCloseArgs, ctx: CommandContext) -> dict:
    return {"closed": await _delete_support_users(args.username)}


# --- SSH grant ---

class SshGrantArgs(CommandArgs):
    minutes: int = Field(default=60, ge=5, le=MAX_SUPPORT_MINUTES)


def _grant_state() -> Optional[datetime]:
    raw = ident.read_file("ssh_grant.json")
    if not raw:
        return None
    try:
        return datetime.fromisoformat(json.loads(raw)["expires_at"])
    except (ValueError, KeyError):
        return None


def ssh_grant_active() -> bool:
    exp = _grant_state()
    return exp is not None and exp > datetime.now(timezone.utc)


def _grant(instance_id: str, minutes: int) -> datetime:
    expires_at = datetime.now(timezone.utc) + timedelta(minutes=minutes)
    sshd.grant(instance_id, expires_at)
    ident.write_private("ssh_grant.json", json.dumps({"expires_at": expires_at.isoformat()}).encode())
    return expires_at


def _revoke_grant() -> None:
    sshd.revoke()
    try:
        os.unlink(os.path.join(ident.hub_dir(), "ssh_grant.json"))
    except FileNotFoundError:
        pass


@command(protocol.CMD_SUPPORT_SSH_GRANT, SshGrantArgs, timeout=60)
async def _ssh_grant(args: SshGrantArgs, ctx: CommandContext) -> dict:
    from .client import hub_agent
    if hub_agent.identity is None:
        raise CommandError("istanza non registrata")
    try:
        expires_at = await asyncio.to_thread(_grant, hub_agent.identity.instance_id, args.minutes)
    except RuntimeError as e:
        raise CommandError(str(e))
    return {
        "user": sshd.SUPPORT_USER,
        "principal": sshd.principal(hub_agent.identity.instance_id),
        "expires_at": expires_at.isoformat(),
    }


@command(protocol.CMD_SUPPORT_SSH_REVOKE, timeout=30)
async def _ssh_revoke(args: CommandArgs, ctx: CommandContext) -> dict:
    await asyncio.to_thread(_revoke_grant)
    return {}


async def ui_session_active() -> bool:
    from core.auth.models import User
    from core.database import async_session_maker

    async with async_session_maker() as session:
        row = (await session.execute(select(User.id).where(
            User.is_hub_support == True, User.expires_at > datetime.utcnow()  # noqa: E712
        ).limit(1))).first()
    return row is not None


# --- Expiry ---

async def sweep_once() -> None:
    from .client import hub_agent
    _purge_tickets()
    expired = await _delete_support_users(only_expired=True)
    if expired:
        logger.info("Hub support accounts expired: %s", ", ".join(expired))
        hub_agent.send_event(protocol.EVENT_SUPPORT_EXPIRED, {"ui": expired})
    exp = await asyncio.to_thread(_grant_state)
    if exp is not None and exp <= datetime.now(timezone.utc):
        await asyncio.to_thread(_revoke_grant)
        logger.info("Hub support SSH grant expired")
        hub_agent.send_event(protocol.EVENT_SUPPORT_EXPIRED, {"ssh": True})


async def sweeper() -> None:
    while True:
        try:
            await sweep_once()
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Hub support sweeper error")
        await asyncio.sleep(SWEEP_INTERVAL)


async def cleanup_all() -> None:
    """Close every support access and undo the sshd setup (unenroll)."""
    _tickets.clear()
    try:
        await _delete_support_users()
    except Exception as e:
        logger.warning("Hub support accounts not removed: %s", e)
    await asyncio.to_thread(_revoke_grant)
    await asyncio.to_thread(sshd.remove_all)
