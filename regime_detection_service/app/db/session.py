"""Async SQLAlchemy engine/session, tenant-scoped via RLS GUC, matching platform conventions."""
from __future__ import annotations

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import get_settings

settings = get_settings()

engine = create_async_engine(
    settings.DATABASE_URL,
    pool_size=settings.DB_POOL_SIZE,
    max_overflow=settings.DB_MAX_OVERFLOW,
    pool_pre_ping=True,
    future=True,
)

SessionLocal = async_sessionmaker(bind=engine, expire_on_commit=False, class_=AsyncSession)


@asynccontextmanager
async def session_scope(tenant_id: str | None = None) -> AsyncGenerator[AsyncSession, None]:
    """
    Yields an AsyncSession with the tenant RLS GUC set, matching the platform's row-level
    security convention (`current_setting('app.tenant_id')` used in RLS policies).
    """
    async with SessionLocal() as session:
        tid = tenant_id or settings.DEFAULT_TENANT_ID
        await session.execute(text("SELECT set_config('app.tenant_id', :tid, true)"), {"tid": tid})
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency."""
    async with session_scope() as session:
        yield session
