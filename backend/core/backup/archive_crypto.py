"""
MADMIN config archive encryption.

An archive holds password hashes, TOTP secrets, WireGuard private keys, IPsec
PSKs and the OpenVPN PKI. When a passphrase is configured it is encrypted
before it is stored or uploaded:

    b"MADMINENC1" | 16-byte salt | Fernet token of the .tar.gz

The key comes from the passphrase through scrypt, so the archive can be
restored on any instance by whoever knows the passphrase, and by nobody else:
there is no recovery if it is lost.

The format is recognised by its first bytes, not by the file name. Archives
written before encryption existed (plain .tar.gz, gzip magic 1f 8b) are
always accepted without a passphrase.
"""
import base64
import os

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt

MAGIC = b"MADMINENC1"
GZIP_MAGIC = b"\x1f\x8b"
SALT_LEN = 16
ENCRYPTED_SUFFIX = ".tar.gz.enc"
PLAIN_SUFFIX = ".tar.gz"


class PassphraseRequired(Exception):
    """The archive is encrypted and no passphrase was given."""


class WrongPassphrase(Exception):
    """The passphrase does not decrypt the archive (or the archive is damaged)."""


class UnknownArchiveFormat(Exception):
    """Neither an encrypted MADMIN archive nor a gzip file."""


def is_archive_name(name: str) -> bool:
    return name.endswith(PLAIN_SUFFIX) or name.endswith(ENCRYPTED_SUFFIX)


def _fernet(passphrase: str, salt: bytes) -> Fernet:
    key = Scrypt(salt=salt, length=32, n=2 ** 15, r=8, p=1).derive(passphrase.encode())
    return Fernet(base64.urlsafe_b64encode(key))


def archive_format(path: str) -> str:
    """'encrypted' or 'plain'; raises UnknownArchiveFormat otherwise."""
    with open(path, "rb") as f:
        head = f.read(len(MAGIC))
    if head == MAGIC:
        return "encrypted"
    if head[:2] == GZIP_MAGIC:
        return "plain"
    raise UnknownArchiveFormat("Formato archivio non riconosciuto")


def encrypt_file(src: str, dst: str, passphrase: str) -> None:
    salt = os.urandom(SALT_LEN)
    with open(src, "rb") as f:
        token = _fernet(passphrase, salt).encrypt(f.read())
    fd = os.open(dst, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "wb") as f:
        f.write(MAGIC + salt + token)


def decrypt_file(src: str, dst: str, passphrase: str) -> None:
    with open(src, "rb") as f:
        data = f.read()
    if not data.startswith(MAGIC):
        raise UnknownArchiveFormat("Non è un archivio cifrato MADMIN")
    salt = data[len(MAGIC):len(MAGIC) + SALT_LEN]
    try:
        plain = _fernet(passphrase, salt).decrypt(data[len(MAGIC) + SALT_LEN:])
    except InvalidToken:
        raise WrongPassphrase("Passphrase errata o archivio danneggiato")
    fd = os.open(dst, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "wb") as f:
        f.write(plain)
