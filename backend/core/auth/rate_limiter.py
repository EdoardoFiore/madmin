"""
MADMIN Login Rate Limiter

In-memory rate limiter with incremental backoff for login attempts.
Tracks attempts per client IP to prevent brute-force attacks.

Backoff schedule:
- 5 failures  → 30 second block
- 3 more      → 2 minute block
- Each after  → 10 minute block

Counters reset on successful login.
"""
import time
import threading
import logging
from typing import Dict
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
    In-memory rate limiter for login endpoint.

    Thread-safe via a simple lock.
    """

    def __init__(self):
        self._records: Dict[str, _IPRecord] = {}
        self._lock = threading.Lock()
        self._last_cleanup = time.time()

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
        Check if the client IP is currently blocked.

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

    def record_failure(self, client_ip: str) -> None:
        """
        Record a failed login attempt.
        
        Applies incremental blocking based on consecutive failures.
        """
        with self._lock:
            if client_ip not in self._records:
                self._records[client_ip] = _IPRecord()
            
            rec = self._records[client_ip]
            rec.attempts += 1
            rec.last_attempt = time.time()

            # Determine if a block should be applied
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

    def record_success(self, client_ip: str) -> None:
        """
        Record a successful login. Resets all counters for this IP.
        """
        with self._lock:
            if client_ip in self._records:
                del self._records[client_ip]


# Singleton
login_rate_limiter = LoginRateLimiter()
