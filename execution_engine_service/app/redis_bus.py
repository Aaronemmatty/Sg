"""
Redis pub/sub integration.

Subscribes (pattern): sg:risk_approved:{symbol}  — produced by risk_engine (8007),
                       carries both RISK_APPROVED and RISK_HOLD (status field distinguishes).
Publishes:             sg:executions:{symbol}     — for portfolio_management_service (8009)
                       sg:execution:events         — general bus for SSE dashboard, non order-flow-critical

Channel contract additions made by execution_engine_service are scoped to its
own outbound namespace (sg:executions:*) so they don't collide with the
existing frozen contract documented in the platform handover.
"""
from __future__ import annotations

import json
from collections.abc import AsyncIterator, Callable, Awaitable

import redis.asyncio as redis

from app.config import settings
from app.logging_config import get_logger
from app.models import ExecutionEvent, RiskDecision

log = get_logger(__name__)

IntentHandler = Callable[[RiskDecision], Awaitable[None]]


class RedisBus:
    def __init__(self) -> None:
        self._redis: redis.Redis | None = None
        self._pubsub: redis.client.PubSub | None = None

    async def connect(self) -> None:
        self._redis = redis.from_url(settings.redis_url, decode_responses=True)
        await self._redis.ping()
        log.info("redis_connected", url=settings.redis_url)

    async def close(self) -> None:
        if self._pubsub:
            await self._pubsub.close()
        if self._redis:
            await self._redis.close()

    async def listen_risk_approved(self) -> AsyncIterator[RiskDecision]:
        """Yields parsed RiskDecision objects from sg:risk_approved:{symbol}.
        Malformed payloads are logged and skipped, never raised, so one bad
        message can't kill the consumer loop."""
        self._pubsub = self._redis.pubsub()
        await self._pubsub.psubscribe(settings.redis_risk_approved_pattern)
        log.info("subscribed", pattern=settings.redis_risk_approved_pattern)

        async for message in self._pubsub.listen():
            if message["type"] != "pmessage":
                continue
            raw = message["data"]
            try:
                payload = json.loads(raw)
                decision = RiskDecision.model_validate(payload)
            except Exception:
                log.error("malformed_risk_decision_payload", raw=raw[:500] if isinstance(raw, str) else str(raw))
                continue
            yield decision

    async def publish_execution_event(self, event: ExecutionEvent) -> None:
        channel = f"{settings.redis_execution_channel_prefix}:{event.symbol}"
        await self._redis.publish(channel, event.model_dump_json())

    async def publish_general_event(self, event: ExecutionEvent) -> None:
        await self._redis.publish(settings.redis_execution_events_channel, event.model_dump_json())


redis_bus = RedisBus()
