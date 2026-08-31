"""
Watchdog scheduler: redundant to the event-driven SignalConsumer. Runs every
`RECALC_INTERVAL_SECONDS` and recomputes the aggregate for any symbol whose cached result
is missing or stale, so a dropped/delayed pub/sub message never leaves the platform
without a recent consensus read for more than one interval.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

from app.config import Settings
from app.core.engine import NoSignalsAvailableError, SignalAggregationEngine
from app.db.session import session_scope
from app.services.redis_client import AggregationRedisClient

logger = logging.getLogger(__name__)


class AggregationWatchdogScheduler:
    def __init__(self, settings: Settings, redis_client: AggregationRedisClient, engine: SignalAggregationEngine):
        self.settings = settings
        self.redis = redis_client
        self.engine = engine
        self._task: asyncio.Task | None = None
        self._stop = asyncio.Event()

    async def start(self) -> None:
        self._task = asyncio.create_task(self._run(), name="aggregation_watchdog_scheduler")

    async def stop(self) -> None:
        self._stop.set()
        if self._task is not None:
            await asyncio.wait_for(self._task, timeout=10)

    async def _run(self) -> None:
        while not self._stop.is_set():
            try:
                await self._tick()
            except Exception:  # noqa: BLE001
                logger.exception("watchdog tick failed")
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=self.settings.RECALC_INTERVAL_SECONDS)
            except asyncio.TimeoutError:
                continue

    async def _tick(self) -> None:
        tf = self.settings.DEFAULT_TIMEFRAME
        symbols = [self.settings.PRIMARY_SYMBOL, *self.settings.WATCHLIST_SYMBOLS]
        for symbol in symbols:
            if await self._is_stale(symbol, tf):
                logger.info("watchdog: cache stale/missing for %s:%s — recalculating", symbol, tf)
                try:
                    async with session_scope() as session:
                        await self.engine.aggregate(session, symbol, tf)
                except NoSignalsAvailableError as exc:
                    logger.info("watchdog: no signals for %s:%s — %s", symbol, tf, exc)
                except Exception:  # noqa: BLE001
                    logger.exception("watchdog: aggregation failed for %s:%s", symbol, tf)

    async def _is_stale(self, symbol: str, timeframe: str) -> bool:
        cached = await self.redis.get_cached_result(symbol, timeframe)
        if cached is None:
            return True
        age = (datetime.now(timezone.utc) - cached.timestamp).total_seconds()
        return age > self.settings.STALE_AFTER_SECONDS
