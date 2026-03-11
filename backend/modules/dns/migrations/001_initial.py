"""
DNS Module - Initial Database Migration

Creates DNS tables using direct engine access.
"""
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import SQLModel


async def upgrade(session: AsyncSession) -> None:
    """Create DNS module tables."""
    # Import models to register them in SQLModel metadata
    from modules.dns.models import (
        DnsSettings, DnsZone, DnsRecord, DnsForwarder
    )

    # Import the engine directly from database module
    from core.database import engine

    # Use the engine directly for DDL operations
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)

    print("DNS module tables created")


async def downgrade(session: AsyncSession) -> None:
    """Drop DNS module tables."""
    from core.database import engine
    from sqlalchemy import text

    tables = ["dns_record", "dns_forwarder", "dns_zone", "dns_settings"]

    async with engine.begin() as conn:
        for table in tables:
            await conn.execute(text(f"DROP TABLE IF EXISTS {table} CASCADE"))
