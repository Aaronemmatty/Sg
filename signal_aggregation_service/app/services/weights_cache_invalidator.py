"""
Subscribes to `sg:weights:updated` so that *other* replicas of this service (which didn't
perform the write themselves) invalidate their in-process WeightStore cache promptly,
rather than waiting out the full WEIGHT_CACHE_TTL_SECONDS window.
"""
from __future__ import annotations

import asyncio
import json
import logging

from app.services.redis_client import AggregationRedisClient
from app.services.weight_store import WeightStore

logger = logging.getLogger(__name__)


class WeightsCacheInvalidator:
    def __init__(self, redis_client: AggregationRedisClient, weight_store: WeightStore):
        self.redis = redis_client
        self.weight_store = weight_store
        self._task: asyncio.Task | None = None
        self._stop = asyncio.Event()

    async def start(self) -> None:
        self._task = asyncio.create_task(self._run(), name="weights_cache_invalidator")

    async def stop(self) -> None:
        self._stop.set()
        if self._task is not None:
            await asyncio.wait_for(self._task, timeout=10)

    async def _run(self) -> None:
        pubsub = await self.redis.subscribe_weights_updated()
        try:
            async for message in pubsub.listen():
                if self._stop.is_set():
                    break
                if message.get("type") != "message":
                    continue
                try:
                    payload = json.loads(message["data"])
                    self.weight_store.invalidate(payload.get("regime"))
                    logger.info("invalidated weight cache for regime=%s", payload.get("regime"))
                except (TypeError, json.JSONDecodeError):
                    logger.warning("dropped malformed weights-updated message")
        finally:
            await pubsub.unsubscribe()
            await pubsub.aclose()
