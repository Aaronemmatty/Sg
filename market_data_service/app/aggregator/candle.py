"""
Multi-timeframe candle aggregator.

Design:
  - Receives validated ticks
  - Maintains in-memory OHLCV state for every (symbol, timeframe) pair
  - When a candle period expires, marks it complete and emits it
  - 1m is the base; all higher TFs aggregate from the same tick stream
  - No disk I/O in this class — emits via callbacks
"""

from __future__ import annotations

import asyncio
import time
from collections import defaultdict
from typing import Callable, Awaitable

from app.core.calendar import candle_start_epoch
from app.core.config import get_settings
from app.core.logging import get_logger
from app.core.types import OHLCV, Tick, Timeframe

settings = get_settings()
log = get_logger(__name__)

# Candle-complete callback type
OnCandleComplete = Callable[[OHLCV], Awaitable[None]]


class CandleAggregator:
    """
    Stateful in-memory aggregator.
    Keyed by (symbol, timeframe_minutes) → OHLCV.
    """

    def __init__(self, on_complete: OnCandleComplete) -> None:
        self._on_complete = on_complete
        self._candles: dict[tuple[str, int], OHLCV] = {}
        self._last_volume: dict[str, int] = {}   # cumulative day volume per symbol
        self._timeframes = [Timeframe(tf) for tf in settings.AGGREGATION_TIMEFRAMES]

    async def process_tick(self, tick: Tick) -> None:
        now_s = int(tick.timestamp_ns / 1e9)

        # Compute delta volume (Kite sends cumulative day volume)
        last_vol = self._last_volume.get(tick.symbol, 0)
        delta_vol = max(0, tick.volume - last_vol)
        self._last_volume[tick.symbol] = tick.volume

        for tf in self._timeframes:
            await self._update_candle(tick, tf, now_s, delta_vol)

    async def _update_candle(
        self, tick: Tick, tf: Timeframe, now_s: int, delta_vol: int
    ) -> None:
        key = (tick.symbol, tf.value)
        candle_start = candle_start_epoch(now_s, tf.value)
        candle_end   = candle_start + tf.value * 60

        existing = self._candles.get(key)

        if existing is None:
            # First tick for this (symbol, timeframe)
            self._candles[key] = OHLCV.from_tick(tick, tf, candle_start)
            return

        if now_s >= existing.close_time:
            # Current tick is beyond the current candle — close it
            existing.is_complete = True
            completed = existing

            # Start new candle with current tick
            self._candles[key] = OHLCV.from_tick(tick, tf, candle_start)

            # Emit completed candle (non-blocking)
            asyncio.create_task(self._emit(completed))
        else:
            # Still inside the current candle — update it
            existing.update(tick, delta_vol)

    async def _emit(self, candle: OHLCV) -> None:
        try:
            await self._on_complete(candle)
        except Exception as exc:
            log.error("candle_emit_failed", symbol=candle.symbol,
                      timeframe=candle.timeframe.label, error=str(exc))

    def reset_symbol(self, symbol: str) -> None:
        """Drop all candle state for a symbol (e.g. at market open)."""
        for tf in self._timeframes:
            self._candles.pop((symbol, tf.value), None)
        self._last_volume.pop(symbol, None)

    def reset_all(self) -> None:
        self._candles.clear()
        self._last_volume.clear()
        log.info("aggregator_reset")

    def get_current_candle(self, symbol: str, timeframe: Timeframe) -> OHLCV | None:
        return self._candles.get((symbol, timeframe.value))

    @property
    def active_symbol_count(self) -> int:
        symbols = {key[0] for key in self._candles}
        return len(symbols)

    @property
    def active_candle_count(self) -> int:
        return len(self._candles)
