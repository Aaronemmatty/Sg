"""
Market Data Engine — central orchestrator.

Wires together:
  Feed (KiteTicker/Mock) → Validator → Aggregator → Redis pub/sub
                                                   → PostgreSQL writer
                                                   → ClickHouse (optional)

Lifecycle:
  engine.start()   — called at app startup
  engine.stop()    — called at app shutdown
  engine.subscribe(symbols)
  engine.unsubscribe(symbols)
"""

from __future__ import annotations

import asyncio
from typing import Optional

from sqlalchemy.ext.asyncio import async_sessionmaker, AsyncSession

from app.aggregator.candle import CandleAggregator
from app.core.calendar import is_market_open, seconds_to_market_open
from app.core.config import get_settings
from app.core.logging import get_logger
from app.core.redis import (
    publish_candle,
    publish_status,
    set_feed_status,
    store_candle,
)
from app.core.types import OHLCV, Tick
from app.feeds.base import BaseFeed, MockFeed
from app.feeds.kite.instruments import get_registry
from app.feeds.kite.ticker import KiteFeed
from app.publishers.postgres import CandleWriter

settings = get_settings()
log = get_logger(__name__)


class MarketDataEngine:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory
        self._feed: Optional[BaseFeed] = None
        self._aggregator: Optional[CandleAggregator] = None
        self._writer: Optional[CandleWriter] = None
        self._scheduler_task: Optional[asyncio.Task] = None
        self._running = False
        self._subscribed_symbols: set[str] = set()

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    async def start(self) -> None:
        if self._running:
            return

        log.info("engine_starting", mode=settings.KITE_MODE)

        # 1. Load instrument registry
        registry = get_registry()
        await registry.load()

        # 2. Create candle writer
        self._writer = CandleWriter(
            session_factory=self._session_factory,
            batch_size=100,
            flush_interval_s=5.0,
        )
        await self._writer.start()

        # 3. Create aggregator — on_complete fires when candle closes
        self._aggregator = CandleAggregator(on_complete=self._on_candle_complete)

        # 4. Create feed
        if settings.KITE_MODE == "mock":
            self._feed = MockFeed(
                on_tick=self._on_tick,
                tick_interval_ms=500,
            )
            # Auto-subscribe to default mock symbols
            await self._feed.start()
            await self._feed.subscribe(MockFeed.DEFAULT_SYMBOLS)
            self._subscribed_symbols.update(MockFeed.DEFAULT_SYMBOLS.keys())
        else:
            self._feed = KiteFeed(on_tick=self._on_tick)
            await self._feed.start()

        self._running = True

        # 5. Market-hours scheduler
        self._scheduler_task = asyncio.create_task(
            self._market_scheduler(), name="market-scheduler"
        )

        await set_feed_status("running", {"mode": settings.KITE_MODE})
        log.info("engine_started", mode=settings.KITE_MODE)

    async def stop(self) -> None:
        self._running = False
        if self._scheduler_task:
            self._scheduler_task.cancel()
        if self._feed:
            await self._feed.stop()
        if self._writer:
            await self._writer.stop()
        if self._aggregator:
            self._aggregator.reset_all()
        await set_feed_status("stopped")
        log.info("engine_stopped")

    # ── Subscription management ───────────────────────────────────────────────

    async def subscribe(self, symbols: list[str]) -> dict[str, int]:
        """
        Subscribe to live feed for given NSE symbols.
        Returns {symbol: token} map for successfully subscribed symbols.
        """
        if not self._feed:
            raise RuntimeError("Engine not started.")

        registry = get_registry()
        token_map = registry.get_tokens(symbols)

        if not token_map:
            log.warning("subscribe_no_tokens_found", symbols=symbols)
            return {}

        await self._feed.subscribe(token_map)
        self._subscribed_symbols.update(token_map.keys())

        log.info("symbols_subscribed", count=len(token_map))
        return token_map

    async def unsubscribe(self, symbols: list[str]) -> None:
        if not self._feed:
            return

        registry = get_registry()
        token_map = registry.get_tokens(symbols)
        tokens = list(token_map.values())

        if tokens:
            await self._feed.unsubscribe(tokens)

        for sym in symbols:
            self._subscribed_symbols.discard(sym)
            if self._aggregator:
                self._aggregator.reset_symbol(sym)

        log.info("symbols_unsubscribed", count=len(symbols))

    # ── Tick handler ──────────────────────────────────────────────────────────

    async def _on_tick(self, tick: Tick) -> None:
        """Called for every validated tick from the feed."""
        if self._aggregator:
            await self._aggregator.process_tick(tick)

    # ── Candle completion handler ─────────────────────────────────────────────

    async def _on_candle_complete(self, candle: OHLCV) -> None:
        """Called when any (symbol, timeframe) candle closes."""
        data = candle.to_dict()

        # Publish to Redis pub/sub (strategy engine subscribes here)
        await publish_candle(data)

        # Cache current candle state in Redis
        await store_candle(candle.symbol, candle.timeframe.label, data)

        # Write to PostgreSQL (batched)
        if self._writer:
            await self._writer.write(candle)

        log.debug(
            "candle_complete",
            symbol=candle.symbol,
            timeframe=candle.timeframe.label,
            close=candle.close,
            volume=candle.volume,
        )

    # ── Market scheduler ──────────────────────────────────────────────────────

    async def _market_scheduler(self) -> None:
        """
        Handles market open/close lifecycle:
          - At market open: reset validator state, publish status
          - At market close: flush all writers, summarise day
          - Pre-open: warm up instrument registry
        """
        log.info("market_scheduler_started")
        while self._running:
            try:
                await self._check_market_state()
            except Exception as exc:
                log.error("scheduler_error", error=str(exc))
            await asyncio.sleep(30)   # check every 30 seconds

    async def _check_market_state(self) -> None:
        if is_market_open():
            await publish_status({"event": "market_open"})
        else:
            secs = seconds_to_market_open()
            if secs < 600:   # 10 minutes before open
                log.info("market_opening_soon", seconds=secs)
                # Refresh instrument registry
                await get_registry().load()
                # Reset aggregator state for clean candles
                if self._aggregator:
                    self._aggregator.reset_all()

    # ── State / health ────────────────────────────────────────────────────────

    @property
    def is_running(self) -> bool:
        return self._running

    @property
    def subscribed_count(self) -> int:
        return len(self._subscribed_symbols)

    def get_stats(self) -> dict:
        stats: dict = {
            "running": self._running,
            "mode": settings.KITE_MODE,
            "subscribed_symbols": self.subscribed_count,
        }
        if self._feed and hasattr(self._feed, "stats"):
            stats["feed"] = self._feed.stats  # type: ignore[attr-defined]
        if self._aggregator:
            stats["aggregator"] = {
                "active_candles": self._aggregator.active_candle_count,
                "active_symbols": self._aggregator.active_symbol_count,
            }
        if self._writer:
            stats["writer"] = {"buffer_depth": self._writer.buffer_depth}
        return stats


# ── Singleton ─────────────────────────────────────────────────────────────────
_engine: Optional[MarketDataEngine] = None


def get_engine() -> MarketDataEngine:
    if _engine is None:
        raise RuntimeError("MarketDataEngine not initialised. Call init_engine() first.")
    return _engine


def init_engine(session_factory: async_sessionmaker[AsyncSession]) -> MarketDataEngine:
    global _engine
    _engine = MarketDataEngine(session_factory)
    return _engine
