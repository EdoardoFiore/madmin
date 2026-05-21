"""
MADMIN Core Database Module

Provides async PostgreSQL connection using SQLAlchemy 2.0 with asyncpg driver.
Handles session management and database initialization.
"""
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy import text
from sqlalchemy.orm import DeclarativeBase
from sqlmodel import SQLModel
from typing import AsyncGenerator
import logging

from config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

# Create async engine
engine = create_async_engine(
    settings.database_url,
    echo=settings.debug,
    pool_pre_ping=True,
    pool_size=5,
    max_overflow=10
)

# Async session factory
async_session_maker = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False
)


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """
    Dependency that provides an async database session.
    Automatically handles commit/rollback and session cleanup.
    """
    async with async_session_maker() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


async def init_db() -> None:
    """
    Initialize database tables.
    Creates all tables defined in SQLModel metadata, then applies incremental
    column migrations for tables that may already exist.
    """
    async with engine.begin() as conn:
        # Import all models to ensure they're registered in SQLModel metadata
        from core.auth.models import User, Permission, UserPermission, RevokedToken, LoginAttempt
        from core.firewall.models import MachineFirewallRule, ModuleChain, FirewallObject
        from core.modules.models import InstalledModule
        from core.settings.models import SystemSettings, SMTPSettings, BackupSettings
        from core.audit.models import AuditLog

        await conn.run_sync(SQLModel.metadata.create_all)
        logger.info("Database tables created successfully")

        # Incremental migrations: add columns to existing tables that predate this feature.
        # Uses ADD COLUMN IF NOT EXISTS so safe to run on fresh and existing DBs.
        await _migrate_firewall_object_columns(conn)


async def _migrate_firewall_object_columns(conn) -> None:
    """Add FirewallObject FK columns to machine_firewall_rule (step 1.1 migration)."""
    migrations = [
        "ALTER TABLE machine_firewall_rule ADD COLUMN IF NOT EXISTS "
        "source_object_id UUID REFERENCES firewall_object(id) ON DELETE SET NULL",
        "ALTER TABLE machine_firewall_rule ADD COLUMN IF NOT EXISTS "
        "destination_object_id UUID REFERENCES firewall_object(id) ON DELETE SET NULL",
        "ALTER TABLE machine_firewall_rule ADD COLUMN IF NOT EXISTS "
        "service_object_id UUID REFERENCES firewall_object(id) ON DELETE SET NULL",
    ]
    for stmt in migrations:
        try:
            await conn.execute(text(stmt))
        except Exception as e:
            logger.warning(f"Migration skipped (already applied?): {e}")


async def check_db_connection() -> bool:
    """
    Check if database connection is healthy.
    Returns True if connection successful, False otherwise.
    """
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
            return True
    except Exception as e:
        logger.error(f"Database connection failed: {e}")
        return False
