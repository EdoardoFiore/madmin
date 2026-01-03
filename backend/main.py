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
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
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
    from core.auth.service import init_core_permissions, init_default_admin
    from core.firewall.orchestrator import firewall_orchestrator
    from core.modules.loader import module_loader
    
    # Initialize database
    logger.info("Initializing database...")
    await init_db()
    
    # Initialize core permissions and default admin
    async with async_session_maker() as session:
        await init_core_permissions(session)
        await init_default_admin(session)
        await session.commit()
    
    # Initialize firewall chains
    logger.info("Initializing firewall chains...")
    await firewall_orchestrator.initialize()
    
    # Load installed modules
    logger.info("Loading modules...")
    async with async_session_maker() as session:
        await module_loader.load_all_modules(app, session)
        await session.commit()
    
    # Apply firewall rules from database
    async with async_session_maker() as session:
        await firewall_orchestrator.apply_rules(session)
    
    logger.info("MADMIN ready!")
    
    yield
    
    # Shutdown
    logger.info("MADMIN shutting down...")


def create_app() -> FastAPI:
    """
    Application factory.
    Creates and configures the FastAPI application.
    """
    app = FastAPI(
        title="MADMIN",
        description="Modular Admin System - Manage your server with ease",
        version="1.0.0",
        lifespan=lifespan
    )
    
    # CORS middleware
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    
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
    
    # UI Router for frontend
    @app.get("/api/ui/menu")
    async def get_full_menu():
        """Get complete menu structure for frontend sidebar."""
        from core.modules.loader import module_loader
        from core.auth.dependencies import get_current_user
        
        # Core menu items
        core_menu = [
            {"label": "Dashboard", "icon": "home", "route": "#dashboard", "permission": None},
            {"label": "Utenti", "icon": "users", "route": "#users", "permission": "users.view"},
            {"label": "Firewall Macchina", "icon": "shield", "route": "#firewall", "permission": "firewall.view"},
            {"label": "Rete", "icon": "network", "route": "#network", "permission": "network.view"},
            {"label": "Crontab", "icon": "clock", "route": "#crontab", "permission": "settings.view"},
            {"label": "Impostazioni", "icon": "settings", "route": "#settings", "permission": "settings.view"},
            {"label": "Moduli", "icon": "puzzle", "route": "#modules", "permission": "modules.view"},
        ]
        
        # Add module menu items
        module_menu = module_loader.get_menu_items()
        
        return {
            "core": core_menu,
            "modules": module_menu
        }
    
    # Health check endpoint
    @app.get("/api/health")
    async def health_check():
        """Health check endpoint."""
        from core.database import check_db_connection
        
        db_healthy = await check_db_connection()
        
        return {
            "status": "healthy" if db_healthy else "degraded",
            "database": "connected" if db_healthy else "disconnected",
            "version": "1.0.0"
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
        
        @app.get("/")
        async def serve_index():
            """Serve the main SPA index."""
            return FileResponse(os.path.join(frontend_dir, "index.html"))
        
        @app.get("/login")
        async def serve_login():
            """Serve the login page."""
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
