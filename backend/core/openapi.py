"""
MADMIN OpenAPI Configuration

Centralizes OpenAPI/Swagger metadata:
- Tag definitions with descriptions
- Custom schema generation with JWT security
- Common error response definitions
"""
from fastapi import FastAPI
from fastapi.openapi.utils import get_openapi


# ── Core API Tags (order matters for Swagger UI) ──────────────────────

CORE_TAGS = [
    {
        "name": "Authentication",
        "description": "User authentication, JWT tokens, 2FA/TOTP, user management and RBAC permissions.",
    },
    {
        "name": "System",
        "description": "Server statistics (CPU, RAM, disk, network), uptime, alerts and system health monitoring.",
    },
    {
        "name": "Firewall",
        "description": "Host iptables rules management, module chains orchestration and rule ordering.",
    },
    {
        "name": "Network",
        "description": "Network interface configuration via Netplan, IP addressing and routing.",
    },
    {
        "name": "Services",
        "description": "Systemd service control — start, stop, restart, enable/disable and status monitoring.",
    },
    {
        "name": "Cron",
        "description": "Crontab management — create, edit, toggle and delete scheduled tasks.",
    },
    {
        "name": "Files",
        "description": "File upload and download operations for data management.",
    },
    {
        "name": "Backup",
        "description": "Configuration export/import, scheduled backups (local and remote), restore operations.",
    },
    {
        "name": "Settings",
        "description": "System settings, SMTP configuration, backup scheduling, certificates and UI preferences.",
    },
    {
        "name": "Audit Logs",
        "description": "API call audit trail — searchable logs with user identity, IP, method and response codes.",
    },
    {
        "name": "Modules",
        "description": "Dynamic module lifecycle — discovery, activation, deactivation, dependency management and chain priority.",
    },
]


# ── Common Error Responses ─────────────────────────────────────────────

COMMON_RESPONSES = {
    401: {
        "description": "Not authenticated — missing or invalid JWT token",
        "content": {
            "application/json": {
                "example": {"detail": "Not authenticated"}
            }
        },
    },
    403: {
        "description": "Permission denied — insufficient RBAC permissions",
        "content": {
            "application/json": {
                "example": {"detail": "Permission denied"}
            }
        },
    },
    404: {
        "description": "Resource not found",
        "content": {
            "application/json": {
                "example": {"detail": "Not found"}
            }
        },
    },
    422: {
        "description": "Validation error — request body or parameters failed validation",
    },
    500: {
        "description": "Internal server error",
        "content": {
            "application/json": {
                "example": {"detail": "Internal server error"}
            }
        },
    },
}

# Subset for authenticated endpoints (most common)
AUTH_RESPONSES = {k: v for k, v in COMMON_RESPONSES.items() if k in (401, 403)}

# Public endpoints only need 422/500
PUBLIC_RESPONSES = {k: v for k, v in COMMON_RESPONSES.items() if k in (422, 500)}


# ── Paths excluded from global JWT security requirement ────────────────

_PUBLIC_PATH_FRAGMENTS = ("/auth/token", "/health", "/auth/init", "/docs", "/redoc", "/openapi.json")


def setup_openapi(app: FastAPI) -> None:
    """
    Override app.openapi() to inject:
    - JWT Bearer security scheme
    - Global security requirement (except public paths)
    - Sorted tags (core first, then modules alphabetically)
    """
    def custom_openapi():
        if app.openapi_schema:
            return app.openapi_schema

        schema = get_openapi(
            title=app.title,
            version=app.version,
            description=app.description,
            routes=app.routes,
            tags=app.openapi_tags,
        )

        # Inject security scheme
        schema.setdefault("components", {})
        schema["components"]["securitySchemes"] = {
            "BearerAuth": {
                "type": "http",
                "scheme": "bearer",
                "bearerFormat": "JWT",
                "description": "Enter your JWT token obtained from POST /api/auth/token",
            }
        }

        # Apply security globally except to public paths
        for path, methods in schema.get("paths", {}).items():
            if any(frag in path for frag in _PUBLIC_PATH_FRAGMENTS):
                continue
            for method_detail in methods.values():
                if isinstance(method_detail, dict) and "summary" in method_detail:
                    method_detail.setdefault("security", [{"BearerAuth": []}])

        app.openapi_schema = schema
        return schema

    app.openapi = custom_openapi
