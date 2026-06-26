"""
MADMIN - Modular Admin System

Main FastAPI application entry point.
Handles:
- Application initialization
- Router registration
- Database setup
- Module loading
- Startup/shutdown events
"""
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI, Depends, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware
from config import MADMIN_VERSION
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
import os

from config import get_settings

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Application lifespan handler.
    Runs on startup and shutdown.
    """
    logger.info("MADMIN starting up...")
    
    # Import here to avoid circular imports
    from core.database import init_db, async_session_maker
    from core.auth.service import init_core_permissions
    from core.auth.token_blacklist import token_blacklist
    from core.auth.rate_limiter import login_rate_limiter
    from core.firewall.orchestrator import firewall_orchestrator
    from core.modules.loader import module_loader

    # Initialize database
    logger.info("Initializing database...")
    await init_db()

    # Initialize core permissions
    async with async_session_maker() as session:
        await init_core_permissions(session)

    # Restore security state from DB (survives restarts)
    logger.info("Restoring token blacklist and rate limiter state from DB...")
    async with async_session_maker() as session:
        await token_blacklist.load_from_db(session)
        await login_rate_limiter.load_from_db(session)
    
    # Initialize firewall chains
    logger.info("Initializing firewall chains...")
    await firewall_orchestrator.initialize()

    # Managed LAN reconcile (self-heal) — MUST run before load_all_modules so the
    # DHCP module (if activated here) gets its router mounted in this same boot.
    from core.provisioning.service import provisioning_service
    async with async_session_maker() as session:
        try:
            await provisioning_service.reconcile(session)
            await session.commit()
        except Exception as e:
            logger.error(f"Managed LAN reconcile failed on startup: {e}", exc_info=True)

    # Load installed modules
    logger.info("Loading modules...")
    async with async_session_maker() as session:
        await module_loader.load_all_modules(app, session)
        await session.commit()
    
    # One-shot migration (idempotent): convert legacy inline geo:<cc> rule tokens
    # into geo address objects + rule references, so the uniform address-object
    # path fully replaces the old inline geo path.
    async with async_session_maker() as session:
        try:
            import re as _geo_re_mod
            from core.firewall.models import (
                MachineFirewallRule, AddressObject, FirewallRuleAddress,
            )
            from core.firewall import addresses as fw_addresses
            geo_re = _geo_re_mod.compile(r'^geo:([a-z]{2})$', _geo_re_mod.IGNORECASE)
            migrated = 0
            rows = (await session.execute(select(MachineFirewallRule))).scalars().all()
            for rule in rows:
                for direction in ("source", "destination"):
                    m = geo_re.match(getattr(rule, direction) or "")
                    if not m:
                        continue
                    cc = m.group(1).lower()
                    obj = (await session.execute(
                        select(AddressObject).where(
                            AddressObject.type == "geo", AddressObject.value == cc
                        )
                    )).scalars().first()
                    if not obj:
                        ref_key = None
                        for _ in range(12):
                            k = fw_addresses.new_ref_key()
                            if (await session.execute(
                                select(AddressObject).where(AddressObject.ref_key == k)
                            )).scalar_one_or_none() is None:
                                ref_key = k
                                break
                        name, base, n = f"Geo {cc.upper()}", f"Geo {cc.upper()}", 2
                        while (await session.execute(
                            select(AddressObject).where(AddressObject.name == name)
                        )).scalar_one_or_none() is not None:
                            name, n = f"{base} ({n})", n + 1
                        obj = AddressObject(ref_key=ref_key, name=name, type="geo",
                                            value=cc, enabled=True)
                        session.add(obj)
                        await session.flush()
                    has_ref = (await session.execute(
                        select(FirewallRuleAddress).where(
                            FirewallRuleAddress.rule_id == rule.id,
                            FirewallRuleAddress.direction == direction,
                            FirewallRuleAddress.object_id == obj.id,
                        )
                    )).scalar_one_or_none()
                    if has_ref is None:
                        session.add(FirewallRuleAddress(
                            rule_id=rule.id, direction=direction, object_id=obj.id, order=0))
                    setattr(rule, direction, None)
                    session.add(rule)
                    migrated += 1
            if migrated:
                await session.commit()
                logger.info(f"Migrated {migrated} legacy geo: rule tokens to geo address objects")
        except Exception as e:
            await session.rollback()
            logger.error(f"Legacy geo: migration failed: {e}", exc_info=True)

    # Apply firewall rules from database
    async with async_session_maker() as session:
        try:
            await firewall_orchestrator.apply_rules(session)
        except Exception as e:
            logger.error(f"Firewall apply_rules failed on startup: {e}", exc_info=True)

    import asyncio

    # Restore services that were UP before the last restart (non-blocking).
    # Runs each module's on_startup hook after firewall rules are applied, so
    # module start logic can layer its dynamic chains on top of the base ruleset.
    async def restore_services():
        try:
            async with async_session_maker() as session:
                await module_loader.run_startup_hooks(session)
            logger.info("Service auto-restore (on_startup hooks) completed")
        except Exception as e:
            logger.error(f"Service auto-restore failed: {e}", exc_info=True)

    restore_task = asyncio.create_task(restore_services())
    logger.info("Service auto-restore started in background")

    # Start background stats collection task
    from core.system.service import system_service, save_stats_to_history, save_network_traffic
    
    stats_task_running = True
    
    async def collect_stats_periodically():
        """Background task to collect system stats every 60 seconds."""
        while stats_task_running:
            try:
                async with async_session_maker() as session:
                    # Collect system stats
                    stats = system_service.get_stats()
                    if stats.get("available"):
                        await save_stats_to_history(
                            session,
                            cpu=stats["cpu"]["percent"],
                            ram=stats["memory"]["percent"],
                            disk=stats["disk"]["percent"],
                            ram_used=stats["memory"]["used"],
                            ram_total=stats["memory"]["total"],
                            disk_used=stats["disk"]["used"],
                            disk_total=stats["disk"]["total"]
                        )
                    
                    # Collect network traffic
                    await save_network_traffic(session)
            except Exception as e:
                logger.error(f"Background stats collection error: {e}")
            
            await asyncio.sleep(60)  # Collect every 60 seconds
    
    # Start the background task
    stats_task = asyncio.create_task(collect_stats_periodically())
    logger.info("Background stats collection started (every 60s)")
    
    # Start scheduled backup task
    from core.settings.models import BackupSettings
    from core.backup.service import run_backup
    from sqlalchemy import select
    from datetime import datetime
    
    backup_task_running = True
    last_backup_date = None
    
    async def scheduled_backup_task():
        """Background task to run scheduled backups."""
        nonlocal last_backup_date
        
        while backup_task_running:
            try:
                async with async_session_maker() as session:
                    result = await session.execute(
                        select(BackupSettings).where(BackupSettings.id == 1)
                    )
                    settings = result.scalar_one_or_none()
                    
                    if settings and settings.enabled:
                        now = datetime.now()
                        current_time = now.strftime("%H:%M")
                        current_date = now.date()
                        
                        # Check if it's time to run backup
                        should_run = False
                        
                        if settings.frequency == "daily":
                            # Run once per day at specified time
                            if current_time == settings.time and last_backup_date != current_date:
                                should_run = True
                        elif settings.frequency == "weekly":
                            # Run on Sundays at specified time
                            if now.weekday() == 6 and current_time == settings.time and last_backup_date != current_date:
                                should_run = True
                        
                        if should_run:
                            logger.info(f"Starting scheduled backup (frequency: {settings.frequency})")
                            last_backup_date = current_date
                            
                            backup_result = await run_backup(
                                session=session,
                                remote_protocol=settings.remote_protocol if settings.remote_host else None,
                                remote_host=settings.remote_host or None,
                                remote_port=settings.remote_port,
                                remote_user=settings.remote_user or None,
                                remote_password=settings.remote_password or None,
                                remote_path=settings.remote_path,
                                retention_days=settings.retention_days
                            )
                            
                            # Update last run status
                            settings.last_run_time = datetime.utcnow()
                            if backup_result.get("success"):
                                settings.last_run_status = "success"
                            elif backup_result.get("archive"):
                                # Archive created locally, but upload failed
                                settings.last_run_status = "upload_failed"
                            else:
                                settings.last_run_status = "failed"
                            session.add(settings)
                            await session.commit()
                            
                            if backup_result.get("success"):
                                logger.info(f"Scheduled backup completed: {backup_result.get('archive')}")
                            else:
                                logger.error(f"Scheduled backup failed: {backup_result.get('errors')}")
                            
            except Exception as e:
                logger.error(f"Scheduled backup task error: {e}")
            
            await asyncio.sleep(60)  # Check every minute
    
    backup_task = asyncio.create_task(scheduled_backup_task())
    logger.info("Scheduled backup task started")
    
    # Start audit log cleanup task
    from core.audit.service import cleanup_old_logs
    
    audit_cleanup_running = True
    
    async def audit_cleanup_task():
        """Background task to clean up old audit log entries (runs every 24h)."""
        while audit_cleanup_running:
            try:
                await asyncio.sleep(86400)  # Wait 24 hours
                async with async_session_maker() as session:
                    await cleanup_old_logs(session)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Audit log cleanup error: {e}")
    
    audit_task = asyncio.create_task(audit_cleanup_task())
    logger.info("Audit log cleanup task started (every 24h)")

    # Start address-object dynamic refresh task (daily at midnight): re-resolve
    # fqdn objects and re-download geo country lists, rebuilding their ipsets.
    import json as _json
    from core.firewall import addresses as fw_addresses
    from core.firewall.models import AddressObject
    from datetime import timedelta

    address_refresh_running = True

    def _seconds_until_midnight() -> float:
        now = datetime.now()
        next_midnight = (now + timedelta(days=1)).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        return (next_midnight - now).total_seconds()

    async def address_refresh_task():
        """Refresh fqdn/geo address-object ipsets every day at midnight."""
        while address_refresh_running:
            try:
                await asyncio.sleep(_seconds_until_midnight())
                async with async_session_maker() as session:
                    result = await session.execute(
                        select(AddressObject).where(
                            AddressObject.enabled == True,
                            AddressObject.type.in_(("fqdn", "geo")),
                        )
                    )
                    objs = result.scalars().all()
                    if not objs:
                        continue
                    obj_dicts = []
                    for o in objs:
                        ips = None
                        if o.resolved_ips:
                            try:
                                ips = _json.loads(o.resolved_ips)
                            except Exception:
                                ips = None
                        obj_dicts.append({
                            "ref_key": o.ref_key, "type": o.type, "value": o.value,
                            "enabled": o.enabled, "resolved_ips": ips,
                        })
                    fresh = await asyncio.to_thread(fw_addresses.refresh_dynamic, obj_dicts)
                    if fresh:
                        now = datetime.utcnow()
                        for o in objs:
                            if o.ref_key in fresh:
                                o.resolved_ips = _json.dumps(fresh[o.ref_key])
                                o.resolved_at = now
                                session.add(o)
                        await session.commit()
                    logger.info(f"Address: refreshed {len(objs)} dynamic objects (fqdn/geo)")
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Address refresh task error: {e}")

    address_task = asyncio.create_task(address_refresh_task())
    logger.info("Address dynamic refresh task started (daily at midnight)")

    logger.info("MADMIN ready!")
    
    yield
    
    # Shutdown
    logger.info("MADMIN shutting down...")
    stats_task_running = False
    backup_task_running = False
    audit_cleanup_running = False
    address_refresh_running = False
    stats_task.cancel()
    backup_task.cancel()
    audit_task.cancel()
    address_task.cancel()
    restore_task.cancel()
    try:
        await restore_task
    except asyncio.CancelledError:
        pass
    try:
        await stats_task
    except asyncio.CancelledError:
        pass
    try:
        await backup_task
    except asyncio.CancelledError:
        pass
    try:
        await audit_task
    except asyncio.CancelledError:
        pass
    try:
        await address_task
    except asyncio.CancelledError:
        pass


class _SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response: Response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        return response


def create_app() -> FastAPI:
    """
    Application factory.
    Creates and configures the FastAPI application.
    """
    from core.openapi import CORE_TAGS, setup_openapi

    app = FastAPI(
        title="MADMIN",
        description="Modular Admin System — Manage your Ubuntu server with ease.\n\n"
                    "Provides core system management (firewall, network, services, cron) "
                    "and a dynamic module system (DHCP, DNS, OpenVPN, WireGuard, IPsec).",
        version=MADMIN_VERSION,
        lifespan=lifespan,
        openapi_tags=list(CORE_TAGS),
        docs_url="/api/docs" if settings.debug else None,
        redoc_url="/api/redoc" if settings.debug else None,
        openapi_url="/api/openapi.json" if settings.debug else None,
        contact={"name": "MADMIN", "url": "https://github.com/edoardo-f/madmin"},
    )

    # Custom OpenAPI schema with JWT security
    setup_openapi(app)
    
    # CORS middleware — no allow_credentials; auth uses Bearer token in localStorage
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.add_middleware(_SecurityHeadersMiddleware)
    
    # Audit log middleware (logs API calls with user identity)
    from core.audit.middleware import AuditLogMiddleware
    app.add_middleware(AuditLogMiddleware)
    
    # Register core routers
    from core.auth.router import router as auth_router
    from core.firewall.router import router as firewall_router
    from core.modules.router import router as modules_router
    from core.settings.router import router as settings_router
    from core.files.router import router as files_router
    from core.backup.router import router as backup_router
    from core.system.router import router as system_router
    from core.services.router import router as services_router
    from core.network.router import router as network_router
    from core.cron.router import router as cron_router
    from core.audit.router import router as audit_router
    from core.provisioning.router import router as provisioning_router
    
    app.include_router(auth_router)
    app.include_router(firewall_router)
    app.include_router(modules_router)
    app.include_router(settings_router)
    app.include_router(files_router)
    app.include_router(backup_router)
    app.include_router(system_router)
    app.include_router(services_router)
    app.include_router(network_router)
    app.include_router(cron_router)
    app.include_router(audit_router)
    app.include_router(provisioning_router)
    
    # UI Router for frontend
    from core.auth.dependencies import get_current_user
    from core.auth.models import User

    @app.get("/api/ui/menu", tags=["System"], include_in_schema=False)
    async def get_full_menu(current_user: User = Depends(get_current_user)):
        """Get complete menu structure for frontend sidebar."""
        from core.modules.loader import module_loader
        
        # Core menu items (labels are i18n keys, resolved by the frontend)
        core_menu = [
            {"label": "menu.dashboard", "icon": "home", "route": "#dashboard", "permission": None},
            {"label": "menu.users", "icon": "users", "route": "#users", "permission": "users.view"},
            {"label": "menu.firewall", "icon": "shield", "route": "#firewall", "permission": "firewall.view"},
            {"label": "menu.network", "icon": "network", "route": "#network", "permission": "network.view"},
            {"label": "menu.crontab", "icon": "clock", "route": "#crontab", "permission": "settings.view"},
            {"label": "menu.logs", "icon": "file-text", "route": "#logs", "permission": "logs.view"},
            {"label": "menu.settings", "icon": "settings", "route": "#settings", "permission": "settings.view"},
            {"label": "menu.modules", "icon": "puzzle", "route": "#modules", "permission": "modules.view"},
        ]
        
        # Add module menu items
        module_menu = module_loader.get_menu_items()
        
        return {
            "core": core_menu,
            "modules": module_menu
        }
    
    # Health check endpoint
    @app.get("/api/health", tags=["System"])
    async def health_check():
        """Health check endpoint."""
        from core.database import check_db_connection

        db_healthy = await check_db_connection()

        return {
            "status": "healthy" if db_healthy else "degraded",
            "database": "connected" if db_healthy else "disconnected",
            "version": MADMIN_VERSION
        }
    
    # Mount static frontend files
    # This should be done after all API routes
    frontend_dir = os.path.join(os.path.dirname(__file__), "..", "frontend")
    uploads_dir = os.environ.get("MADMIN_UPLOAD_DIR", "/opt/madmin/uploads")
    
    # Mount uploads directory
    if os.path.exists(uploads_dir) or True:  # Create if needed when accessed
        os.makedirs(uploads_dir, exist_ok=True)
        app.mount("/uploads", StaticFiles(directory=uploads_dir), name="uploads")
    
    if os.path.exists(frontend_dir):
        # Note: Static assets (/static/*) are served directly by Nginx
        # Module static files are mounted at /static/modules/{module_id} by module_loader
        
        @app.get("/", include_in_schema=False)
        async def serve_index():
            return FileResponse(os.path.join(frontend_dir, "index.html"))

        @app.get("/login", include_in_schema=False)
        async def serve_login():
            return FileResponse(os.path.join(frontend_dir, "login.html"))
    
    return app


# Create the application instance
app = create_app()


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8000,
        reload=settings.debug
    )
