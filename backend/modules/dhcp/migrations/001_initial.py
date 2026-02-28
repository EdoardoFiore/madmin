"""
DHCP Module - Initial Database Migration

Creates DHCP tables using direct engine access.
"""
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import SQLModel


async def upgrade(session: AsyncSession) -> None:
    """Create DHCP module tables."""
    # Import models to register them in SQLModel metadata
    from modules.dhcp.models import (
        DhcpSubnet, DhcpHost, DhcpOption
    )

    # Import the engine directly from database module
    from core.database import engine

    # Use the engine directly for DDL operations
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)

    print("DHCP module tables created")


async def downgrade(session: AsyncSession) -> None:
    """Drop DHCP module tables."""
    from core.database import engine
    from sqlalchemy import text

    tables = ["dhcp_option", "dhcp_host", "dhcp_subnet"]

    async with engine.begin() as conn:
        for table in tables:
            await conn.execute(text(f"DROP TABLE IF EXISTS {table} CASCADE"))
