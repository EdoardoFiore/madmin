"""
Module licenses issued by the manager.

A license is `<base64url(payload)>.<base64url(signature)>`, signed with the
manager's Ed25519 license key (public half received at enrollment, license.pub).
Payload: {"lid", "iid", "feature", "iat", "nbf", "exp"}; it is valid on this
instance only (iid = instance_id) and between nbf and exp.

Licenses are short (the manager re-issues them before they expire, as long as
they stay active), so no revocation list is needed offline: a revoked
license simply is not renewed. license.revoke removes one at once.

A module that declares `"license": {"feature": "..."}` in its manifest can be
activated, and is loaded at startup, only with a valid license for that
feature. An expired license never deactivates a module (that drops its
tables): the module is just not loaded until a license is back.

This is a contractual control, not DRM: whoever is root on the machine can
change the code.
"""
import base64
import binascii
import json
import logging
import os
import time
from typing import Dict, Optional, Tuple

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from pydantic import Field

from . import identity as ident, protocol
from .commands import CommandArgs, CommandContext, CommandError, command

logger = logging.getLogger(__name__)

_FILE = "licenses.json"
# (mtime of licenses.json, mtime of state.json) -> verified payloads by lid
_cache: Optional[Tuple[Tuple[float, float], Dict[str, dict]]] = None


class LicenseError(ValueError):
    pass


def _b64d(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def _public_key() -> Optional[Ed25519PublicKey]:
    raw = ident.read_file("license.pub")
    if not raw:
        return None
    try:
        return Ed25519PublicKey.from_public_bytes(base64.b64decode(raw.strip()))
    except (binascii.Error, ValueError):
        logger.error("Manager license public key unreadable")
        return None


def verify(token: str, instance_id: str, key: Ed25519PublicKey, check_time: bool = True) -> dict:
    """The payload of a valid license for this instance. Raises LicenseError."""
    try:
        body, sig = token.strip().split(".", 1)
        key.verify(_b64d(sig), body.encode())
        payload = json.loads(_b64d(body))
    except (ValueError, binascii.Error, InvalidSignature):
        raise LicenseError("licenza non valida (firma)")
    if not isinstance(payload, dict) or payload.get("iid") != instance_id:
        raise LicenseError("licenza emessa per un'altra istanza")
    for k in ("lid", "feature", "nbf", "exp"):
        if k not in payload:
            raise LicenseError(f"licenza incompleta ({k})")
    if check_time and not _in_validity(payload, time.time()):
        raise LicenseError("licenza scaduta o non ancora valida")
    return payload


def _in_validity(payload: dict, now: float) -> bool:
    # 5 minutes of tolerance on nbf for clock skew between manager and instance
    return payload["nbf"] - 300 <= now < payload["exp"]


def _mtime(name: str) -> float:
    try:
        return os.stat(os.path.join(ident.manager_dir(), name)).st_mtime
    except FileNotFoundError:
        return 0.0


def _stored() -> list:
    raw = ident.read_file(_FILE)
    try:
        data = json.loads(raw) if raw else []
    except ValueError:
        return []
    return [t for t in data if isinstance(t, str)]


def _valid_licenses() -> Dict[str, dict]:
    global _cache
    stamp = (_mtime(_FILE), _mtime("state.json"))
    if _cache is not None and _cache[0] == stamp:
        return _cache[1]
    valid: Dict[str, dict] = {}
    identity = ident.load_identity()
    key = _public_key()
    if identity and not identity.revoked and key:
        # Signature and instance checked once per file version; the validity
        # window is checked on every read (is_licensed, licensed_features)
        for token in _stored():
            try:
                p = verify(token, identity.instance_id, key, check_time=False)
            except LicenseError:
                continue
            valid[p["lid"]] = p
    _cache = (stamp, valid)
    return valid


def license_ids() -> list:
    """Ids of the licenses installed here and valid now (hello.state)."""
    now = time.time()
    return sorted(lid for lid, p in _valid_licenses().items() if _in_validity(p, now))


def is_licensed(feature: str) -> bool:
    """True if a license for `feature` is valid now (blocking: file reads)."""
    now = time.time()
    return any(p["feature"] == feature and _in_validity(p, now) for p in _valid_licenses().values())


def licensed_features() -> Dict[str, int]:
    now = time.time()
    out: Dict[str, int] = {}
    for p in _valid_licenses().values():
        if _in_validity(p, now):
            out[p["feature"]] = max(out.get(p["feature"], 0), int(p["exp"]))
    return out


# --- Commands ---

class LicenseInstallArgs(CommandArgs):
    token: str = Field(min_length=10, max_length=4096)


@command(protocol.CMD_LICENSE_INSTALL, LicenseInstallArgs, timeout=15)
async def _install(args: LicenseInstallArgs, ctx: CommandContext) -> dict:
    from .client import manager_agent
    identity = manager_agent.identity
    key = _public_key()
    if identity is None or key is None:
        raise CommandError("istanza non registrata o chiave licenze assente", protocol.ERR_PRECONDITION)
    try:
        payload = verify(args.token, identity.instance_id, key)
    except LicenseError as e:
        raise CommandError(str(e))
    kept = []
    for token in _stored():
        try:
            other = json.loads(_b64d(token.split(".", 1)[0]))
        except (ValueError, binascii.Error):
            continue
        # A renewal replaces the license it renews
        if other.get("lid") != payload["lid"]:
            kept.append(token)
    kept.append(args.token.strip())
    ident.write_private(_FILE, json.dumps(kept).encode())
    return {"license_id": payload["lid"], "feature": payload["feature"], "exp": payload["exp"]}


class LicenseRevokeArgs(CommandArgs):
    license_id: str = Field(min_length=1, max_length=64)


@command(protocol.CMD_LICENSE_REVOKE, LicenseRevokeArgs, timeout=15)
async def _revoke(args: LicenseRevokeArgs, ctx: CommandContext) -> dict:
    kept = []
    removed = False
    for token in _stored():
        try:
            lid = json.loads(_b64d(token.split(".", 1)[0])).get("lid")
        except (ValueError, binascii.Error):
            continue
        if lid == args.license_id:
            removed = True
        else:
            kept.append(token)
    ident.write_private(_FILE, json.dumps(kept).encode())
    return {"removed": removed}
