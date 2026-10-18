"""
MADMIN traffic capture (tcpdump)

Live packet capture for troubleshooting from the panel. One tcpdump process
per capture writes the pcap and prints the packets at the same time
(`-w <file> --print`, tcpdump >= 4.99): the lines are streamed to the browser,
the file can be downloaded for Wireshark once the capture ends.

Bounded on every side: duration, packet count, pcap size, lines per second
sent to the browser (the rest is counted as dropped, the pcap keeps it all),
captures running at once. The process is stopped when the stream ends (the
browser left), on an explicit stop, by the limits, and at shutdown.

The streamed lines go back over HTTPS: capturing the management interface
would capture its own stream, so the panel's own connection is excluded by
default.
"""
import asyncio
import ipaddress
import logging
import os
import re
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import AsyncIterator, Dict, List, Optional

from pydantic import BaseModel, field_validator

from config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

DEFAULT_DURATION = 60
MAX_DURATION = 600
DEFAULT_PACKETS = 1000
MAX_PACKETS = 100_000
MAX_PCAP_BYTES = 50 * 1024 * 1024
LINES_PER_SECOND = 200          # sent to the browser; the pcap keeps everything
MAX_LINE_CHARS = 2000
MAX_RUNNING = 3                 # captures at once, one per user
PCAP_TTL = 1800                 # an ended capture's pcap stays downloadable this long
HEARTBEAT = 15                  # under nginx's proxy_read_timeout (300s)
BATCH_INTERVAL = 0.2

_IFACE_RE = re.compile(r"^[A-Za-z0-9._@-]{1,15}$")
# Free-form BPF (advanced): the expression grammar only, no quotes, no `;`,
# no backslash. tcpdump gets it as one argument after `--`, without a shell.
_BPF_RE = re.compile(r"^[A-Za-z0-9 .:/()!&|<>=\[\]-]{1,500}$")
PROTOCOLS = ("tcp", "udp", "icmp", "arp")


class CaptureError(Exception):
    """A capture that cannot start (bad filter, too many running)."""


class CaptureBusy(CaptureError):
    pass


def capture_dir() -> Path:
    return Path(settings.data_dir) / "captures"


def list_interfaces() -> List[str]:
    """Every interface the kernel has (VPN tunnels included), plus "any"."""
    try:
        names = sorted(os.listdir("/sys/class/net"))
    except OSError:
        names = []
    return ["any"] + [n for n in names if _IFACE_RE.match(n)]


class CaptureSpec(BaseModel):
    interface: str = "any"
    protocol: Optional[str] = None
    host: Optional[str] = None
    src: Optional[str] = None
    dst: Optional[str] = None
    net: Optional[str] = None
    port: Optional[int] = None
    bpf: Optional[str] = None
    duration: int = DEFAULT_DURATION
    max_packets: int = DEFAULT_PACKETS
    snaplen: int = 0                # 0 = whole packet
    link_level: bool = False        # -e: MAC addresses
    verbose: bool = False           # -v
    exclude_panel: bool = True

    @field_validator("interface")
    @classmethod
    def _iface(cls, v):
        if v != "any" and not _IFACE_RE.match(v or ""):
            raise ValueError("Interfaccia non valida")
        return v

    @field_validator("protocol")
    @classmethod
    def _proto(cls, v):
        if v in (None, ""):
            return None
        if v not in PROTOCOLS:
            raise ValueError("Protocollo non valido")
        return v

    @field_validator("host", "src", "dst")
    @classmethod
    def _ip(cls, v):
        if v in (None, ""):
            return None
        try:
            return str(ipaddress.IPv4Address(v.strip()))
        except ValueError:
            raise ValueError(f"Indirizzo IPv4 non valido: {v}")

    @field_validator("net")
    @classmethod
    def _net(cls, v):
        if v in (None, ""):
            return None
        try:
            return str(ipaddress.IPv4Network(v.strip(), strict=False))
        except ValueError:
            raise ValueError(f"Rete non valida: {v}")

    @field_validator("port")
    @classmethod
    def _port(cls, v):
        if v is not None and not 1 <= v <= 65535:
            raise ValueError("Porta non valida")
        return v

    @field_validator("bpf")
    @classmethod
    def _bpf(cls, v):
        if v is None or not v.strip():
            return None
        v = " ".join(v.split())
        if not _BPF_RE.match(v):
            raise ValueError("Il filtro contiene caratteri non ammessi")
        return v

    @field_validator("duration")
    @classmethod
    def _duration(cls, v):
        if not 1 <= v <= MAX_DURATION:
            raise ValueError(f"Durata tra 1 e {MAX_DURATION} secondi")
        return v

    @field_validator("max_packets")
    @classmethod
    def _packets(cls, v):
        if not 1 <= v <= MAX_PACKETS:
            raise ValueError(f"Pacchetti tra 1 e {MAX_PACKETS}")
        return v

    @field_validator("snaplen")
    @classmethod
    def _snaplen(cls, v):
        if v != 0 and not 64 <= v <= 262144:
            raise ValueError("Snaplen: 0 (intero pacchetto) oppure tra 64 e 262144")
        return v


def build_filter(spec: CaptureSpec, panel_port: Optional[int], client_ip: Optional[str]) -> str:
    """The BPF expression for a capture ("" = everything)."""
    if spec.port is not None and spec.protocol in ("icmp", "arp"):
        raise CaptureError("La porta non si applica a ICMP o ARP")
    parts: List[str] = []
    if spec.protocol:
        parts.append(spec.protocol)
    if spec.host:
        parts.append(f"host {spec.host}")
    if spec.src:
        parts.append(f"src host {spec.src}")
    if spec.dst:
        parts.append(f"dst host {spec.dst}")
    if spec.net:
        parts.append(f"net {spec.net}")
    if spec.port is not None:
        parts.append(f"port {spec.port}")
    if spec.bpf:
        parts.append(f"({spec.bpf})")
    if spec.exclude_panel and panel_port and client_ip:
        try:
            ipaddress.IPv4Address(client_ip)
            parts.append(f"not (tcp port {int(panel_port)} and host {client_ip})")
        except ValueError:
            pass
    return " and ".join(parts)


async def validate_filter(interface: str, expr: str) -> None:
    """Compile the expression with tcpdump -d (nothing captured); CaptureError with its message."""
    if settings.mock_iptables or not expr:
        return
    try:
        proc = await asyncio.create_subprocess_exec(
            "tcpdump", "-d", "-i", interface, "--", expr,
            stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE,
        )
        _, err = await asyncio.wait_for(proc.communicate(), timeout=10)
    except FileNotFoundError:
        raise CaptureError("tcpdump non è installato (apt install tcpdump)")
    except asyncio.TimeoutError:
        raise CaptureError("Verifica del filtro scaduta")
    if proc.returncode != 0:
        raise CaptureError(_tcpdump_message(err))


def _tcpdump_message(stderr: bytes) -> str:
    lines = [l.strip() for l in stderr.decode(errors="replace").splitlines() if l.strip()]
    msg = lines[-1] if lines else "errore sconosciuto"
    return "tcpdump: " + msg.removeprefix("tcpdump: ")


@dataclass
class CaptureSession:
    id: str
    owner_id: str
    owner: str
    interface: str
    expr: str
    spec: CaptureSpec
    started: float = field(default_factory=time.monotonic)
    started_at: float = field(default_factory=time.time)
    proc: Optional[asyncio.subprocess.Process] = None
    running: bool = True
    stop_reason: Optional[str] = None
    end_reason: Optional[str] = None
    ended_at: Optional[float] = None
    packets: int = 0
    dropped: int = 0
    error: Optional[str] = None

    @property
    def pcap_path(self) -> Path:
        return capture_dir() / f"{self.id}.pcap"

    def pcap_size(self) -> int:
        try:
            return self.pcap_path.stat().st_size
        except OSError:
            return 0

    def has_pcap(self) -> bool:
        # 24 bytes = the pcap header alone (no packet)
        return self.pcap_size() > 24


_sessions: Dict[str, CaptureSession] = {}
_start_lock = asyncio.Lock()


def get_session(capture_id: str) -> Optional[CaptureSession]:
    return _sessions.get(capture_id)


async def start(spec: CaptureSpec, expr: str, owner_id: str, owner: str) -> CaptureSession:
    """Start tcpdump; a running capture of the same user is stopped first."""
    async with _start_lock:
        cleanup_expired()
        for sess in list(_sessions.values()):
            if sess.running and sess.owner_id == owner_id:
                await stop(sess, "replaced")
        if sum(1 for s in _sessions.values() if s.running) >= MAX_RUNNING:
            raise CaptureBusy(f"Già {MAX_RUNNING} catture in corso: riprovare più tardi")

        sess = CaptureSession(id=uuid.uuid4().hex, owner_id=owner_id, owner=owner,
                              interface=spec.interface, expr=expr, spec=spec)
        if not settings.mock_iptables:
            capture_dir().mkdir(parents=True, exist_ok=True, mode=0o700)
            cmd = ["tcpdump", "-i", spec.interface, "-nn", "-l", "-U",
                   "-s", str(spec.snaplen), "-c", str(spec.max_packets),
                   # without -Z tcpdump drops to the tcpdump user before creating
                   # the file; the .pcap name is what AppArmor's profile allows
                   "-Z", "root", "-w", str(sess.pcap_path), "--print"]
            if spec.link_level:
                cmd.append("-e")
            if spec.verbose:
                cmd.append("-v")
            if expr:
                cmd += ["--", expr]
            try:
                sess.proc = await asyncio.create_subprocess_exec(
                    *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
                    stdin=asyncio.subprocess.DEVNULL, limit=1 << 20,
                )
            except FileNotFoundError:
                raise CaptureError("tcpdump non è installato (apt install tcpdump)")
        _sessions[sess.id] = sess
        logger.info(f"Capture {sess.id} started by {owner} on {spec.interface}: {expr or '(all)'}")
        return sess


async def stop(sess: CaptureSession, reason: str) -> None:
    """Ask the capture to stop: tcpdump gets SIGTERM, flushes the pcap and exits."""
    if not sess.running:
        return
    sess.stop_reason = sess.stop_reason or reason
    await _terminate(sess)


async def _terminate(sess: CaptureSession) -> None:
    proc = sess.proc
    if proc is None or proc.returncode is not None:
        return
    try:
        proc.terminate()
        await asyncio.wait_for(proc.wait(), timeout=3)
    except ProcessLookupError:
        pass
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()


def _finish(sess: CaptureSession, reason: str) -> None:
    sess.running = False
    sess.end_reason = reason
    sess.ended_at = time.time()
    logger.info(f"Capture {sess.id} ended ({reason}): {sess.packets} packets, {sess.dropped} not shown")


async def events(sess: CaptureSession) -> AsyncIterator[dict]:
    """
    The capture as stream events: start, pkt (line batches), stats, hb, end.
    Whatever ends the stream (limits, stop, the browser leaving: the generator
    is then cancelled), the process is stopped in the finally.
    """
    reason = "error"
    try:
        yield {"t": "start", "id": sess.id, "interface": sess.interface, "filter": sess.expr,
               "duration": sess.spec.duration, "max_packets": sess.spec.max_packets}
        if sess.proc is None:
            async for ev in _mock_events(sess):
                yield ev
            reason = sess.stop_reason or "duration"
        else:
            reason = None
            async for ev in _process_events(sess):
                if ev.get("t") == "_reason":
                    reason = ev["reason"]
                else:
                    yield ev
    finally:
        await _terminate(sess)
        if reason is None:
            reason = sess.stop_reason or "client"
        _finish(sess, reason)
    yield {"t": "end", "reason": reason, "packets": sess.packets, "dropped": sess.dropped,
           "pcap": sess.has_pcap(), "error": sess.error}


async def _process_events(sess: CaptureSession) -> AsyncIterator[dict]:
    proc = sess.proc
    deadline = sess.started + sess.spec.duration
    batch: List[str] = []
    last_flush = last_stats = last_sent = time.monotonic()
    window, window_count = int(time.monotonic()), 0

    def stats():
        return {"t": "stats", "packets": sess.packets, "dropped": sess.dropped,
                "bytes": sess.pcap_size(), "elapsed": round(time.monotonic() - sess.started)}

    while True:
        try:
            raw = await asyncio.wait_for(proc.stdout.readline(), timeout=BATCH_INTERVAL)
        except asyncio.TimeoutError:
            raw = None
        now = time.monotonic()
        if raw == b"":
            # tcpdump exited: packet count reached, stopped, or an error
            await proc.wait()
            if sess.stop_reason:
                reason = sess.stop_reason
            elif proc.returncode == 0:
                reason = "count"
            else:
                reason = "error"
                sess.error = _tcpdump_message(await proc.stderr.read())
            if batch:
                yield {"t": "pkt", "lines": batch}
            yield stats()
            yield {"t": "_reason", "reason": reason}
            return
        if raw:
            line = raw.decode(errors="replace").rstrip("\n")[:MAX_LINE_CHARS]
            # -v continuation lines start with whitespace: one packet, several lines
            if line and not line[0].isspace():
                sess.packets += 1
            if int(now) != window:
                window, window_count = int(now), 0
            if window_count < LINES_PER_SECOND:
                batch.append(line)
                window_count += 1
            elif line and not line[0].isspace():
                sess.dropped += 1
        if batch and now - last_flush >= BATCH_INTERVAL:
            yield {"t": "pkt", "lines": batch}
            batch, last_flush, last_sent = [], now, now
        if now - last_stats >= 1:
            yield stats()
            last_stats = last_sent = now
            if sess.pcap_size() >= MAX_PCAP_BYTES:
                sess.stop_reason = sess.stop_reason or "size"
                await _terminate(sess)
        if now >= deadline and not sess.stop_reason:
            sess.stop_reason = "duration"
            await _terminate(sess)
        if now - last_sent >= HEARTBEAT:
            yield {"t": "hb"}
            last_sent = now


async def _mock_events(sess: CaptureSession) -> AsyncIterator[dict]:
    """MOCK_IPTABLES: fake packets, so the panel can be tried without root."""
    deadline = sess.started + sess.spec.duration
    n = 0
    while time.monotonic() < deadline and not sess.stop_reason and n < sess.spec.max_packets:
        await asyncio.sleep(0.5)
        n += 1
        sess.packets = n
        ts = time.strftime("%H:%M:%S")
        yield {"t": "pkt", "lines": [
            f"{ts}.{n:06d} IP 192.168.1.{10 + n % 5}.{40000 + n} > 1.1.1.1.443: Flags [P.], seq {n}, length 64"]}
        yield {"t": "stats", "packets": n, "dropped": 0, "bytes": 0,
               "elapsed": round(time.monotonic() - sess.started)}
    if n >= sess.spec.max_packets:
        sess.stop_reason = sess.stop_reason or "count"


def cleanup_expired() -> None:
    """Forget ended captures older than PCAP_TTL and remove their pcap."""
    now = time.time()
    for sid, sess in list(_sessions.items()):
        if not sess.running and sess.ended_at and now - sess.ended_at > PCAP_TTL:
            _sessions.pop(sid, None)
            try:
                sess.pcap_path.unlink(missing_ok=True)
            except OSError:
                pass


def purge_dir() -> None:
    """At startup: no capture survives a restart, nor its file."""
    d = capture_dir()
    if not d.is_dir():
        return
    for f in d.glob("*.pcap"):
        try:
            f.unlink()
        except OSError:
            pass


async def stop_all() -> None:
    """At shutdown."""
    for sess in list(_sessions.values()):
        if sess.running:
            await stop(sess, "shutdown")
