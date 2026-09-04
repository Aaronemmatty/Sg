"""
asyncpg connection pool for portfolio_management_service.

Matches the exact pool + migration pattern from execution_engine_service (8008).
"""
from __future__ import annotations

from pathlib import Path

import asyncpg

from app.core.config import settings
from app.core.logging import get_logger

log = get_logger(__name__)

pool: asyncpg.Pool | None = None


def get_pool() -> asyncpg.Pool:
    if pool is None:
        raise RuntimeError("Database pool not initialized — call init_pool() first")
    return pool


async def init_pool() -> asyncpg.Pool:
    global pool
    clean_dsn = settings.database_url.replace("postgresql+asyncpg://", "postgresql://")
    pool = await asyncpg.create_pool(
        dsn=clean_dsn,
        min_size=settings.db_pool_min_size,
        max_size=settings.db_pool_max_size,
    )
    await _run_migrations(pool)
    log.info("db_pool_initialized", min_size=settings.db_pool_min_size, max_size=settings.db_pool_max_size)
    return pool


async def close_pool() -> None:
    global pool
    if pool is not None:
        await pool.close()
        pool = None
        log.info("db_pool_closed")


async def _run_migrations(p: asyncpg.Pool) -> None:
    migrations_dir = Path(__file__).resolve().parent.parent.parent / "migrations"
    for migration_file in sorted(migrations_dir.glob("*.sql")):
        sql = migration_file.read_text()
        async with p.acquire() as conn:
            await conn.execute(sql)
        log.info("migration_applied", file=migration_file.name)
