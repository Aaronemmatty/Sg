"""Thin facade so API/worker code publishes events without reaching into RegimeRedisClient
internals directly. Keeps `app/events/contracts.py` as the single source of truth for shape."""
from __future__ import annotations

from app.models.domain import RegimeResult
from app.services.redis_client import RegimeRedisClient


class RegimeEventPublisher:
    def __init__(self, redis_client: RegimeRedisClient):
        self.redis = redis_client

    async def publish_update(self, result: RegimeResult) -> None:
        await self.redis.publish_regime_event(result, event_type="regime_update")

    async def publish_change(self, result: RegimeResult) -> None:
        await self.redis.publish_regime_event(result, event_type="regime_change")
