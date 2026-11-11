"""
Enrollment of this instance to a MADMIN Manager, certificate renewal, unenroll.

Two ways in, both from the root CLI:
- enroll: with a token (MMGR1-...), immediate;
- register: with the manager URL only; the manager shows the request and an
  operator approves it later. The service polls until then (client.py).

Enrollment runs only from the root CLI (`python -m core.manager enroll`), called
by setup-madmin.sh: there is no HTTP endpoint for it, so nobody who can reach
the panel can bind the instance to a manager of their choice.

The token carries the sha256 of the manager CA: the CA downloaded on first contact
is accepted only if it matches, and from then on it is the only trust anchor
(no trust-on-first-use, no unverified TLS after the download).
"""
import logging
from datetime import datetime, timezone
from typing import Optional

import httpx

from . import identity as ident
from .identity import ManagerIdentity, ManagerIdentityError
from .inventory import collect_facts
from .protocol import PROTOCOL_VERSION

logger = logging.getLogger(__name__)

_TIMEOUT = httpx.Timeout(30.0, connect=15.0)

# Renew once less than this fraction of the certificate lifetime is left
RENEW_AT_REMAINING = 1 / 3


def _detail(r: httpx.Response) -> str:
    try:
        d = r.json().get("detail")
        if d:
            return str(d)[:300]
    except ValueError:
        pass
    return f"HTTP {r.status_code}"


async def _fetch_ca(manager_url: str, expected_fp: Optional[str]) -> bytes:
    """
    The manager CA. The download itself is not verified: with expected_fp it is
    accepted only if it matches; without, it is trusted on first use (the
    caller says so to the operator, and the manager shows the same fingerprint).
    """
    async with httpx.AsyncClient(verify=False, timeout=_TIMEOUT) as client:
        r = await client.get(f"{manager_url}/agent/ca.pem")
    if r.status_code != 200:
        raise ManagerIdentityError(f"CA del manager non scaricabile: {_detail(r)}")
    ca_pem = r.content
    try:
        fp = ident.ca_fingerprint(ca_pem)
    except ValueError:
        raise ManagerIdentityError("Il manager ha restituito una CA non valida")
    if expected_fp is not None and fp != expected_fp:
        raise ManagerIdentityError(
            "Il fingerprint della CA del manager non corrisponde a quello atteso: "
            "connessione non attendibile, registrazione interrotta"
        )
    return ca_pem


def _check_not_enrolled(force: bool) -> None:
    current = ident.load_identity()
    if current and not current.revoked and not force:
        raise ManagerIdentityError(
            f"Istanza già registrata (instance_id {current.instance_id}): "
            "usa 'unenroll' o --force"
        )


def _save_identity(data: dict, manager_url: str, key_pem: bytes, ca_pem: bytes) -> ManagerIdentity:
    cert_pem = str(data.get("cert_pem", "")).encode()
    instance_id = str(data.get("instance_id", ""))
    if not cert_pem or not instance_id:
        raise ManagerIdentityError("Risposta di enrollment incompleta")
    ident.check_issued_cert(cert_pem, key_pem, ca_pem)

    # state.json last: its presence is what marks the instance as enrolled
    ident.write_private("ca.pem", ca_pem)
    ident.save_cert_and_key(cert_pem, key_pem)
    if data.get("ssh_ca_pub"):
        ident.write_private("ssh_ca.pub", str(data["ssh_ca_pub"]).strip().encode() + b"\n")
    if data.get("license_pub"):
        ident.write_private("license.pub", str(data["license_pub"]).strip().encode())
    identity = ManagerIdentity(
        instance_id=instance_id,
        manager_url=manager_url,
        revoked=False,
        enrolled_at=datetime.now(timezone.utc).isoformat(),
        backup_passphrase=str(data.get("backup_passphrase", "")),
    )
    ident.save_state(identity)
    ident.remove_pending()
    return identity


async def enroll(raw_token: str, force: bool = False) -> ManagerIdentity:
    token = ident.parse_token(raw_token)
    _check_not_enrolled(force)

    ca_pem = await _fetch_ca(token.manager_url, token.ca_fingerprint)
    key_pem, csr_pem = ident.new_key_and_csr()
    facts = await collect_facts()

    async with httpx.AsyncClient(verify=ident.server_ssl_context(ca_pem), timeout=_TIMEOUT) as client:
        r = await client.post(f"{token.manager_url}/agent/enroll", json={
            "token_id": token.token_id,
            "secret": token.secret,
            "csr": csr_pem.decode(),
            "protocol": PROTOCOL_VERSION,
            "facts": facts,
        })
    if r.status_code != 200:
        raise ManagerIdentityError(f"Enrollment rifiutato dal manager: {_detail(r)}")
    return _save_identity(r.json(), token.manager_url, key_pem, ca_pem)


async def register(manager_url: str, ca_sha256: Optional[str] = None, force: bool = False) -> dict:
    """
    Ask the manager to enroll this instance without a token. Returns the
    request: the agent then polls until an operator approves it.
    """
    manager_url = ident.check_manager_url(manager_url)
    expected = ident.check_fingerprint(ca_sha256) if ca_sha256 else None
    _check_not_enrolled(force)

    ca_pem = await _fetch_ca(manager_url, expected)
    key_pem, csr_pem = ident.new_key_and_csr()
    facts = await collect_facts()
    async with httpx.AsyncClient(verify=ident.server_ssl_context(ca_pem), timeout=_TIMEOUT) as client:
        r = await client.post(f"{manager_url}/agent/register", json={
            "csr": csr_pem.decode(),
            "protocol": PROTOCOL_VERSION,
            "ca_pinned": expected is not None,
            "facts": facts,
        })
    if r.status_code != 200:
        raise ManagerIdentityError(f"Registrazione rifiutata dal manager: {_detail(r)}")
    data = r.json()
    ident.write_private("ca.pem", ca_pem)
    ident.write_private("pending_key.pem", key_pem)
    pending = {
        "manager_url": manager_url,
        "request_id": str(data["request_id"]),
        "request_secret": str(data["request_secret"]),
        "status": "pending",
        "key_fingerprint": ident.key_fingerprint(key_pem),
        "ca_fingerprint": ident.ca_fingerprint(ca_pem),
        "ca_pinned": expected is not None,
        "requested_at": datetime.now(timezone.utc).isoformat(),
        "poll_interval": int(data.get("poll_interval") or 60),
    }
    ident.save_pending(pending)
    return pending


async def poll_registration() -> str:
    """One check of a pending registration: 'approved' (identity saved),
    'pending', or the final 'rejected' / 'expired'. Raises on network errors."""
    pending = ident.load_pending()
    if not pending or pending.get("status") != "pending":
        return (pending or {}).get("status", "none")
    ca_pem = ident.read_file("ca.pem")
    key_pem = ident.read_file("pending_key.pem")
    if not ca_pem or not key_pem:
        raise ManagerIdentityError("Registrazione in attesa incompleta: ripetere 'register'")
    async with httpx.AsyncClient(verify=ident.server_ssl_context(ca_pem), timeout=_TIMEOUT) as client:
        r = await client.get(f"{pending['manager_url']}/agent/register/{pending['request_id']}",
                             headers={"X-Request-Secret": pending["request_secret"]})
    if r.status_code == 404:
        status = "rejected"
    elif r.status_code != 200:
        raise ManagerIdentityError(f"Manager: {_detail(r)}")
    else:
        data = r.json()
        status = str(data.get("status"))
        if status == "approved":
            _save_identity(data, pending["manager_url"], key_pem, ca_pem)
            return status
    if status in ("rejected", "expired"):
        pending["status"] = status
        ident.save_pending(pending)
    return status


def renewal_due(identity: ManagerIdentity) -> bool:
    start, end = identity.cert_validity()
    remaining = (end - datetime.now(timezone.utc)).total_seconds()
    return remaining < (end - start).total_seconds() * RENEW_AT_REMAINING


async def renew(identity: ManagerIdentity) -> None:
    """New key and certificate, authenticated by the current certificate."""
    key_pem, csr_pem = ident.new_key_and_csr()
    async with httpx.AsyncClient(verify=identity.ssl_context(), timeout=_TIMEOUT) as client:
        r = await client.post(f"{identity.manager_url}/agent/renew", json={"csr": csr_pem.decode()})
    if r.status_code != 200:
        raise ManagerIdentityError(f"Rinnovo certificato rifiutato: {_detail(r)}")
    cert_pem = str(r.json().get("cert_pem", "")).encode()
    ident.check_issued_cert(cert_pem, key_pem, ident.read_file("ca.pem") or b"")
    ident.save_cert_and_key(cert_pem, key_pem)
    logger.info("Manager: client certificate renewed")


async def unenroll(notify: bool = True) -> None:
    """Forget the manager. The manager is told first (best effort) so it can mark the
    instance as decommissioned instead of waiting for it."""
    identity = ident.load_identity()
    if identity and notify and not identity.revoked:
        try:
            async with httpx.AsyncClient(verify=identity.ssl_context(), timeout=_TIMEOUT) as client:
                await client.post(f"{identity.manager_url}/agent/unenroll")
        except Exception as e:
            logger.warning("Manager not notified of the unenroll: %s", e)
    from .support import cleanup_all
    await cleanup_all()
    ident.remove_identity()
    ident.remove_pending()
