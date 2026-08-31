"""
Event-driven trigger for signal_aggregation_service. Subscribes to both
`sg:signals:{symbol}` (a strategy published a new signal) and `sg:regime:{symbol}` (the
regime changed, which changes which weights apply) for every symbol this service cares
about, and recomputes the aggregate whenever either fires. `workers/scheduler.py` is the
redundant watchdog in case events are delayed or dropped.
"""
from __future__ import annotations

import asyncio
import logging

from app.config import Settings
from app.core.engine import NoSignalsAvailableError, SignalAggregationEngine
from app.db.session import session_scope
from app.services.redis_client import AggregationRedisClient

logger = logging.getLogger(__name__)


class SignalConsumer:
    def __init__(self, settings: Settings, redis_client: AggregationRedisClient, engine: SignalAggregationEngine):
        self.settings = settings
        self.redis = redis_client
        self.engine = engine
        self._task: asyncio.Task | None = None
        self._stop = asyncio.Event()

    def _watched_symbols(self) -> list[str]:
        return [self.settings.PRIMARY_SYMBOL, *self.settings.WATCHLIST_SYMBOLS]

    async def start(self) -> None:
        self._task = asyncio.create_task(self._run(), name="signal_consumer")

    async def stop(self) -> None:
        self._stop.set()
        if self._task is not None:
            await asyncio.wait_for(self._task, timeout=10)

    async def _run(self) -> None:
        pubsub = await self.redis.subscribe_triggers(self._watched_symbols())
        try:
            async for event in self.redis.listen(pubsub):
                if self._stop.is_set():
                    break
                await self._handle_trigger(event)
        finally:
            await pubsub.unsubscribe()
            await pubsub.aclose()

    async def _handle_trigger(self, event: dict) -> None:
        data = event.get("data", {})
        symbol = data.get("symbol")
        timeframe = data.get("timeframe", self.settings.DEFAULT_TIMEFRAME)
        if not symbol:
            logger.warning("trigger event missing symbol field on %s: %s", event.get("channel"), data)
            return

        try:
            async with session_scope() as session:
                await self.engine.aggregate(session, symbol, timeframe)
        except NoSignalsAvailableError as exc:
            logger.info("skipping aggregation for %s:%s — %s", symbol, timeframe, exc)
        except Exception:  # noqa: BLE001
            logger.exception("aggregation failed for %s:%s", symbol, timeframe)
