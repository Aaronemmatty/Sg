"""
Event-driven trigger: subscribes to `sg:market:candle:{symbol}:{tf}` for every symbol this
service cares about (NIFTY50 + watchlist) and re-runs the regime engine whenever a new
5-minute candle completes. This is the primary recalculation path; `workers/scheduler.py`
is a redundant watchdog in case candle events are delayed or dropped.
"""
from __future__ import annotations

import asyncio
import logging

from app.config import Settings
from app.core.engine import InsufficientDataError, RegimeDetectionEngine
from app.db.session import session_scope
from app.services.redis_client import RegimeRedisClient

logger = logging.getLogger(__name__)


class CandleConsumer:
    def __init__(self, settings: Settings, redis_client: RegimeRedisClient, engine: RegimeDetectionEngine):
        self.settings = settings
        self.redis = redis_client
        self.engine = engine
        self._task: asyncio.Task | None = None
        self._stop = asyncio.Event()

    def _watched_pairs(self) -> list[tuple[str, str]]:
        tf = self.settings.DEFAULT_TIMEFRAME
        symbols = [self.settings.PRIMARY_SYMBOL, *self.settings.WATCHLIST_SYMBOLS]
        return [(s, tf) for s in symbols]

    async def start(self) -> None:
        self._task = asyncio.create_task(self._run(), name="candle_consumer")

    async def stop(self) -> None:
        self._stop.set()
        if self._task is not None:
            await asyncio.wait_for(self._task, timeout=10)

    async def _run(self) -> None:
        pubsub = await self.redis.subscribe_candles(self._watched_pairs())
        try:
            async for event in self.redis.listen(pubsub):
                if self._stop.is_set():
                    break
                await self._handle_candle_event(event)
        finally:
            await pubsub.unsubscribe()
            await pubsub.aclose()

    async def _handle_candle_event(self, event: dict) -> None:
        symbol = event.get("symbol")
        timeframe = event.get("timeframe", self.settings.DEFAULT_TIMEFRAME)
        if not symbol:
            logger.warning("candle event missing symbol field: %s", event)
            return

        # NIFTY50 always recomputes first so per-symbol divergence checks have a fresh
        # market regime to compare against.
        try:
            async with session_scope() as session:
                if symbol != self.settings.PRIMARY_SYMBOL:
                    await self.engine.detect_market_wide(session, timeframe)
                await self.engine.detect(session, symbol, timeframe)
        except InsufficientDataError as exc:
            logger.info("skipping regime recalc for %s:%s — %s", symbol, timeframe, exc)
        except Exception:  # noqa: BLE001
            logger.exception("regime recalculation failed for %s:%s", symbol, timeframe)
