from __future__ import annotations

import time

from redis.asyncio import Redis

from app.core.config import settings
from app.core.logging import log
from app.core.metrics import RATE_LIMIT_REJECTIONS


class RateLimitExceeded(Exception):
    def __init__(self, scope: str, limit: int) -> None:
        self.scope = scope
        self.limit = limit
        super().__init__(f"Rate limit exceeded ({scope}): {limit}/min")


class RateLimiter:
    """Fixed-window (60s) counter in Redis. Simpler and cheaper than a
    sliding-window/token-bucket implementation, with the standard caveat
    that it can allow a short burst across a window boundary — acceptable
    here since the goal is cost/abuse control, not precise throttling."""

    def __init__(self, redis: Redis) -> None:
        self._redis = redis

    async def check_and_increment(self, user_sub: str) -> None:
        if not settings.rate_limit_enabled:
            return

        bucket = int(time.time() // 60)
        global_key = f"ai:ratelimit:global:{bucket}"
        user_key = f"ai:ratelimit:user:{user_sub}:{bucket}"

        try:
            global_count = await self._redis.incr(global_key)
            if global_count == 1:
                await self._redis.expire(global_key, 60)
            user_count = await self._redis.incr(user_key)
            if user_count == 1:
                await self._redis.expire(user_key, 60)
        except Exception as exc:  # noqa: BLE001
            # Fail open — a Redis outage should degrade rate limiting, not
            # take down the whole analysis capability.
            log.warning("rate_limiter_unavailable_failing_open", error=str(exc))
            return

        if global_count > settings.rate_limit_global_per_minute:
            RATE_LIMIT_REJECTIONS.labels(scope="global").inc()
            raise RateLimitExceeded("global", settings.rate_limit_global_per_minute)
        if user_count > settings.rate_limit_per_user_per_minute:
            RATE_LIMIT_REJECTIONS.labels(scope="user").inc()
            raise RateLimitExceeded("user", settings.rate_limit_per_user_per_minute)
