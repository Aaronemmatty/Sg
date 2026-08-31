"""Redis connection helper — consistent with 8001–8009."""
from __future__ import annotations

import redis.asyncio as redis

from app.core.config import settings
from app.core.logging import get_logger

log = get_logger(__name__)

_client: redis.Redis | None = None


async def get_redis() -> redis.Redis:
    global _client
    if _client is None:
        _client = redis.from_url(settings.redis_url, decode_responses=True)
        await _client.ping()
        log.info("redis_connected", url=settings.redis_url)
    return _client


async def close_redis() -> None:
    global _client
    if _client is not None:
        await _client.close()
        _client = None
