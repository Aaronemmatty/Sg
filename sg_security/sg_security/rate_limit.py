from __future__ import annotations

import time
from collections.abc import Callable

from fastapi import HTTPException, Request, status
from redis.asyncio import Redis
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response


class RedisRateLimiter:
    def __init__(self, redis: Redis, prefix: str) -> None:
        self._redis = redis
        self._prefix = prefix

    async def _check(self, key: str, limit: int, window_seconds: int) -> bool:
        full_key = f"rl:{self._prefix}:{key}:{int(time.time()) // window_seconds}"
        try:
            count = await self._redis.incr(full_key)
            if count == 1:
                await self._redis.expire(full_key, window_seconds)
        except Exception:
            return True
        return count <= limit

    def limit(self, *, per_user: int | None = None, global_limit: int | None = None, window_seconds: int = 60):
        async def _dependency(request: Request) -> None:
            user = getattr(request.state, "user", None)
            user_id = getattr(user, "sub", None) or request.client.host if request.client else "unknown"

            if per_user is not None:
                ok = await self._check(f"user:{user_id}", per_user, window_seconds)
                if not ok:
                    raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail="Rate limit exceeded")

            if global_limit is not None:
                ok = await self._check("global", global_limit, window_seconds)
                if not ok:
                    raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail="Service-wide rate limit exceeded")

        return _dependency


class RateLimitMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, redis_client: Redis, prefix: str, per_ip_limit: int = 120, window_seconds: int = 60, exempt_paths: tuple[str, ...] = ("/health", "/metrics")) -> None:
        super().__init__(app)
        self._limiter = RedisRateLimiter(redis_client, prefix)
        self._per_ip_limit = per_ip_limit
        self._window_seconds = window_seconds
        self._exempt_paths = exempt_paths

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        if request.url.path in self._exempt_paths:
            return await call_next(request)

        client_ip = request.client.host if request.client else "unknown"
        ok = await self._limiter._check(f"ip:{client_ip}", self._per_ip_limit, self._window_seconds)
        if not ok:
            return Response(content='{"detail":"Rate limit exceeded"}', status_code=status.HTTP_429_TOO_MANY_REQUESTS, media_type="application/json")
        return await call_next(request)
