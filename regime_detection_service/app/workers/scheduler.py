"""
Watchdog scheduler: redundant to the event-driven CandleConsumer. Runs every
`RECALC_INTERVAL_SECONDS` (default 300s = 5 minutes) and recomputes the regime for any
symbol whose cached regime is missing or stale, so a dropped/delayed pub/sub message never
leaves the platform without a regime read for more than one interval.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

from app.config import Settings
from app.core.engine import InsufficientDataError, RegimeDetectionEngine
from app.db.session import session_scope
from app.services.redis_client import RegimeRedisClient

logger = logging.getLogger(__name__)

STALE_AFTER_SECONDS = 600  # 2x the default 5-min cadence


class RegimeWatchdogScheduler:
    def __init__(self, settings: Settings, redis_client: RegimeRedisClient, engine: RegimeDetectionEngine):
        self.settings = settings
        self.redis = redis_client
        self.engine = engine
        self._task: asyncio.Task | None = None
        self._stop = asyncio.Event()

    async def start(self) -> None:
        self._task = asyncio.create_task(self._run(), name="regime_watchdog_scheduler")

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
                        if symbol != self.settings.PRIMARY_SYMBOL:
                            await self.engine.detect_market_wide(session, tf)
                        await self.engine.detect(session, symbol, tf)
                except InsufficientDataError as exc:
                    logger.info("watchdog: insufficient data for %s:%s — %s", symbol, tf, exc)
                except Exception:  # noqa: BLE001
                    logger.exception("watchdog: recalculation failed for %s:%s", symbol, tf)

    async def _is_stale(self, symbol: str, timeframe: str) -> bool:
        cached = await self.redis.get_cached_regime(symbol, timeframe)
        if cached is None:
            return True
        age = (datetime.now(timezone.utc) - cached.timestamp).total_seconds()
        return age > STALE_AFTER_SECONDS
