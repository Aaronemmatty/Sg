"""
shared_security_lib/rate_limit.py — Redis fixed-window rate limiter, the
same pattern already proven in ai_analyst_service (8012), generalized so
the other 10 services (which currently have NO inbound rate limiting at
all — see SECURITY findings, "no rate limiting" gap) can adopt it without
re-deriving the logic.

This is deliberately the same fixed-window approach as 8012 rather than a
token-bucket/sliding-window, for consistency — both share the same known
limitation (a burst up to ~2x the limit across a minute boundary), which
is an acceptable, already-documented tradeoff platform-wide rather than a
new one introduced here. Upgrade both together later if it matters.

Usage (per-route):

    from shared_security_lib.rate_limit import RedisRateLimiter

    limiter = RedisRateLimiter(redis_client, prefix="risk_engine")

    @router.post("/intents")
    async def submit_intent(
        ...,
        _rl: None = Depends(limiter.limit(per_user=60, global_limit=600, window_seconds=60)),
    ):
        ...

Usage (apply platform-wide as ASGI middleware instead, e.g. for a service
with many routes that all deserve the same default):

    app.add_middleware(
        RateLimitMiddleware,
        redis_client=redis_client,
        prefix="market_data_service",
        per_ip_limit=120,
        window_seconds=60,
    )
"""
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
        """Fixed-window counter. Returns True if the request should proceed."""
        full_key = f"rl:{self._prefix}:{key}:{int(time.time()) // window_seconds}"
        try:
            count = await self._redis.incr(full_key)
            if count == 1:
                await self._redis.expire(full_key, window_seconds)
        except Exception:
            # Fails OPEN on Redis outage — same documented tradeoff as
            # ai_analyst_service's existing rate limiter/cache. This is a
            # deliberate availability-over-strictness choice, not an
            # oversight; an attacker would need a concurrent Redis outage
            # AND knowledge of it to exploit the gap, and failing closed
            # here would turn a Redis blip into a platform-wide outage.
            return True
        return count <= limit

    def limit(self, *, per_user: int | None = None, global_limit: int | None = None, window_seconds: int = 60):
        async def _dependency(request: Request) -> None:
            user = getattr(request.state, "user", None)
            user_id = getattr(user, "sub", None) or request.client.host if request.client else "unknown"

            if per_user is not None:
                ok = await self._check(f"user:{user_id}", per_user, window_seconds)
                if not ok:
                    raise HTTPException(
                        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                        detail="Rate limit exceeded",
                    )

            if global_limit is not None:
                ok = await self._check("global", global_limit, window_seconds)
                if not ok:
                    raise HTTPException(
                        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                        detail="Service-wide rate limit exceeded",
                    )

        return _dependency


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Per-IP rate limiting at the ASGI layer — use for services where
    gating every route individually isn't worth the boilerplate (most of
    the 10 currently-unprotected services). Exempts /health and /metrics
    so Prometheus scraping and liveness probes are never throttled."""

    def __init__(
        self,
        app,
        redis_client: Redis,
        prefix: str,
        per_ip_limit: int = 120,
        window_seconds: int = 60,
        exempt_paths: tuple[str, ...] = ("/health", "/metrics"),
    ) -> None:
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
            return Response(
                content='{"detail":"Rate limit exceeded"}',
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                media_type="application/json",
            )
        return await call_next(request)
