"""
MADMIN Token Blacklist

In-memory blacklist for immediate JWT revocation when users
are disabled or deleted. Prevents revoked users from using
existing tokens until they naturally expire.

Entries auto-expire after the token TTL to avoid memory leaks.
"""
import time
import threading
import logging
from typing import Dict, Set
import uuid

from config import get_settings

logger = logging.getLogger(__name__)


class TokenBlacklist:
    """
    In-memory user revocation list.

    When a user is disabled or deleted, their user_id is added here.
    The get_current_user dependency checks this before the DB query
    for immediate invalidation.

    Entries auto-expire after the configured token TTL.
    """

    def __init__(self):
        self._revoked: Dict[uuid.UUID, float] = {}  # user_id → revocation timestamp
        self._lock = threading.Lock()

    def revoke_user(self, user_id: uuid.UUID) -> None:
        """
        Add a user to the revocation list.
        Called when a user is disabled or deleted.
        """
        with self._lock:
            self._revoked[user_id] = time.time()
            logger.info(f"Token blacklist: revoked user {user_id}")

    def unrevoke_user(self, user_id: uuid.UUID) -> None:
        """
        Remove a user from the revocation list.
        Called when a previously disabled user is re-enabled.
        """
        with self._lock:
            if user_id in self._revoked:
                del self._revoked[user_id]
                logger.info(f"Token blacklist: unrevoked user {user_id}")

    def is_revoked(self, user_id: uuid.UUID) -> bool:
        """
        Check if a user's tokens have been revoked.
        Also cleans up expired entries opportunistically.
        """
        with self._lock:
            if user_id not in self._revoked:
                return False

            revoked_at = self._revoked[user_id]
            settings = get_settings()
            ttl_seconds = settings.access_token_expire_minutes * 60

            # If the revocation is older than the token TTL,
            # the token has expired naturally — remove from blacklist
            if time.time() - revoked_at > ttl_seconds:
                del self._revoked[user_id]
                return False

            return True

    def cleanup(self) -> int:
        """
        Remove expired entries from the blacklist.
        Returns number of entries removed.
        """
        with self._lock:
            settings = get_settings()
            ttl_seconds = settings.access_token_expire_minutes * 60
            now = time.time()

            expired = [
                uid for uid, ts in self._revoked.items()
                if now - ts > ttl_seconds
            ]
            for uid in expired:
                del self._revoked[uid]

            if expired:
                logger.debug(f"Token blacklist cleanup: removed {len(expired)} expired entries")

            return len(expired)


# Singleton
token_blacklist = TokenBlacklist()
