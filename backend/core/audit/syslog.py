"""
MADMIN Audit Syslog Forwarder

Forwards audit-log entries to an external syslog collector (SIEM, rsyslog,
Graylog, Splunk) in RFC 5424 format over UDP, TCP or TLS (RFC 5425).

Design:
- The middleware calls `syslog_forwarder.submit(...)` after persisting each
  AuditLog row. `submit()` is non-blocking: it applies the in-memory filter and
  enqueues into a bounded asyncio.Queue (drops on overflow). No network I/O runs
  on the request path.
- A single background task (`run()`, started from the lifespan) drains the queue
  and delivers each message, keeping a persistent connection for TCP/TLS and a
  datagram endpoint for UDP. Failures are isolated, logged and stored in
  `SyslogSettings.last_error`; they never surface to the request.

Config lives in the `syslog_settings` singleton row (id=1). `load_config()` reads
it at startup; `reload()` re-reads it after a PATCH and forces reconnection.
"""
import asyncio
import logging
import socket
import ssl
from datetime import datetime
from typing import Optional

logger = logging.getLogger("madmin.audit.syslog")

# Placeholder Private Enterprise Number for the structured-data SD-ID.
# TODO: replace 99999 with a registered IANA PEN if one is obtained.
SD_ID = "madmin@99999"

# Bounded queue: under a syslog outage messages are dropped rather than growing
# unbounded. 10k entries is generous for an admin panel's audit rate.
QUEUE_MAXSIZE = 10000

# Backoff (seconds) applied after a delivery failure to avoid hammering an
# unreachable collector while still draining the queue.
_FAIL_BACKOFF = 5.0


def _severity(status_code: int) -> int:
    """Map an HTTP status code to a syslog severity (RFC 5424 numeric)."""
    if status_code >= 500:
        return 3   # err
    if status_code >= 400:
        return 4   # warning
    return 6       # info


def _sd_escape(value: str) -> str:
    """Escape a structured-data param value per RFC 5424 §6.3.3."""
    return value.replace('\\', '\\\\').replace('"', '\\"').replace(']', '\\]')


def format_rfc5424(
    *,
    facility: int,
    app_name: str,
    hostname: str,
    timestamp: datetime,
    username: str,
    method: str,
    path: str,
    status_code: int,
    duration_ms: int,
    client_ip: str,
    category: str,
) -> bytes:
    """
    Build an RFC 5424 syslog frame (without transport framing) as UTF-8 bytes.

    Layout: <PRI>1 TIMESTAMP HOSTNAME APP-NAME PROCID MSGID [SD] MSG
    PROCID is NILVALUE ('-'); MSGID is 'AUDIT'.
    """
    pri = facility * 8 + _severity(status_code)
    ts = timestamp.strftime("%Y-%m-%dT%H:%M:%S.%fZ")  # UTC (audit ts is utcnow)
    host = (hostname or "-").replace(" ", "_")[:255] or "-"
    app = (app_name or "madmin").replace(" ", "_")[:48] or "madmin"

    sd = (
        f'[{SD_ID} user="{_sd_escape(username)}" method="{_sd_escape(method)}" '
        f'path="{_sd_escape(path)}" status="{status_code}" '
        f'ip="{_sd_escape(client_ip)}" dur="{duration_ms}" '
        f'cat="{_sd_escape(category)}"]'
    )
    msg = f'{method} {path} -> {status_code}'
    frame = f'<{pri}>1 {ts} {host} {app} - AUDIT {sd} {msg}'
    return frame.encode("utf-8")


class SyslogForwarder:
    """Singleton syslog forwarder. Instantiate once as `syslog_forwarder`."""

    def __init__(self) -> None:
        self._queue: asyncio.Queue = asyncio.Queue(maxsize=QUEUE_MAXSIZE)
        self._cfg: dict = self._defaults()
        self._hostname: str = socket.gethostname()
        self._dropped: int = 0
        self._stopped: bool = False
        self._dirty: bool = False  # config changed -> reconnect on next drain

        # Persistent connections held by the drain loop only.
        self._writer: Optional[asyncio.StreamWriter] = None       # tcp/tls
        self._udp_transport: Optional[asyncio.BaseTransport] = None
        self._ssl_ctx: Optional[ssl.SSLContext] = None

    @staticmethod
    def _defaults() -> dict:
        return {
            "enabled": False, "host": "", "port": 514, "protocol": "udp",
            "facility": 16, "app_name": "madmin", "forward_reads": False,
            "min_status": 0, "tls_ca_cert": None, "tls_verify": True,
        }

    # --- Config -----------------------------------------------------------

    async def load_config(self) -> None:
        """Read the SyslogSettings singleton into the in-memory cache."""
        try:
            from core.database import async_session_maker
            from core.settings.models import SyslogSettings
            from sqlalchemy import select

            async with async_session_maker() as session:
                res = await session.execute(
                    select(SyslogSettings).where(SyslogSettings.id == 1)
                )
                row = res.scalar_one_or_none()
                if row is not None:
                    self._cfg = {
                        "enabled": row.enabled, "host": row.host, "port": row.port,
                        "protocol": row.protocol, "facility": row.facility,
                        "app_name": row.app_name, "forward_reads": row.forward_reads,
                        "min_status": row.min_status, "tls_ca_cert": row.tls_ca_cert,
                        "tls_verify": row.tls_verify,
                    }
                else:
                    self._cfg = self._defaults()
        except Exception as e:
            logger.error(f"Syslog load_config failed: {e}")
            self._cfg = self._defaults()

    async def reload(self) -> None:
        """Re-read config and force the drain loop to reconnect."""
        await self.load_config()
        self._dirty = True

    # --- Enqueue (called from the request path, must not block) -----------

    def _should_forward(self, category: str, status_code: int) -> bool:
        cfg = self._cfg
        if not cfg.get("enabled") or not cfg.get("host"):
            return False
        if category == "read" and not cfg.get("forward_reads"):
            return False
        if status_code < int(cfg.get("min_status") or 0):
            return False
        return True

    def submit(
        self,
        *,
        timestamp: datetime,
        username: str,
        method: str,
        path: str,
        status_code: int,
        duration_ms: int,
        client_ip: str,
        category: str,
    ) -> None:
        """Non-blocking enqueue. Applies the filter; drops on queue overflow."""
        if not self._should_forward(category, status_code):
            return
        item = {
            "timestamp": timestamp, "username": username, "method": method,
            "path": path, "status_code": status_code, "duration_ms": duration_ms,
            "client_ip": client_ip, "category": category,
        }
        try:
            self._queue.put_nowait(item)
        except asyncio.QueueFull:
            self._dropped += 1
            if self._dropped % 100 == 1:
                logger.debug(f"Syslog queue full, dropped {self._dropped} entries")

    # --- Delivery ---------------------------------------------------------

    def _build_ssl_context(self) -> ssl.SSLContext:
        ctx = ssl.create_default_context()
        ca = self._cfg.get("tls_ca_cert")
        if ca:
            ctx.load_verify_locations(cadata=ca)
        if not self._cfg.get("tls_verify", True):
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
        return ctx

    def _format(self, item: dict) -> bytes:
        return format_rfc5424(
            facility=int(self._cfg.get("facility", 16)),
            app_name=self._cfg.get("app_name", "madmin"),
            hostname=self._hostname,
            **item,
        )

    async def _close_connections(self) -> None:
        if self._writer is not None:
            try:
                self._writer.close()
            except Exception:
                pass
            self._writer = None
        if self._udp_transport is not None:
            try:
                self._udp_transport.close()
            except Exception:
                pass
            self._udp_transport = None

    async def _ensure_udp(self) -> None:
        if self._udp_transport is not None:
            return
        loop = asyncio.get_running_loop()
        transport, _ = await loop.create_datagram_endpoint(
            asyncio.DatagramProtocol,
            remote_addr=(self._cfg["host"], int(self._cfg["port"])),
        )
        self._udp_transport = transport

    async def _ensure_stream(self) -> None:
        if self._writer is not None and not self._writer.is_closing():
            return
        proto = self._cfg["protocol"]
        ssl_arg = self._build_ssl_context() if proto == "tls" else None
        _, writer = await asyncio.open_connection(
            self._cfg["host"], int(self._cfg["port"]), ssl=ssl_arg,
        )
        self._writer = writer

    async def _deliver(self, payload: bytes) -> None:
        """Send one framed message over the persistent connection."""
        proto = self._cfg["protocol"]
        if proto == "udp":
            await self._ensure_udp()
            self._udp_transport.sendto(payload)  # type: ignore[union-attr]
        else:
            # TCP / TLS: octet-counting framing (RFC 5425 / RFC 6587 §3.4.1).
            await self._ensure_stream()
            framed = f"{len(payload)} ".encode("ascii") + payload
            self._writer.write(framed)          # type: ignore[union-attr]
            await self._writer.drain()          # type: ignore[union-attr]

    async def _record_error(self, message: str) -> None:
        """Persist the last delivery error (best-effort)."""
        try:
            from core.database import async_session_maker
            from core.settings.models import SyslogSettings
            from sqlalchemy import select

            async with async_session_maker() as session:
                res = await session.execute(
                    select(SyslogSettings).where(SyslogSettings.id == 1)
                )
                row = res.scalar_one_or_none()
                if row is not None:
                    row.last_error = message[:500]
                    session.add(row)
                    await session.commit()
        except Exception:
            pass

    async def _record_sent(self) -> None:
        try:
            from core.database import async_session_maker
            from core.settings.models import SyslogSettings
            from sqlalchemy import select

            async with async_session_maker() as session:
                res = await session.execute(
                    select(SyslogSettings).where(SyslogSettings.id == 1)
                )
                row = res.scalar_one_or_none()
                if row is not None and row.last_error is not None:
                    row.last_error = None
                    row.last_sent_at = datetime.utcnow()
                    session.add(row)
                    await session.commit()
        except Exception:
            pass

    # --- Background drain loop -------------------------------------------

    async def run(self) -> None:
        """Drain the queue and deliver messages. Runs until cancelled."""
        logger.info("Syslog forwarder task started")
        try:
            while not self._stopped:
                item = await self._queue.get()
                try:
                    if self._dirty:
                        await self._close_connections()
                        self._dirty = False
                    if not self._cfg.get("enabled") or not self._cfg.get("host"):
                        continue
                    await self._deliver(self._format(item))
                    await self._record_sent()
                except asyncio.CancelledError:
                    raise
                except Exception as e:
                    logger.warning(f"Syslog delivery failed: {e}")
                    await self._close_connections()
                    await self._record_error(str(e))
                    await asyncio.sleep(_FAIL_BACKOFF)
                finally:
                    self._queue.task_done()
        except asyncio.CancelledError:
            pass
        finally:
            await self._close_connections()
            logger.info("Syslog forwarder task stopped")

    async def stop(self) -> None:
        self._stopped = True
        await self._close_connections()

    # --- One-shot test send (bypasses queue/persistent conn) --------------

    async def test_send(self) -> dict:
        """
        Send a one-off test message using the current config, opening and
        closing a fresh connection. Returns {"success": bool, "error": str|None}.
        """
        await self.load_config()
        if not self._cfg.get("host"):
            return {"success": False, "error": "Host non configurato"}

        payload = format_rfc5424(
            facility=int(self._cfg.get("facility", 16)),
            app_name=self._cfg.get("app_name", "madmin"),
            hostname=self._hostname,
            timestamp=datetime.utcnow(),
            username="madmin", method="TEST", path="/api/settings/syslog/test",
            status_code=200, duration_ms=0, client_ip="127.0.0.1", category="test",
        )
        proto = self._cfg["protocol"]
        host, port = self._cfg["host"], int(self._cfg["port"])
        try:
            if proto == "udp":
                loop = asyncio.get_running_loop()
                transport, _ = await loop.create_datagram_endpoint(
                    asyncio.DatagramProtocol, remote_addr=(host, port),
                )
                try:
                    transport.sendto(payload)
                finally:
                    transport.close()
            else:
                ssl_arg = self._build_ssl_context() if proto == "tls" else None
                fut = asyncio.open_connection(host, port, ssl=ssl_arg)
                _, writer = await asyncio.wait_for(fut, timeout=10)
                try:
                    framed = f"{len(payload)} ".encode("ascii") + payload
                    writer.write(framed)
                    await writer.drain()
                finally:
                    writer.close()
                    try:
                        await writer.wait_closed()
                    except Exception:
                        pass
            await self._record_sent()
            return {"success": True, "error": None}
        except Exception as e:
            await self._record_error(str(e))
            return {"success": False, "error": str(e)}


# Module-level singleton (import this).
syslog_forwarder = SyslogForwarder()
