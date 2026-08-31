from __future__ import annotations

import pytest

from app.services.rate_limiter import RateLimitExceeded, RateLimiter


class FakeRedis:
    def __init__(self) -> None:
        self.counters: dict[str, int] = {}

    async def incr(self, key: str) -> int:
        self.counters[key] = self.counters.get(key, 0) + 1
        return self.counters[key]

    async def expire(self, key: str, seconds: int) -> None:
        return None


@pytest.mark.asyncio
async def test_allows_requests_under_the_limit(monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "rate_limit_per_user_per_minute", 3)
    monkeypatch.setattr(settings, "rate_limit_global_per_minute", 100)
    monkeypatch.setattr(settings, "rate_limit_enabled", True)

    redis = FakeRedis()
    limiter = RateLimiter(redis)

    for _ in range(3):
        await limiter.check_and_increment("user-1")  # should not raise


@pytest.mark.asyncio
async def test_rejects_requests_over_per_user_limit(monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "rate_limit_per_user_per_minute", 2)
    monkeypatch.setattr(settings, "rate_limit_global_per_minute", 100)
    monkeypatch.setattr(settings, "rate_limit_enabled", True)

    redis = FakeRedis()
    limiter = RateLimiter(redis)

    await limiter.check_and_increment("user-1")
    await limiter.check_and_increment("user-1")
    with pytest.raises(RateLimitExceeded) as exc_info:
        await limiter.check_and_increment("user-1")
    assert exc_info.value.scope == "user"


@pytest.mark.asyncio
async def test_different_users_have_independent_limits(monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "rate_limit_per_user_per_minute", 1)
    monkeypatch.setattr(settings, "rate_limit_global_per_minute", 100)
    monkeypatch.setattr(settings, "rate_limit_enabled", True)

    redis = FakeRedis()
    limiter = RateLimiter(redis)

    await limiter.check_and_increment("user-1")
    await limiter.check_and_increment("user-2")  # different user, should not raise


@pytest.mark.asyncio
async def test_global_limit_enforced_across_users(monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "rate_limit_per_user_per_minute", 100)
    monkeypatch.setattr(settings, "rate_limit_global_per_minute", 2)
    monkeypatch.setattr(settings, "rate_limit_enabled", True)

    redis = FakeRedis()
    limiter = RateLimiter(redis)

    await limiter.check_and_increment("user-1")
    await limiter.check_and_increment("user-2")
    with pytest.raises(RateLimitExceeded) as exc_info:
        await limiter.check_and_increment("user-3")
    assert exc_info.value.scope == "global"


@pytest.mark.asyncio
async def test_disabled_rate_limiter_never_raises(monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "rate_limit_enabled", False)
    redis = FakeRedis()
    limiter = RateLimiter(redis)

    for _ in range(50):
        await limiter.check_and_increment("user-1")


@pytest.mark.asyncio
async def test_fails_open_when_redis_unavailable(monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "rate_limit_enabled", True)
    monkeypatch.setattr(settings, "rate_limit_per_user_per_minute", 1)

    class BrokenRedis:
        async def incr(self, key: str) -> int:
            raise ConnectionError("redis down")

    limiter = RateLimiter(BrokenRedis())
    # Should not raise RateLimitExceeded or propagate the connection error.
    await limiter.check_and_increment("user-1")
