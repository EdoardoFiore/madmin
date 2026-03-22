"""
MADMIN Login Rate Limiter

Hybrid in-memory + PostgreSQL rate limiter with incremental backoff for login attempts.
The in-memory cache ensures zero-latency checks; the DB layer survives restarts.

Backoff schedule:
- 5 failures  → 30 second block
- 3 more      → 2 minute block
- Each after  → 10 minute block

Counters reset on successful login.
"""
import time
import threading
import logging
from datetime import datetime, timedelta
from typing import Dict, Optional
from fastapi import HTTPException, status

logger = logging.getLogger(__name__)

# Backoff configuration
INITIAL_THRESHOLD = 5       # Failures before first block
SECOND_THRESHOLD = 3        # Additional failures before second block
BLOCK_DURATIONS = [30, 120, 600]  # seconds: 30s, 2min, 10min
CLEANUP_INTERVAL = 600      # Clean stale entries every 10 minutes
STALE_AFTER = 3600           # Remove entries inactive for 1 hour


class _IPRecord:
    """Track login attempts for a single IP."""
    __slots__ = ("attempts", "blocked_until", "block_count", "last_attempt")

    def __init__(self):
        self.attempts: int = 0
        self.blocked_until: float = 0.0
        self.block_count: int = 0
        self.last_attempt: float = time.time()


class LoginRateLimiter:
    """
    Hybrid in-memory + PostgreSQL rate limiter for login endpoint.

    Thread-safe via a simple lock. DB writes happen on record_failure/record_success.
    Call load_from_db(session) at startup to restore blocked IPs after a restart.
    """

    def __init__(self):
        self._records: Dict[str, _IPRecord] = {}
        self._lock = threading.Lock()
        self._last_cleanup = time.time()

    async def load_from_db(self, session) -> None:
        """
        Load currently-blocked IPs from the database.
        Call once at application startup to restore state after a restart.
        """
        from sqlalchemy import select
        from .models import LoginAttempt

        now = datetime.utcnow()
        result = await session.execute(
            select(LoginAttempt).where(LoginAttempt.blocked_until > now)
        )
        records = result.scalars().all()

        with self._lock:
            for record in records:
                rec = _IPRecord()
                rec.attempts = record.attempts
                rec.block_count = record.block_count
                rec.blocked_until = record.blocked_until.timestamp() if record.blocked_until else 0.0
                rec.last_attempt = record.last_attempt.timestamp()
                self._records[record.ip] = rec

        logger.info(f"Rate limiter: loaded {len(records)} blocked IPs from DB")

    def _cleanup_stale(self):
        """Remove entries that haven't been active for a while."""
        now = time.time()
        if now - self._last_cleanup < CLEANUP_INTERVAL:
            return
        self._last_cleanup = now
        stale_ips = [
            ip for ip, rec in self._records.items()
            if now - rec.last_attempt > STALE_AFTER and now > rec.blocked_until
        ]
        for ip in stale_ips:
            del self._records[ip]
        if stale_ips:
            logger.debug(f"Rate limiter cleanup: removed {len(stale_ips)} stale entries")

    def check_rate_limit(self, client_ip: str) -> None:
        """
        Check if the client IP is currently blocked (in-memory, zero-latency).

        Raises HTTPException(429) with Retry-After header if blocked.
        """
        with self._lock:
            self._cleanup_stale()
            rec = self._records.get(client_ip)
            if not rec:
                return

            now = time.time()
            if now < rec.blocked_until:
                remaining = int(rec.blocked_until - now) + 1
                logger.warning(
                    f"Rate limit: IP {client_ip} blocked for {remaining}s "
                    f"(block #{rec.block_count}, {rec.attempts} attempts)"
                )
                raise HTTPException(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    detail=f"Troppi tentativi. Riprova tra {remaining} secondi.",
                    headers={"Retry-After": str(remaining)},
                )

    async def record_failure(self, session, client_ip: str) -> None:
        """
        Record a failed login attempt (cache + DB).

        Applies incremental blocking based on consecutive failures.
        """
        with self._lock:
            if client_ip not in self._records:
                self._records[client_ip] = _IPRecord()

            rec = self._records[client_ip]
            rec.attempts += 1
            rec.last_attempt = time.time()

            should_block = False

            if rec.block_count == 0 and rec.attempts >= INITIAL_THRESHOLD:
                should_block = True
            elif rec.block_count == 1 and rec.attempts >= INITIAL_THRESHOLD + SECOND_THRESHOLD:
                should_block = True
            elif rec.block_count >= 2 and rec.attempts > INITIAL_THRESHOLD + SECOND_THRESHOLD + (rec.block_count - 2):
                should_block = True

            if should_block:
                duration_idx = min(rec.block_count, len(BLOCK_DURATIONS) - 1)
                duration = BLOCK_DURATIONS[duration_idx]
                rec.blocked_until = time.time() + duration
                rec.block_count += 1
                logger.warning(
                    f"Rate limit: IP {client_ip} blocked for {duration}s "
                    f"(block #{rec.block_count}, {rec.attempts} total attempts)"
                )

            # Capture for DB write
            attempts = rec.attempts
            block_count = rec.block_count
            blocked_until_dt = (
                datetime.utcfromtimestamp(rec.blocked_until)
                if rec.blocked_until > time.time() else None
            )

        # Persist to DB
        from .models import LoginAttempt

        existing = await session.get(LoginAttempt, client_ip)
        if existing:
            existing.attempts = attempts
            existing.block_count = block_count
            existing.blocked_until = blocked_until_dt
            existing.last_attempt = datetime.utcnow()
            session.add(existing)
        else:
            session.add(LoginAttempt(
                ip=client_ip,
                attempts=attempts,
                block_count=block_count,
                blocked_until=blocked_until_dt,
                last_attempt=datetime.utcnow()
            ))
        # Caller is responsible for committing the session

    async def record_success(self, session, client_ip: str) -> None:
        """
        Record a successful login. Resets all counters for this IP (cache + DB).
        """
        with self._lock:
            if client_ip in self._records:
                del self._records[client_ip]

        from sqlalchemy import delete
        from .models import LoginAttempt

        await session.execute(delete(LoginAttempt).where(LoginAttempt.ip == client_ip))
        # Caller is responsible for committing the session


# Singleton
login_rate_limiter = LoginRateLimiter()
