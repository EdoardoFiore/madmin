"""
Agent module — initial migration.
Creates: agent_hub_config, agent_log, agent_pushed_ssh_key
"""
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text


async def upgrade(session: AsyncSession):
    await session.execute(text("""
        CREATE TABLE IF NOT EXISTS agent_hub_config (
            id INTEGER PRIMARY KEY DEFAULT 1,
            hub_url VARCHAR(512),
            instance_id VARCHAR(64),
            instance_name VARCHAR(255),
            agent_token_enc TEXT,
            enrollment_status VARCHAR(32) NOT NULL DEFAULT 'not_enrolled',
            ws_connected BOOLEAN NOT NULL DEFAULT FALSE,
            last_heartbeat_at TIMESTAMP,
            hub_ca_fingerprint VARCHAR(128),
            setup_hub_url VARCHAR(512),
            setup_enrollment_token_enc TEXT,
            setup_instance_name VARCHAR(255),
            enrolled_at TIMESTAMP,
            updated_at TIMESTAMP NOT NULL DEFAULT now(),
            last_telemetry_ts TIMESTAMP
        )
    """))

    await session.execute(text("""
        CREATE TABLE IF NOT EXISTS agent_log (
            id SERIAL PRIMARY KEY,
            ts TIMESTAMP NOT NULL DEFAULT now(),
            level VARCHAR(16) NOT NULL DEFAULT 'info',
            event VARCHAR(128) NOT NULL,
            detail VARCHAR(1024)
        )
    """))
    await session.execute(text("CREATE INDEX IF NOT EXISTS idx_agent_log_ts ON agent_log(ts)"))

    await session.execute(text("""
        CREATE TABLE IF NOT EXISTS agent_pushed_ssh_key (
            id SERIAL PRIMARY KEY,
            assignment_id VARCHAR(64) NOT NULL,
            target_user VARCHAR(128) NOT NULL DEFAULT 'madmin',
            public_key TEXT NOT NULL,
            allow_source_ips TEXT,
            iptables_rule_added BOOLEAN NOT NULL DEFAULT FALSE,
            pushed_at TIMESTAMP NOT NULL DEFAULT now(),
            expires_at TIMESTAMP,
            revoked_at TIMESTAMP,
            active BOOLEAN NOT NULL DEFAULT TRUE
        )
    """))
    await session.execute(text(
        "CREATE INDEX IF NOT EXISTS idx_agent_ssh_key_assignment ON agent_pushed_ssh_key(assignment_id)"
    ))

    # Add missing columns to existing tables (for upgrades)
    await session.execute(text("""
        ALTER TABLE agent_hub_config 
        ADD COLUMN IF NOT EXISTS setup_hub_url VARCHAR(512),
        ADD COLUMN IF NOT EXISTS setup_enrollment_token_enc TEXT,
        ADD COLUMN IF NOT EXISTS setup_instance_name VARCHAR(255),
        ADD COLUMN IF NOT EXISTS last_telemetry_ts TIMESTAMP
    """))

    # Seed singleton config row
    await session.execute(text("""
        INSERT INTO agent_hub_config (id) VALUES (1)
        ON CONFLICT (id) DO NOTHING
    """))
