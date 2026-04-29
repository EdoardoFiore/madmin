"""
SSH key push/revoke service.
Writes authorized_keys entry + opens iptables rule via MOD_AGENT_INPUT chain.
"""
import json
import logging
import os
import subprocess
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Tuple

logger = logging.getLogger(__name__)

AUTHORIZED_KEYS_COMMENT = "# madmin-hub-managed"


async def push_key(
    assignment_id: str,
    public_key: str,
    target_user: str = "madmin",
    allow_source_ips: Optional[List[str]] = None,
    expires_at: Optional[str] = None,
) -> Tuple[bool, str]:
    """Write key to authorized_keys and open iptables rule."""
    from core.database import async_session_maker
    from sqlalchemy import select
    from modules.agent.models import PushedSSHKey

    async with async_session_maker() as session:
        result = await session.execute(
            select(PushedSSHKey).where(
                PushedSSHKey.assignment_id == assignment_id,
                PushedSSHKey.active == True,
            )
        )
        existing = result.scalar_one_or_none()
        if existing:
            return True, "Chiave già installata"

    # Write to authorized_keys
    ok, msg = _write_authorized_key(public_key, target_user, allow_source_ips or [])
    if not ok:
        return False, msg

    # Open iptables for source IPs (if specified)
    rule_added = False
    if allow_source_ips:
        for ip in allow_source_ips:
            _add_iptables_allow(ip)
        rule_added = True

    expires_dt = None
    if expires_at:
        try:
            expires_dt = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
        except Exception:
            pass

    # Persist
    async with async_session_maker() as session:
        session.add(PushedSSHKey(
            assignment_id=assignment_id,
            target_user=target_user,
            public_key=public_key,
            allow_source_ips=json.dumps(allow_source_ips) if allow_source_ips else None,
            iptables_rule_added=rule_added,
            expires_at=expires_dt,
            active=True,
        ))
        await session.commit()

    logger.info(f"SSH key pushed for assignment {assignment_id}, user {target_user}")
    return True, "Chiave SSH installata"


async def revoke_key(assignment_id: str) -> Tuple[bool, str]:
    """Remove key from authorized_keys and close iptables rule."""
    from core.database import async_session_maker
    from sqlalchemy import select
    from modules.agent.models import PushedSSHKey

    async with async_session_maker() as session:
        result = await session.execute(
            select(PushedSSHKey).where(
                PushedSSHKey.assignment_id == assignment_id,
                PushedSSHKey.active == True,
            )
        )
        key_row = result.scalar_one_or_none()
        if not key_row:
            return True, "Chiave non presente"

        _remove_authorized_key(key_row.public_key, key_row.target_user)

        if key_row.iptables_rule_added and key_row.allow_source_ips:
            ips = json.loads(key_row.allow_source_ips)
            for ip in ips:
                _remove_iptables_allow(ip)

        key_row.active = False
        key_row.revoked_at = datetime.utcnow()
        session.add(key_row)
        await session.commit()

    logger.info(f"SSH key revoked for assignment {assignment_id}")
    return True, "Chiave SSH rimossa"


async def cleanup_expired_keys():
    """Called every 5 min — revoke keys past expires_at."""
    from core.database import async_session_maker
    from sqlalchemy import select
    from modules.agent.models import PushedSSHKey

    async with async_session_maker() as session:
        result = await session.execute(
            select(PushedSSHKey).where(
                PushedSSHKey.active == True,
                PushedSSHKey.expires_at != None,
                PushedSSHKey.expires_at < datetime.utcnow(),
            )
        )
        expired = result.scalars().all()
        for k in expired:
            await revoke_key(k.assignment_id)
            logger.info(f"Auto-revoked expired SSH key: assignment={k.assignment_id}")


def _authorized_keys_path(username: str) -> Path:
    try:
        import pwd
        home = pwd.getpwnam(username).pw_dir
    except Exception:
        home = f"/home/{username}"
    return Path(home) / ".ssh" / "authorized_keys"


def _write_authorized_key(public_key: str, username: str, source_ips: List[str]) -> Tuple[bool, str]:
    path = _authorized_keys_path(username)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        os.chmod(path.parent, 0o700)

        # Build entry with optional from= restriction
        entry = public_key.strip()
        if source_ips:
            from_str = ",".join(source_ips)
            entry = f'from="{from_str}" {entry}'
        entry = f"{entry} {AUTHORIZED_KEYS_COMMENT}\n"

        # Append (don't overwrite)
        with open(path, "a") as f:
            f.write(entry)
        os.chmod(path, 0o600)
        return True, "OK"
    except PermissionError:
        return False, f"Permission denied scrivendo {path}"
    except Exception as e:
        return False, str(e)


def _remove_authorized_key(public_key: str, username: str):
    path = _authorized_keys_path(username)
    if not path.exists():
        return
    try:
        key_part = public_key.strip().split()[:2]  # type + base64
        key_identifier = " ".join(key_part)
        lines = path.read_text().splitlines(keepends=True)
        new_lines = [
            l for l in lines
            if key_identifier not in l or AUTHORIZED_KEYS_COMMENT not in l
        ]
        path.write_text("".join(new_lines))
    except Exception as e:
        logger.warning(f"Failed to remove key from {path}: {e}")


def _add_iptables_allow(source_ip: str):
    from config import get_settings
    if get_settings().mock_iptables:
        logger.info(f"[MOCK] iptables: allow SSH from {source_ip}")
        return
    try:
        subprocess.run(
            ["iptables", "-I", "MOD_AGENT_INPUT", "-p", "tcp", "--dport", "22",
             "-s", source_ip, "-j", "ACCEPT", "-m", "comment",
             "--comment", f"madmin-hub-ssh-{source_ip}"],
            check=True, capture_output=True,
        )
    except Exception as e:
        logger.warning(f"iptables allow SSH failed for {source_ip}: {e}")


def _remove_iptables_allow(source_ip: str):
    from config import get_settings
    if get_settings().mock_iptables:
        logger.info(f"[MOCK] iptables: remove SSH allow for {source_ip}")
        return
    try:
        subprocess.run(
            ["iptables", "-D", "MOD_AGENT_INPUT", "-p", "tcp", "--dport", "22",
             "-s", source_ip, "-j", "ACCEPT", "-m", "comment",
             "--comment", f"madmin-hub-ssh-{source_ip}"],
            capture_output=True,
        )
    except Exception as e:
        logger.debug(f"iptables remove failed for {source_ip}: {e}")
