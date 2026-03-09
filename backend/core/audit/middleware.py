"""
MADMIN Audit Log Middleware

Starlette middleware that intercepts API requests and logs:
- Who (username from JWT)
- What (method + path)
- Result (status code + duration)
- Where from (client IP)

Logs are always written to Python logger (→ journalctl).
Non-excluded paths are also persisted to the audit_log database table.
"""
import time
import logging
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response
from jose import jwt, JWTError

from config import get_settings

logger = logging.getLogger("madmin.audit")

# JWT algorithm (same as core.auth.service)
ALGORITHM = "HS256"


def _extract_username(request: Request) -> str:
    """
    Extract username from JWT Bearer token without hitting the database.

    Returns 'anonymous' if no token or token is invalid.
    """
    auth_header = request.headers.get("authorization", "")
    if not auth_header.startswith("Bearer "):
        return "anonymous"

    token = auth_header[7:]  # Strip "Bearer "

    try:
        settings = get_settings()
        payload = jwt.decode(token, settings.secret_key, algorithms=[ALGORITHM])
        return payload.get("sub", "anonymous")
    except JWTError:
        return "anonymous"


def _get_client_ip(request: Request) -> str:
    """
    Get the real client IP from proxy headers.

    Nginx is configured to set X-Real-IP and X-Forwarded-For.
    """
    return (
        request.headers.get("x-real-ip")
        or request.headers.get("x-forwarded-for", "").split(",")[0].strip()
        or (request.client.host if request.client else "unknown")
    )
class AuditLogMiddleware(BaseHTTPMiddleware):
    """
    Middleware that logs API calls with user identity.

    - Always logs to Python logger (visible in journalctl)
    - Persists non-excluded paths to the audit_log DB table
    """

    async def dispatch(self, request: Request, call_next) -> Response:
        # Only intercept /api/ routes
        path = request.url.path
        if not path.startswith("/api/"):
            return await call_next(request)

        # Extract info before processing
        method = request.method
        username = _extract_username(request)
        client_ip = _get_client_ip(request)

        # Time the request
        start_time = time.time()
        response = await call_next(request)
        duration_ms = int((time.time() - start_time) * 1000)

        status_code = response.status_code

        from .service import is_excluded

        excluded = is_excluded(path, method)

        # Only log to Python logger and DB if not excluded
        if not excluded:
            logger.info(
                f"AUDIT | user={username} | {method} {path} | {status_code} | {duration_ms}ms | ip={client_ip}"
            )

            try:
                from core.database import async_session_maker
                from .models import AuditLog

                category = "read" if method == "GET" else "write"

                # Strip query params from stored path
                clean_path = path.split("?")[0]

                audit_entry = AuditLog(
                    username=username,
                    method=method,
                    path=clean_path,
                    status_code=status_code,
                    duration_ms=duration_ms,
                    client_ip=client_ip,
                    category=category,
                )

                async with async_session_maker() as session:
                    session.add(audit_entry)
                    await session.commit()

            except Exception as e:
                # Never let audit logging break the actual request
                logger.error(f"Failed to persist audit log: {e}")

        return response