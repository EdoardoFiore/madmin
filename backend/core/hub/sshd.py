"""
OpenSSH configuration for hub support access.

Support SSH uses certificates signed by the hub's SSH user CA, never keys
written to authorized_keys. Two things must hold for a login:
- the hub signed the operator's key for principal madmin-support-<instance_id>,
  valid only for the grant duration and only from 127.0.0.1 (the tunnel end);
- the instance lists that principal for root, which it does only while a
  grant is open (the line also carries expiry-time and from="127.0.0.1").

Files (outside /home and /root: the service runs with ProtectHome):
    /etc/ssh/madmin_hub_ca.pub                  hub SSH user CA
    /etc/ssh/madmin_principals/root             principals accepted for root
    /etc/ssh/sshd_config.d/20-madmin-hub.conf   TrustedUserCAKeys + AuthorizedPrincipalsFile

AuthorizedPrincipalsFile applies to certificate logins only: password and
authorized_keys logins are not affected.
"""
import logging
import os
import subprocess
from datetime import datetime, timezone
from typing import Optional

from . import identity as ident

logger = logging.getLogger(__name__)

SSHD_BIN = "/usr/sbin/sshd"
CA_PATH = "/etc/ssh/madmin_hub_ca.pub"
PRINCIPALS_DIR = "/etc/ssh/madmin_principals"
PRINCIPALS_ROOT = os.path.join(PRINCIPALS_DIR, "root")
DROPIN_PATH = "/etc/ssh/sshd_config.d/20-madmin-hub.conf"
SUPPORT_USER = "root"

_DROPIN = f"""# Managed by MADMIN (hub support access). Removed on unenroll.
TrustedUserCAKeys {CA_PATH}
AuthorizedPrincipalsFile {PRINCIPALS_DIR}/%u
"""


def principal(instance_id: str) -> str:
    return f"madmin-support-{instance_id}"


def _write(path: str, content: str, mode: int = 0o644) -> None:
    tmp = f"{path}.madmin-tmp"
    with open(tmp, "w") as f:
        f.write(content)
    os.chmod(tmp, mode)
    os.replace(tmp, path)


def _read(path: str) -> Optional[str]:
    try:
        with open(path) as f:
            return f.read()
    except FileNotFoundError:
        return None


def _sshd_test() -> tuple[bool, str]:
    os.makedirs("/run/sshd", mode=0o755, exist_ok=True)
    r = subprocess.run([SSHD_BIN, "-t"], capture_output=True, text=True, timeout=15)
    return r.returncode == 0, (r.stderr or r.stdout).strip()[:300]


def _reload() -> None:
    # Socket activation (Ubuntu 24.04): when ssh.service is not running the
    # next connection starts it with the new configuration anyway
    subprocess.run(["systemctl", "try-reload-or-restart", "ssh.service"],
                   capture_output=True, timeout=30)


def ensure_configured() -> None:
    """Install CA + drop-in (blocking). Rolled back if sshd rejects them."""
    if not os.path.exists(SSHD_BIN):
        raise RuntimeError("OpenSSH server non installato")
    ca = ident.read_file("ssh_ca.pub")
    if not ca:
        raise RuntimeError("CA SSH della hub assente: ripetere l'enrollment")
    ca_text = ca.decode().strip() + "\n"
    os.makedirs(PRINCIPALS_DIR, mode=0o755, exist_ok=True)
    if _read(CA_PATH) == ca_text and _read(DROPIN_PATH) == _DROPIN:
        return
    previous_ca, previous_dropin = _read(CA_PATH), _read(DROPIN_PATH)
    _write(CA_PATH, ca_text)
    _write(DROPIN_PATH, _DROPIN)
    ok, err = _sshd_test()
    if not ok:
        for path, old in ((CA_PATH, previous_ca), (DROPIN_PATH, previous_dropin)):
            if old is None:
                try:
                    os.unlink(path)
                except FileNotFoundError:
                    pass
            else:
                _write(path, old)
        raise RuntimeError(f"configurazione sshd rifiutata: {err}")
    _reload()
    logger.info("Hub: sshd configured for support certificates")


def grant(instance_id: str, expires_at: datetime) -> None:
    """Accept the support principal for root until expires_at (UTC)."""
    ensure_configured()
    stamp = expires_at.astimezone(timezone.utc).strftime("%Y%m%d%H%M%SZ")
    _write(PRINCIPALS_ROOT,
           f'expiry-time="{stamp}",from="127.0.0.1" {principal(instance_id)}\n')


def revoke() -> None:
    try:
        os.unlink(PRINCIPALS_ROOT)
    except FileNotFoundError:
        pass


def remove_all() -> None:
    """Undo everything (unenroll)."""
    revoke()
    changed = False
    for path in (DROPIN_PATH, CA_PATH):
        try:
            os.unlink(path)
            changed = True
        except FileNotFoundError:
            pass
    try:
        os.rmdir(PRINCIPALS_DIR)
    except OSError:
        pass
    if changed and os.path.exists(SSHD_BIN):
        _reload()
