"""
MADMIN TOTP Utilities

Provides Time-based One-Time Password (TOTP) functionality for 2FA.
Backup codes are hashed with bcrypt before storage.
TOTP secrets are encrypted by callers (see service.py) before DB storage.
"""
import pyotp
import qrcode
import io
import base64
import secrets
import json
from typing import Tuple, List


def generate_totp_secret() -> str:
    """Generate a random TOTP secret in Base32 format."""
    return pyotp.random_base32()


def generate_backup_codes(count: int = 8) -> List[str]:
    """
    Generate one-time backup codes for account recovery.

    Returns:
        List of 12-character uppercase hex codes (48 bits of entropy each).
        These are plaintext — callers must hash them before storing.
    """
    return [secrets.token_hex(6).upper() for _ in range(count)]


def hash_backup_codes(codes: List[str]) -> List[dict]:
    """
    Hash a list of plaintext backup codes with bcrypt.

    Returns:
        List of {"hash": bcrypt_hash, "used": False} dicts for DB storage.
    """
    from .service import pwd_context
    return [{"hash": pwd_context.hash(code.upper()), "used": False} for code in codes]


def get_provisioning_uri(secret: str, username: str, issuer: str = "MADMIN") -> str:
    """
    Generate a provisioning URI for authenticator app setup.

    Args:
        secret: TOTP secret key (plaintext, not encrypted)
        username: User's username
        issuer: Application name shown in authenticator

    Returns:
        otpauth:// URI for QR code generation
    """
    totp = pyotp.TOTP(secret)
    return totp.provisioning_uri(name=username, issuer_name=issuer)


def generate_qr_base64(uri: str) -> str:
    """
    Generate a QR code image as base64-encoded PNG.

    Args:
        uri: The provisioning URI to encode

    Returns:
        Base64-encoded PNG image string
    """
    qr = qrcode.make(uri)
    buffer = io.BytesIO()
    qr.save(buffer, format='PNG')
    return base64.b64encode(buffer.getvalue()).decode()


def verify_totp(secret: str, code: str) -> bool:
    """
    Verify a TOTP code against the secret.

    Args:
        secret: User's TOTP secret (plaintext — decrypt before calling)
        code: 6-digit code from authenticator app

    Returns:
        True if code is valid within the current 30-second window.
    """
    totp = pyotp.TOTP(secret)
    return totp.verify(code, valid_window=0)


def verify_backup_code(codes_json: str, code: str) -> Tuple[bool, str]:
    """
    Verify a backup code against stored bcrypt hashes and mark it as used.

    Args:
        codes_json: JSON string containing list of {"hash": str, "used": bool}
        code: Backup code to verify (case-insensitive, dashes/spaces ignored)

    Returns:
        Tuple of (is_valid, updated_codes_json)
    """
    from .service import pwd_context

    codes = json.loads(codes_json) if codes_json else []
    code_clean = code.upper().replace("-", "").replace(" ", "")

    for i, entry in enumerate(codes):
        if entry.get("used", False):
            continue
        if pwd_context.verify(code_clean, entry["hash"]):
            codes[i] = {**entry, "used": True}
            return True, json.dumps(codes)

    return False, codes_json
