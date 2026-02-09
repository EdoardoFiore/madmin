"""
MADMIN TOTP Utilities

Provides Time-based One-Time Password (TOTP) functionality for 2FA.
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


def generate_backup_codes(count: int = 10) -> List[str]:
    """
    Generate one-time backup codes for account recovery.
    
    Args:
        count: Number of backup codes to generate
        
    Returns:
        List of 8-character uppercase hex codes
    """
    return [secrets.token_hex(4).upper() for _ in range(count)]


def get_provisioning_uri(secret: str, username: str, issuer: str = "MADMIN") -> str:
    """
    Generate a provisioning URI for authenticator app setup.
    
    Args:
        secret: TOTP secret key
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
        secret: User's TOTP secret
        code: 6-digit code from authenticator app
        
    Returns:
        True if code is valid (including ±1 time window for clock drift)
    """
    totp = pyotp.TOTP(secret)
    return totp.verify(code, valid_window=1)


def verify_backup_code(codes_json: str, code: str) -> Tuple[bool, str]:
    """
    Verify a backup code and remove it if valid.
    
    Args:
        codes_json: JSON string containing list of backup codes
        code: Backup code to verify
        
    Returns:
        Tuple of (is_valid, updated_codes_json)
    """
    codes = json.loads(codes_json) if codes_json else []
    code_clean = code.upper().replace("-", "").replace(" ", "")
    
    if code_clean in codes:
        codes.remove(code_clean)
        return True, json.dumps(codes)
    
    return False, codes_json
