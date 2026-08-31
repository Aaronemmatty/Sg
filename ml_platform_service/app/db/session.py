"""asyncpg pool — consistent with 8001–8009."""
from __future__ import annotations

from pathlib import Path

import asyncpg

from app.core.config import settings
from app.core.logging import get_logger

log = get_logger(__name__)
pool: asyncpg.Pool | None = None


async def init_pool() -> asyncpg.Pool:
    global pool
    pool = await asyncpg.create_pool(
        dsn=settings.database_url,
        min_size=settings.db_pool_min_size,
        max_size=settings.db_pool_max_size,
    )
    await _run_migrations(pool)
    log.info("db_pool_initialized")
    return pool


async def close_pool() -> None:
    global pool
    if pool:
        await pool.close()
        pool = None


async def _run_migrations(p: asyncpg.Pool) -> None:
    migrations_dir = Path(__file__).resolve().parent.parent.parent / "migrations"
    for f in sorted(migrations_dir.glob("*.sql")):
        async with p.acquire() as conn:
            await conn.execute(f.read_text())
        log.info("migration_applied", file=f.name)
