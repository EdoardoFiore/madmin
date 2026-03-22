"""
MADMIN Token Blacklist

Hybrid in-memory + PostgreSQL revocation list for immediate JWT revocation.
The in-memory cache ensures zero-latency checks on every request.
The DB layer ensures revocations survive application restarts.

Call load_from_db(session) at startup to restore state from DB.
"""
import time
import threading
import logging
from datetime import datetime, timedelta
from typing import Dict
import uuid

from config import get_settings

logger = logging.getLogger(__name__)


class TokenBlacklist:
    """
    Hybrid user revocation list (in-memory cache + PostgreSQL).

    When a user is disabled or deleted, their user_id is added here.
    The get_current_user dependency checks this before the DB query
    for immediate invalidation that survives restarts.
    """

    def __init__(self):
        self._revoked: Dict[uuid.UUID, float] = {}  # user_id → revocation timestamp
        self._lock = threading.Lock()

    async def load_from_db(self, session) -> None:
        """
        Load active revocations from the database.
        Call once at application startup to restore state after a restart.
        """
        from sqlalchemy import select
        from .models import RevokedToken

        now = datetime.utcnow()
        result = await session.execute(
            select(RevokedToken).where(RevokedToken.expires_at > now)
        )
        records = result.scalars().all()

        with self._lock:
            for record in records:
                self._revoked[record.user_id] = record.revoked_at.timestamp()

        logger.info(f"Token blacklist: loaded {len(records)} revoked entries from DB")

    async def revoke_user(self, session, user_id: uuid.UUID) -> None:
        """
        Add a user to the revocation list (cache + DB).
        Called when a user is disabled or deleted.
        """
        now_ts = time.time()
        with self._lock:
            self._revoked[user_id] = now_ts
            logger.info(f"Token blacklist: revoked user {user_id}")

        # Persist to DB
        from sqlalchemy import delete
        from .models import RevokedToken

        revoked_at = datetime.utcnow()
        expires_at = revoked_at + timedelta(minutes=get_settings().access_token_expire_minutes)

        await session.execute(delete(RevokedToken).where(RevokedToken.user_id == user_id))
        session.add(RevokedToken(user_id=user_id, revoked_at=revoked_at, expires_at=expires_at))
        # Caller is responsible for committing the session

    async def unrevoke_user(self, session, user_id: uuid.UUID) -> None:
        """
        Remove a user from the revocation list (cache + DB).
        Called when a previously disabled user is re-enabled.
        """
        with self._lock:
            if user_id in self._revoked:
                del self._revoked[user_id]
                logger.info(f"Token blacklist: unrevoked user {user_id}")

        from sqlalchemy import delete
        from .models import RevokedToken

        await session.execute(delete(RevokedToken).where(RevokedToken.user_id == user_id))
        # Caller is responsible for committing the session

    def is_revoked(self, user_id: uuid.UUID) -> bool:
        """
        Check if a user's tokens have been revoked (in-memory only, zero-latency).
        Also cleans up expired entries opportunistically.
        """
        with self._lock:
            if user_id not in self._revoked:
                return False

            revoked_at = self._revoked[user_id]
            settings = get_settings()
            ttl_seconds = settings.access_token_expire_minutes * 60

            if time.time() - revoked_at > ttl_seconds:
                del self._revoked[user_id]
                return False

            return True

    async def cleanup_db(self, session) -> int:
        """
        Remove expired revocation records from the database.
        Returns number of entries removed.
        """
        from sqlalchemy import delete
        from .models import RevokedToken

        now = datetime.utcnow()
        result = await session.execute(
            delete(RevokedToken).where(RevokedToken.expires_at <= now)
        )
        removed = result.rowcount
        if removed:
            logger.debug(f"Token blacklist DB cleanup: removed {removed} expired entries")
        return removed


# Singleton
token_blacklist = TokenBlacklist()
