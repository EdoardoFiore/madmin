"""
MADMIN remote backup storage (SFTP, FTPS).

Synchronous: callers run these functions in a thread (asyncio.to_thread). Every
network step has a timeout, so a server that accepts the connection and then
never answers costs a request a few seconds, not the whole event loop.

- SFTP: the server key is compared with the one pinned at the first
  connection (BackupSettings.remote_host_key) before the password is sent.
  Without the check anyone able to intercept the connection received the
  credentials and every archive.
- FTPS: explicit TLS for the control and the data channel. Plain FTP is not
  supported: it sent the password and the archives in clear.
"""
import base64
import hashlib
import logging
import posixpath
import socket
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from ftplib import FTP_TLS, error_perm
from typing import List, Optional

from .archive_crypto import is_archive_name

logger = logging.getLogger(__name__)

CONNECT_TIMEOUT = 15
IO_TIMEOUT = 60


@dataclass
class RemoteTarget:
    protocol: str            # "sftp" or "ftps"
    host: str
    port: int
    username: str
    password: str
    path: str = "/"
    host_key: Optional[str] = None


class HostKeyMismatch(Exception):
    def __init__(self, expected: str, presented: str):
        super().__init__(
            f"La chiave del server SFTP è cambiata (attesa {expected}, presentata {presented}). "
            "Se il cambio è legittimo, dimentica la chiave nelle impostazioni backup."
        )
        self.presented = presented


def fingerprint(key) -> str:
    digest = base64.b64encode(hashlib.sha256(key.asbytes()).digest()).decode().rstrip("=")
    return f"{key.get_name()} SHA256:{digest}"


@contextmanager
def _transport(host: str, port: int):
    import paramiko
    sock = socket.create_connection((host, port), timeout=CONNECT_TIMEOUT)
    transport = paramiko.Transport(sock)
    transport.banner_timeout = CONNECT_TIMEOUT
    transport.handshake_timeout = CONNECT_TIMEOUT
    transport.auth_timeout = CONNECT_TIMEOUT
    try:
        transport.start_client(timeout=CONNECT_TIMEOUT)
        yield transport
    finally:
        transport.close()


def fetch_host_key(host: str, port: int) -> str:
    """The fingerprint of the key an SFTP server presents (first-use pinning)."""
    with _transport(host, port) as transport:
        return fingerprint(transport.get_remote_server_key())


@contextmanager
def _sftp(target: RemoteTarget):
    import paramiko
    with _transport(target.host, target.port) as transport:
        presented = fingerprint(transport.get_remote_server_key())
        if presented != target.host_key:
            raise HostKeyMismatch(target.host_key or "-", presented)
        transport.auth_password(target.username, target.password)
        sftp = paramiko.SFTPClient.from_transport(transport)
        sftp.get_channel().settimeout(IO_TIMEOUT)
        try:
            yield sftp
        finally:
            sftp.close()


@contextmanager
def _ftps(target: RemoteTarget):
    ftp = FTP_TLS(timeout=IO_TIMEOUT)
    try:
        ftp.connect(target.host, target.port, timeout=CONNECT_TIMEOUT)
        ftp.login(target.username, target.password)  # AUTH TLS first
        ftp.prot_p()                                 # data channel encrypted too
        if target.path and target.path != "/":
            ftp.cwd(target.path)
        yield ftp
    finally:
        try:
            ftp.quit()
        except Exception:
            ftp.close()


def _remote_file(target: RemoteTarget, filename: str) -> str:
    return posixpath.join(target.path or "/", filename)


def _session(target: RemoteTarget):
    if target.protocol == "sftp":
        return _sftp(target)
    if target.protocol == "ftps":
        return _ftps(target)
    raise ValueError(f"Protocollo remoto non supportato: {target.protocol}")


def upload(target: RemoteTarget, local_path: str) -> None:
    filename = posixpath.basename(local_path.replace("\\", "/"))
    with _session(target) as conn:
        if target.protocol == "sftp":
            conn.put(local_path, _remote_file(target, filename))
        else:
            with open(local_path, "rb") as f:
                conn.storbinary(f"STOR {filename}", f)
    logger.info(f"Uploaded {filename} via {target.protocol.upper()}")


def list_archives(target: RemoteTarget) -> List[dict]:
    files: List[dict] = []
    with _session(target) as conn:
        if target.protocol == "sftp":
            for entry in conn.listdir_attr(target.path or "/"):
                if is_archive_name(entry.filename):
                    files.append({
                        "filename": entry.filename,
                        "size_bytes": entry.st_size or 0,
                        "mtime": datetime.fromtimestamp(entry.st_mtime).isoformat() if entry.st_mtime else None,
                    })
        else:
            try:
                for name, facts in conn.mlsd(facts=["size", "modify"]):
                    if is_archive_name(name):
                        mtime = facts.get("modify")
                        files.append({
                            "filename": name,
                            "size_bytes": int(facts.get("size", 0)),
                            "mtime": datetime.strptime(mtime[:14], "%Y%m%d%H%M%S").isoformat() if mtime else None,
                        })
            except error_perm:
                # No MLSD: names only
                for name in conn.nlst():
                    if is_archive_name(name):
                        files.append({"filename": name, "size_bytes": 0, "mtime": None})
    return sorted(files, key=lambda f: f["filename"], reverse=True)


def download(target: RemoteTarget, filename: str, local_path: str) -> None:
    with _session(target) as conn:
        if target.protocol == "sftp":
            conn.get(_remote_file(target, filename), local_path)
        else:
            with open(local_path, "wb") as f:
                conn.retrbinary(f"RETR {filename}", f.write)


def delete(target: RemoteTarget, filename: str) -> None:
    with _session(target) as conn:
        if target.protocol == "sftp":
            conn.remove(_remote_file(target, filename))
        else:
            conn.delete(filename)
