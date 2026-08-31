import pytest

from sg_security.rate_limit import RedisRateLimiter


class FakeRedis:
    def __init__(self):
        self.values = {}

    async def incr(self, key: str) -> int:
        self.values[key] = self.values.get(key, 0) + 1
        return self.values[key]

    async def expire(self, key: str, ttl: int) -> None:
        self.values[key] = self.values[key]


class DummyRequest:
    def __init__(self, user_sub: str):
        self.state = type("State", (), {"user": type("User", (), {"sub": user_sub})()})()
        self.client = type("Client", (), {"host": "127.0.0.1"})()


@pytest.mark.asyncio
async def test_rate_limiter_blocks_second_request_for_same_user():
    redis = FakeRedis()
    limiter = RedisRateLimiter(redis, prefix="demo")
    dependency = limiter.limit(per_user=1, window_seconds=60)

    await dependency(DummyRequest("user-1"))

    with pytest.raises(Exception):
        await dependency(DummyRequest("user-1"))
