"""Thin facade over AggregationRedisClient for publishing, keeping contracts.py as the
single source of truth for event shapes."""
from __future__ import annotations

from app.models.domain import AggregatedSignalResult
from app.services.redis_client import AggregationRedisClient


class AggregationEventPublisher:
    def __init__(self, redis_client: AggregationRedisClient):
        self.redis = redis_client

    async def publish_result(self, result: AggregatedSignalResult) -> None:
        await self.redis.publish_result(result)

    async def publish_weights_updated(self, regime: str) -> None:
        await self.redis.publish_weights_updated(regime)
