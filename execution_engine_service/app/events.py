"""
In-process event bus.

State-machine transitions call `event_bus.publish(event)` once persisted.
Subscribers (metrics, Redis outbound publisher, SSE fanout) react without the
order-processing workflow needing to know about them. This keeps worker.py
free of side-effect-specific code and makes it trivial to add new consumers
(e.g. a future alerting subscriber) without touching the workflow.
"""
from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable

from app.logging_config import get_logger
from app.models import ExecutionEvent

log = get_logger(__name__)

Subscriber = Callable[[ExecutionEvent], Awaitable[None]]


class EventBus:
    def __init__(self) -> None:
        self._subscribers: list[Subscriber] = []
        # Fan-out queue for SSE consumers (each SSE connection gets its own queue,
        # registered/unregistered via subscribe_sse / unsubscribe_sse).
        self._sse_queues: list[asyncio.Queue[ExecutionEvent]] = []

    def subscribe(self, fn: Subscriber) -> None:
        self._subscribers.append(fn)

    def subscribe_sse(self) -> asyncio.Queue[ExecutionEvent]:
        q: asyncio.Queue[ExecutionEvent] = asyncio.Queue(maxsize=1000)
        self._sse_queues.append(q)
        return q

    def unsubscribe_sse(self, q: asyncio.Queue[ExecutionEvent]) -> None:
        if q in self._sse_queues:
            self._sse_queues.remove(q)

    async def publish(self, event: ExecutionEvent) -> None:
        log.info(
            "execution_event",
            event_type=event.event_type,
            order_id=str(event.order_id),
            symbol=event.symbol,
            state=event.state.value,
        )
        for fn in self._subscribers:
            try:
                await fn(event)
            except Exception:
                log.exception("event_subscriber_failed", event_type=event.event_type)

        for q in list(self._sse_queues):
            try:
                q.put_nowait(event)
            except asyncio.QueueFull:
                log.warning("sse_queue_full_dropping_event", event_type=event.event_type)


event_bus = EventBus()
