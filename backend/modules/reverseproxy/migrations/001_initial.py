"""
Reverse Proxy Module - Initial Database Migration
"""
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import SQLModel


async def upgrade(session: AsyncSession) -> None:
    """Create Reverse Proxy module tables."""
    from modules.reverseproxy.models import (
        RevproxyHost, RevproxyHostDomain,
        RevproxyAccessList, RevproxyAccessListAuth, RevproxyAccessListRule,
        RevproxyCertificate,
    )
    from core.database import engine

    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)

    print("Reverse Proxy module tables created")


async def downgrade(session: AsyncSession) -> None:
    """Drop Reverse Proxy module tables."""
    from core.database import engine
    from sqlalchemy import text

    tables = [
        "revproxy_certificate",
        "revproxy_access_list_rule",
        "revproxy_access_list_auth",
        "revproxy_host_domain",
        "revproxy_host",
        "revproxy_access_list",
    ]

    async with engine.begin() as conn:
        for table in tables:
            await conn.execute(text(f"DROP TABLE IF EXISTS {table} CASCADE"))
