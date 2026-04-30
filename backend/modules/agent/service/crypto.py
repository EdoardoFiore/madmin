"""
Shared Fernet encrypt/decrypt for agent module secrets.
Key = sha256(SECRET_KEY | purpose), different purpose per secret type.
"""
import base64
import hashlib

from cryptography.fernet import Fernet


def _fernet(purpose: str) -> Fernet:
    from config import get_settings
    s = get_settings()
    raw = hashlib.sha256(f"{s.secret_key}|{purpose}".encode()).digest()
    return Fernet(base64.urlsafe_b64encode(raw))


def encrypt_value(plaintext: str, purpose: str) -> str:
    return _fernet(purpose).encrypt(plaintext.encode()).decode()


def decrypt_value(ciphertext: str, purpose: str) -> str:
    return _fernet(purpose).decrypt(ciphertext.encode()).decode()
