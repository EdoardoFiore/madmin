"""
In-place schema migrations: an update (madmin-update) keeps the database, so
a change to an existing table or column ships as a numbered step.

    core     backend/core/migrations/NNNN_<name>.py
    module   backend/modules/<id>/upgrades/NNNN_<name>.py

Each step defines `async def upgrade(conn)` (an AsyncConnection inside its
own transaction) and runs once, in order; the last one applied is recorded
in schema_version (component = "core" or the module id). Forward only: a
rollback restores the dump madmin-update takes before the switch.

- A fresh database (no core table before create_all): create_all builds the
  current schema, the latest step is recorded, nothing runs.
- A database from before this mechanism (1.2.0): version 0, every step runs.
- A module activated now: its initial migrations create the current tables,
  the latest step is recorded (mark_module_current); deactivating it drops
  its tables and forgets its version.

A step that fails stops the startup: madmin-update then rolls back.
"""
import importlib.util
import logging
import re
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Tuple

from sqlalchemy import text

logger = logging.getLogger(__name__)

CORE_DIR = Path(__file__).parent
_STEP_RE = re.compile(r"^(\d{4})_[a-z0-9_]+\.py$")


def steps(directory: Path) -> List[Tuple[int, Path]]:
    if not directory.is_dir():
        return []
    found = sorted((int(m.group(1)), p) for p in directory.iterdir() if (m := _STEP_RE.match(p.name)))
    numbers = [n for n, _ in found]
    if numbers != list(range(1, len(numbers) + 1)):
        raise RuntimeError(f"migration steps in {directory} are not numbered 1..N: {numbers}")
    return found


def latest(directory: Path) -> int:
    return len(steps(directory))


async def _ensure_table(conn) -> None:
    await conn.execute(text(
        "CREATE TABLE IF NOT EXISTS schema_version ("
        " component VARCHAR(64) PRIMARY KEY, version INTEGER NOT NULL, applied_at TIMESTAMP NOT NULL)"
    ))


async def _get(conn, component: str) -> Optional[int]:
    row = (await conn.execute(text("SELECT version FROM schema_version WHERE component = :c"),
                              {"c": component})).first()
    return None if row is None else int(row[0])


async def _set(conn, component: str, version: int) -> None:
    await conn.execute(text(
        "INSERT INTO schema_version (component, version, applied_at) VALUES (:c, :v, :t) "
        "ON CONFLICT (component) DO UPDATE SET version = :v, applied_at = :t"
    ), {"c": component, "v": version, "t": datetime.utcnow()})


async def _run(engine, component: str, directory: Path, fresh: bool) -> None:
    async with engine.begin() as conn:
        await _ensure_table(conn)
        current = await _get(conn, component)
    available = steps(directory)
    if current is None and fresh:
        async with engine.begin() as conn:
            await _set(conn, component, len(available))
        return
    current = current or 0
    if current > len(available):
        raise RuntimeError(f"schema of {component} ({current}) newer than this release ({len(available)})")
    for number, path in available[current:]:
        spec = importlib.util.spec_from_file_location(f"migration_{component}_{number}", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        logger.info("Schema %s: step %04d (%s)", component, number, path.stem)
        async with engine.begin() as conn:
            await module.upgrade(conn)
            await _set(conn, component, number)


async def core_is_fresh(engine) -> bool:
    """Before create_all: no core table yet means a new installation."""
    async with engine.connect() as conn:
        row = (await conn.execute(text("SELECT to_regclass('public.\"user\"')"))).first()
    return row is None or row[0] is None


async def run_core(engine, fresh: bool) -> None:
    await _run(engine, "core", CORE_DIR, fresh)


async def run_module(engine, module_id: str, module_path: Path) -> None:
    """Steps of an installed module (its tables exist): at every startup."""
    await _run(engine, module_id, module_path / "upgrades", fresh=False)


async def mark_module_current(engine, module_id: str, module_path: Path) -> None:
    """A module just activated has the current tables: nothing to run."""
    async with engine.begin() as conn:
        await _ensure_table(conn)
        await _set(conn, module_id, latest(module_path / "upgrades"))


async def forget_module(engine, module_id: str) -> None:
    """A module deactivated: its tables are dropped, so is its version."""
    async with engine.begin() as conn:
        await _ensure_table(conn)
        await conn.execute(text("DELETE FROM schema_version WHERE component = :c"), {"c": module_id})
