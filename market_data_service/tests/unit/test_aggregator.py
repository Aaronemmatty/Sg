"""Unit tests — CandleAggregator."""

from __future__ import annotations

import asyncio
import time
from unittest.mock import AsyncMock

import pytest

from app.aggregator.candle import CandleAggregator
from app.core.types import OHLCV, Tick, Timeframe


def _make_tick(symbol: str, price: float, volume: int, ts_offset_s: int = 0) -> Tick:
    """Create a test tick at now + offset seconds."""
    base_ns = int(time.time()) * 1_000_000_000
    return Tick(
        instrument_token=12345,
        symbol=symbol,
        exchange="NSE",
        last_price=price,
        volume=volume,
        timestamp_ns=base_ns + ts_offset_s * 1_000_000_000,
    )


class TestCandleAggregator:
    @pytest.mark.asyncio
    async def test_first_tick_creates_candle(self):
        completed: list[OHLCV] = []

        async def on_complete(c: OHLCV):
            completed.append(c)

        agg = CandleAggregator(on_complete=on_complete)
        tick = _make_tick("NSE:RELIANCE", 2950.0, 1000)
        await agg.process_tick(tick)

        candle = agg.get_current_candle("NSE:RELIANCE", Timeframe.M1)
        assert candle is not None
        assert candle.open == 2950.0
        assert candle.high == 2950.0
        assert candle.low == 2950.0
        assert candle.close == 2950.0

    @pytest.mark.asyncio
    async def test_candle_high_low_update(self):
        completed: list[OHLCV] = []
        agg = CandleAggregator(on_complete=AsyncMock())

        base_ns = int(time.time()) * 1_000_000_000
        # All ticks within the same minute
        for price, vol in [(100.0, 500), (105.0, 300), (98.0, 200), (102.0, 400)]:
            t = Tick("NSE:TEST", "NSE", "NSE:TEST", price, vol, base_ns)
            t.symbol = "NSE:TEST"
            t.exchange = "NSE"
            t.last_price = price
            t.volume = vol
            t.timestamp_ns = base_ns
            await agg.process_tick(t)

        candle = agg.get_current_candle("NSE:TEST", Timeframe.M1)
        assert candle is not None
        assert candle.high == 105.0
        assert candle.low == 98.0

    @pytest.mark.asyncio
    async def test_candle_completion_on_new_period(self):
        completed: list[OHLCV] = []

        async def on_complete(c: OHLCV):
            completed.append(c)

        agg = CandleAggregator(on_complete=on_complete)

        # Tick at now (inside minute N)
        now_s = int(time.time())
        period = 60
        candle_start_now = (now_s // period) * period
        candle_start_next = candle_start_now + period + 5  # into next minute

        t1 = Tick(1, "NSE:X", "NSE", 100.0, 500, candle_start_now * 1_000_000_000)
        t2 = Tick(1, "NSE:X", "NSE", 101.0, 600, candle_start_next * 1_000_000_000)

        await agg.process_tick(t1)
        await asyncio.sleep(0.01)   # allow task to run
        await agg.process_tick(t2)
        await asyncio.sleep(0.01)

        assert len(completed) == 1
        assert completed[0].close == 100.0
        assert completed[0].is_complete is True

    @pytest.mark.asyncio
    async def test_reset_all_clears_state(self):
        agg = CandleAggregator(on_complete=AsyncMock())
        tick = _make_tick("NSE:RELIANCE", 2950.0, 1000)
        await agg.process_tick(tick)

        assert agg.active_symbol_count > 0
        agg.reset_all()
        assert agg.active_symbol_count == 0
        assert agg.active_candle_count == 0

    @pytest.mark.asyncio
    async def test_multiple_timeframes_independent(self):
        agg = CandleAggregator(on_complete=AsyncMock())
        tick = _make_tick("NSE:TCS", 3800.0, 200)
        await agg.process_tick(tick)

        # Should have a candle for each configured timeframe
        from app.core.config import get_settings
        settings = get_settings()
        for tf_min in settings.AGGREGATION_TIMEFRAMES:
            candle = agg.get_current_candle("NSE:TCS", Timeframe(tf_min))
            assert candle is not None, f"Missing candle for {tf_min}m"
