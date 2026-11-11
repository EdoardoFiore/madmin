"""
Identity of this instance towards the MADMIN Manager.

The instance is identified by an X.509 client certificate issued by the manager's
CA, never by its IP or hostname (both change). The private key is generated
here and never leaves the machine: the manager only ever sees a CSR.

Everything lives in DATA_DIR/manager/ (0700, files 0600):
    identity.pem  private key (ECDSA P-256) + client certificate (CN =
                  instance_id) in one file, so a renewal replaces both in a
                  single atomic rename and they can never mismatch
    ca.pem        manager CA(s): the only trust anchors for every manager connection.
                  Usually one; during a CA rotation also the next one, accepted
                  only when cross-signed by a CA already here (accept_ca_bundle)
    ssh_ca.pub    manager SSH user CA (support SSH access)
    license.pub   manager license signing key (Ed25519, raw base64)
    state.json    instance_id, manager_url (and manager_url_next while a move to
                  another address is being tried), backup passphrase, revoked flag
    pending.json / pending_key.pem
                  registration waiting for approval on the manager (no token):
                  request id and secret, and the key the certificate will be for

The folder is not part of the config export: an identity copied to another
machine would be a clone of this instance.
"""
import base64
import binascii
import hashlib
import json
import os
import ssl
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional
from urllib.parse import urlsplit

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID

from config import get_settings

TOKEN_PREFIX = "MMGR1-"


class ManagerIdentityError(Exception):
    pass


def manager_dir() -> str:
    return os.path.join(get_settings().data_dir, "manager")


def _path(name: str) -> str:
    return os.path.join(manager_dir(), name)


def write_private(name: str, data: bytes) -> None:
    """Atomic write, 0600, in DATA_DIR/manager."""
    os.makedirs(manager_dir(), mode=0o700, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=manager_dir(), prefix=f".{name}.")
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, _path(name))
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def read_file(name: str) -> Optional[bytes]:
    try:
        with open(_path(name), "rb") as f:
            return f.read()
    except FileNotFoundError:
        return None


# --- Enrollment token ---

@dataclass
class EnrollmentToken:
    manager_url: str      # https://host:port of the manager agent endpoint
    ca_fingerprint: str   # sha256 hex of the manager CA certificate (DER)
    token_id: str
    secret: str


def parse_token(raw: str) -> EnrollmentToken:
    raw = raw.strip()
    if not raw.startswith(TOKEN_PREFIX):
        raise ManagerIdentityError("Token di enrollment non valido (prefisso)")
    body = raw[len(TOKEN_PREFIX):]
    try:
        data = json.loads(base64.urlsafe_b64decode(body + "=" * (-len(body) % 4)))
    except (binascii.Error, ValueError):
        raise ManagerIdentityError("Token di enrollment non valido (codifica)")
    if not isinstance(data, dict):
        raise ManagerIdentityError("Token di enrollment non valido")
    try:
        token = EnrollmentToken(
            manager_url=str(data["u"]).rstrip("/"),
            ca_fingerprint=str(data["f"]).lower(),
            token_id=str(data["i"]),
            secret=str(data["s"]),
        )
    except KeyError as e:
        raise ManagerIdentityError(f"Token di enrollment incompleto ({e.args[0]})")
    token.manager_url = check_manager_url(token.manager_url)
    token.ca_fingerprint = check_fingerprint(token.ca_fingerprint)
    return token


def check_manager_url(url: str) -> str:
    url = (url or "").strip().rstrip("/")
    parts = urlsplit(url)
    if parts.scheme != "https" or not parts.hostname or parts.path not in ("", "/") or parts.query:
        raise ManagerIdentityError("URL manager non valido (atteso https://host:porta)")
    return url


def check_fingerprint(fp: str) -> str:
    """sha256 hex, colons and case tolerated (as printed by openssl)."""
    fp = (fp or "").strip().lower().replace(":", "")
    if len(fp) != 64 or any(c not in "0123456789abcdef" for c in fp):
        raise ManagerIdentityError("Fingerprint CA non valido (sha256 esadecimale)")
    return fp


def ca_fingerprint(ca_pem: bytes) -> str:
    cert = x509.load_pem_x509_certificate(ca_pem)
    return hashlib.sha256(cert.public_bytes(serialization.Encoding.DER)).hexdigest()


def _fp(cert: x509.Certificate) -> str:
    return hashlib.sha256(cert.public_bytes(serialization.Encoding.DER)).hexdigest()


def trusted_cas() -> list:
    pem = read_file("ca.pem")
    return x509.load_pem_x509_certificates(pem) if pem else []


def trusted_ca_fingerprints() -> list:
    return sorted(_fp(c) for c in trusted_cas())


def _is_ca(cert: x509.Certificate) -> bool:
    try:
        return cert.extensions.get_extension_for_class(x509.BasicConstraints).value.ca
    except x509.ExtensionNotFound:
        return False


def _issued_by_any(cert: x509.Certificate, cas: list) -> bool:
    for ca in cas:
        try:
            cert.verify_directly_issued_by(ca)
            return True
        except Exception:
            continue
    return False


def accept_ca_bundle(bundle_pem: bytes) -> list:
    """
    CA rotation: the manager sends its next CA (self-signed) together with a
    cross certificate for the same key and subject, issued by a CA trusted
    here. Only such a CA is added: a manager cannot make the instance trust
    a CA the current one did not vouch for. Expired CAs are dropped, never
    the last valid one. Returns the fingerprints added.
    """
    try:
        offered = x509.load_pem_x509_certificates(bundle_pem)
    except ValueError:
        raise ManagerIdentityError("Bundle CA non valido")
    trusted = trusted_cas()
    if not trusted:
        raise ManagerIdentityError("ca.pem mancante")
    now = datetime.now(timezone.utc)
    known = {_fp(c) for c in trusted}
    spki = serialization.PublicFormat.SubjectPublicKeyInfo
    added = []
    for root in offered:
        if _fp(root) in known or root.issuer != root.subject or not _is_ca(root):
            continue
        if not _issued_by_any(root, [root]) or root.not_valid_after_utc <= now:
            continue
        key = root.public_key().public_bytes(serialization.Encoding.DER, spki)
        vouched = any(
            x is not root and x.subject == root.subject and _is_ca(x)
            and x.public_key().public_bytes(serialization.Encoding.DER, spki) == key
            and x.not_valid_before_utc <= now < x.not_valid_after_utc
            and _issued_by_any(x, trusted)
            for x in offered
        )
        if vouched:
            trusted.append(root)
            known.add(_fp(root))
            added.append(_fp(root))
    valid = [c for c in trusted if c.not_valid_after_utc > now]
    if added or (valid and len(valid) < len(trusted)):
        write_private("ca.pem", b"".join(c.public_bytes(serialization.Encoding.PEM) for c in (valid or trusted)))
    return added


# --- Keys and certificates ---

def new_key_and_csr() -> tuple[bytes, bytes]:
    """(private key PEM, CSR PEM). The CN is assigned by the manager."""
    key = ec.generate_private_key(ec.SECP256R1())
    csr = (
        x509.CertificateSigningRequestBuilder()
        .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "madmin-agent")]))
        .sign(key, hashes.SHA256())
    )
    key_pem = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )
    return key_pem, csr.public_bytes(serialization.Encoding.PEM)


def key_fingerprint(key_pem: bytes) -> str:
    """sha256 of the public key (SPKI DER): shown by the manager for the request."""
    key = serialization.load_pem_private_key(key_pem, password=None)
    spki = key.public_key().public_bytes(serialization.Encoding.DER,
                                         serialization.PublicFormat.SubjectPublicKeyInfo)
    return hashlib.sha256(spki).hexdigest()


def cert_validity(pem: bytes) -> tuple[datetime, datetime]:
    """Validity of the (first) certificate in a PEM bundle."""
    cert = x509.load_pem_x509_certificate(pem)
    return cert.not_valid_before_utc, cert.not_valid_after_utc


def check_issued_cert(cert_pem: bytes, key_pem: bytes, ca_pem: bytes) -> None:
    """The certificate the manager returned is for our key and signed by one
    of its CAs (ca_pem may hold several during a rotation)."""
    cert = x509.load_pem_x509_certificate(cert_pem)
    cas = x509.load_pem_x509_certificates(ca_pem)
    key = serialization.load_pem_private_key(key_pem, password=None)
    pub = serialization.PublicFormat.SubjectPublicKeyInfo
    if cert.public_key().public_bytes(serialization.Encoding.DER, pub) != \
            key.public_key().public_bytes(serialization.Encoding.DER, pub):
        raise ManagerIdentityError("Il certificato ricevuto non corrisponde alla chiave locale")
    if not _issued_by_any(cert, cas):
        raise ManagerIdentityError("Il certificato ricevuto non è firmato dalla CA del manager")


def save_cert_and_key(cert_pem: bytes, key_pem: bytes) -> None:
    write_private("identity.pem", cert_pem.rstrip(b"\n") + b"\n" + key_pem)


def server_ssl_context(ca_pem: bytes) -> ssl.SSLContext:
    """Trusts only the manager CA, hostname checked."""
    ctx = ssl.create_default_context(cadata=ca_pem.decode())
    ctx.minimum_version = ssl.TLSVersion.TLSv1_2
    return ctx


# --- Enrolled identity ---

@dataclass
class ManagerIdentity:
    instance_id: str
    manager_url: str
    revoked: bool
    enrolled_at: str
    backup_passphrase: str
    # Address being tried (manager.relocate): becomes manager_url after a
    # successful hello there, is dropped otherwise
    manager_url_next: str = ""

    @staticmethod
    def ws_url_of(manager_url: str) -> str:
        return "wss://" + manager_url.split("://", 1)[1] + "/agent/ws"

    @property
    def ws_url(self) -> str:
        return self.ws_url_of(self.manager_url)

    def ssl_context(self) -> ssl.SSLContext:
        """mTLS context: manager CA as the only anchor, our certificate as client."""
        ca = read_file("ca.pem")
        if ca is None:
            raise ManagerIdentityError("ca.pem mancante")
        ctx = server_ssl_context(ca)
        ctx.load_cert_chain(_path("identity.pem"))
        return ctx

    def cert_validity(self) -> tuple[datetime, datetime]:
        pem = read_file("identity.pem")
        if pem is None:
            raise ManagerIdentityError("identity.pem mancante")
        return cert_validity(pem)

    def cert_expired(self) -> bool:
        return self.cert_validity()[1] <= datetime.now(timezone.utc)


def load_identity() -> Optional[ManagerIdentity]:
    """The enrolled identity, or None when this instance is not enrolled."""
    raw = read_file("state.json")
    if raw is None or read_file("identity.pem") is None:
        return None
    try:
        s = json.loads(raw)
        return ManagerIdentity(
            instance_id=s["instance_id"],
            manager_url=s["manager_url"],
            revoked=bool(s.get("revoked", False)),
            enrolled_at=s.get("enrolled_at", ""),
            backup_passphrase=s.get("backup_passphrase", ""),
            manager_url_next=s.get("manager_url_next", ""),
        )
    except (ValueError, KeyError) as e:
        raise ManagerIdentityError(f"state.json non leggibile: {e}")


def save_state(identity: ManagerIdentity) -> None:
    write_private("state.json", json.dumps({
        "instance_id": identity.instance_id,
        "manager_url": identity.manager_url,
        "revoked": identity.revoked,
        "enrolled_at": identity.enrolled_at,
        "backup_passphrase": identity.backup_passphrase,
        "manager_url_next": identity.manager_url_next,
    }, indent=2).encode())


def mark_revoked() -> None:
    identity = load_identity()
    if identity and not identity.revoked:
        identity.revoked = True
        save_state(identity)


def state_mtime() -> tuple:
    """Changes when the CLI enrolls, registers or unenrolls (the agent
    reloads on change)."""
    stamps = []
    for name in ("state.json", "pending.json"):
        try:
            stamps.append(os.stat(_path(name)).st_mtime)
        except FileNotFoundError:
            stamps.append(0.0)
    return tuple(stamps)


# --- Registration waiting for approval ---

def load_pending() -> Optional[dict]:
    raw = read_file("pending.json")
    if raw is None:
        return None
    try:
        return json.loads(raw)
    except ValueError:
        return None


def save_pending(data: dict) -> None:
    write_private("pending.json", json.dumps(data, indent=2).encode())


def remove_pending() -> None:
    for name in ("pending.json", "pending_key.pem"):
        try:
            os.unlink(_path(name))
        except FileNotFoundError:
            pass


def remove_identity() -> None:
    for name in ("state.json", "identity.pem", "ca.pem", "ssh_ca.pub", "license.pub",
                 "licenses.json", "results.json", "status.json", "ssh_grant.json",
                 "pending.json", "pending_key.pem"):
        try:
            os.unlink(_path(name))
        except FileNotFoundError:
            pass
