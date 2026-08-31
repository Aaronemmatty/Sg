"""Async DB session."""
from __future__ import annotations
from collections.abc import AsyncGenerator
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from app.core.config import get_settings
settings = get_settings()
engine = create_async_engine(str(settings.DATABASE_URL), pool_size=5, max_overflow=3, pool_pre_ping=True, echo=settings.DEBUG)
AsyncSessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False, autoflush=False)
async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as s:
        try: yield s; await s.commit()
        except Exception: await s.rollback(); raise
        finally: await s.close()
