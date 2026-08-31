"""Redis client — broker service."""
from __future__ import annotations
from typing import Optional
import redis.asyncio as aioredis
from app.core.config import get_settings

settings = get_settings()
_pool: Optional[aioredis.Redis] = None

async def get_redis() -> aioredis.Redis:
    global _pool
    if _pool is None:
        _pool = await aioredis.from_url(
            str(settings.REDIS_URL), encoding="utf-8",
            decode_responses=True, max_connections=10,
        )
    return _pool

async def close_redis() -> None:
    global _pool
    if _pool:
        await _pool.aclose()
        _pool = None
