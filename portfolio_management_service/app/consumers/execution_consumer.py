"""
Execution Event Consumer.

Subscribes to sg:executions:* (pattern subscribe) — published by
execution_engine_service (8008). Processes ORDER_FILLED and
ORDER_PARTIALLY_FILLED events to update positions and lots.

All other event types (ORDER_SUBMITTED, ORDER_REJECTED, etc.) are
consumed and recorded in the audit trail but do not trigger position
updates (no fill occurred).

Design:
  - Malformed payloads: logged and skipped (never crash the consumer loop)
  - Duplicate delivery: guarded by pm_processed_events idempotency table
  - One event at a time: no concurrent fill processing for the same symbol
    (asyncio single-threaded event loop serializes this naturally)
"""
from __future__ import annotations

import asyncio
import json

import redis.asyncio as redis

from app.core.config import settings
from app.core.logging import get_logger
from app.core.metrics import fill_processing_errors_total, fill_processing_latency_seconds, fills_consumed_total
from app.db import repository as repo
from app.models.domain import ExecutionEvent, ExecutionEventType
from app.services.position_engine import apply_fill

import time

log = get_logger(__name__)


class ExecutionConsumer:
    """
    Consumes sg:executions:{symbol} pattern and routes fill events
    to the position engine.
    """

    def __init__(self, redis_client: redis.Redis) -> None:
        self._redis = redis_client
        self._pubsub: redis.client.PubSub | None = None

    async def run(self, stop_event: asyncio.Event) -> None:
        self._pubsub = self._redis.pubsub()
        await self._pubsub.psubscribe(settings.redis_executions_pattern)
        log.info("execution_consumer_started", pattern=settings.redis_executions_pattern)

        async for message in self._pubsub.listen():
            if stop_event.is_set():
                break

            if message["type"] != "pmessage":
                continue

            raw = message["data"]
            try:
                payload = json.loads(raw)
                event = ExecutionEvent.model_validate(payload)
            except Exception:
                log.error(
                    "malformed_execution_event",
                    raw=raw[:500] if isinstance(raw, str) else str(raw)[:500],
                )
                continue

            await self._process(event)

        log.info("execution_consumer_stopped")

    async def _process(self, event: ExecutionEvent) -> None:
        # Idempotency: skip if already processed
        already_processed = not await repo.claim_event(event.order_id)
        if already_processed:
            log.debug(
                "execution_event_already_processed",
                order_id=str(event.order_id),
                event_type=event.event_type,
            )
            return

        fills_consumed_total.labels(event_type=event.event_type, symbol=event.symbol).inc()

        # Only ORDER_FILLED and ORDER_PARTIALLY_FILLED carry fills
        if not event.is_fill_event:
            log.debug(
                "execution_event_no_fill_skipping",
                event_type=event.event_type,
                order_id=str(event.order_id),
            )
            return

        t0 = time.perf_counter()
        try:
            updated_position = await apply_fill(event)
            elapsed = time.perf_counter() - t0
            fill_processing_latency_seconds.observe(elapsed)
            log.info(
                "fill_processed",
                symbol=event.symbol,
                action=event.action,
                qty=event.filled_quantity,
                net_qty=updated_position.net_quantity,
                event_type=event.event_type,
                latency_ms=round(elapsed * 1000, 2),
            )
        except Exception:
            elapsed = time.perf_counter() - t0
            fill_processing_errors_total.labels(symbol=event.symbol).inc()
            log.exception(
                "fill_processing_failed",
                order_id=str(event.order_id),
                symbol=event.symbol,
                event_type=event.event_type,
                latency_ms=round(elapsed * 1000, 2),
            )

    async def shutdown(self) -> None:
        if self._pubsub:
            await self._pubsub.close()
            log.info("execution_consumer_pubsub_closed")
