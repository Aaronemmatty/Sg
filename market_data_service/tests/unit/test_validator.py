"""Unit tests — TickValidator."""

from __future__ import annotations

import time

import pytest

from app.core.types import Tick
from app.validators.tick import TickValidator


def _tick(symbol: str, price: float, volume: int = 1000) -> Tick:
    return Tick(
        instrument_token=1,
        symbol=symbol,
        exchange="NSE",
        last_price=price,
        volume=volume,
        timestamp_ns=time.time_ns(),
    )


class TestTickValidator:
    def test_valid_tick_passes(self):
        v = TickValidator()
        result = v.validate(_tick("NSE:RELIANCE", 2950.0))
        assert result.valid is True

    def test_price_below_minimum_rejected(self):
        v = TickValidator()
        result = v.validate(_tick("NSE:TEST", 0.001))
        assert result.valid is False
        assert "minimum" in result.reason.lower()

    def test_negative_volume_rejected(self):
        v = TickValidator()
        t = _tick("NSE:TEST", 100.0, -1)
        result = v.validate(t)
        assert result.valid is False

    def test_price_spike_rejected(self):
        v = TickValidator()
        # Establish baseline
        v.validate(_tick("NSE:TEST", 100.0))
        # 50% spike — exceeds MAX_PRICE_DEVIATION_PCT (20%)
        result = v.validate(_tick("NSE:TEST", 150.0))
        assert result.valid is False
        assert "spike" in result.reason.lower()

    def test_small_price_move_accepted(self):
        v = TickValidator()
        v.validate(_tick("NSE:TEST", 100.0))
        # 2% move — within tolerance
        result = v.validate(_tick("NSE:TEST", 102.0))
        assert result.valid is True

    def test_reset_clears_last_price(self):
        v = TickValidator()
        v.validate(_tick("NSE:TEST", 100.0))
        v.reset_symbol("NSE:TEST")
        # After reset, even a large move should pass (no baseline)
        result = v.validate(_tick("NSE:TEST", 200.0))
        assert result.valid is True

    def test_rejection_counts_tracked(self):
        v = TickValidator()
        v.validate(_tick("NSE:TEST", 100.0))
        v.validate(_tick("NSE:TEST", 999.0))   # spike
        assert v.rejection_counts.get("NSE:TEST", 0) == 1

    def test_non_finite_price_rejected(self):
        v = TickValidator()
        t = _tick("NSE:TEST", float("inf"))
        result = v.validate(t)
        assert result.valid is False

    def test_nan_price_rejected(self):
        v = TickValidator()
        t = _tick("NSE:TEST", float("nan"))
        result = v.validate(t)
        assert result.valid is False
