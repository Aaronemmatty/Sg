"""Unit tests — NSE market calendar."""

from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo

import pytest
from freezegun import freeze_time

from app.core.calendar import (
    candle_start_epoch,
    is_market_open,
    is_preopen,
    is_trading_day,
    seconds_to_market_open,
)

IST = ZoneInfo("Asia/Kolkata")


class TestTradingDay:
    def test_weekday_is_trading_day(self):
        assert is_trading_day(date(2025, 3, 3)) is True   # Monday

    def test_saturday_not_trading_day(self):
        assert is_trading_day(date(2025, 3, 1)) is False  # Saturday

    def test_sunday_not_trading_day(self):
        assert is_trading_day(date(2025, 3, 2)) is False  # Sunday

    def test_nse_holiday_not_trading_day(self):
        assert is_trading_day(date(2025, 8, 15)) is False  # Independence Day


class TestMarketOpen:
    @freeze_time("2025-03-03 09:20:00", tz_offset=5.5)
    def test_market_open_during_session(self):
        # 09:20 IST on a Monday — market is open
        now = datetime(2025, 3, 3, 9, 20, tzinfo=IST)
        assert is_market_open(now) is True

    @freeze_time("2025-03-03 09:10:00", tz_offset=5.5)
    def test_market_closed_before_open(self):
        now = datetime(2025, 3, 3, 9, 10, tzinfo=IST)
        assert is_market_open(now) is False

    def test_market_closed_after_close(self):
        now = datetime(2025, 3, 3, 15, 35, tzinfo=IST)
        assert is_market_open(now) is False

    def test_market_closed_on_weekend(self):
        now = datetime(2025, 3, 1, 10, 0, tzinfo=IST)   # Saturday
        assert is_market_open(now) is False


class TestPreOpen:
    def test_preopen_session(self):
        now = datetime(2025, 3, 3, 9, 5, tzinfo=IST)
        assert is_preopen(now) is True

    def test_not_preopen_during_market(self):
        now = datetime(2025, 3, 3, 9, 30, tzinfo=IST)
        assert is_preopen(now) is False


class TestCandleStartEpoch:
    def test_1m_alignment(self):
        # 09:17:43 → should align to 09:17:00
        dt = datetime(2025, 3, 3, 9, 17, 43, tzinfo=IST)
        epoch = int(dt.timestamp())
        start = candle_start_epoch(epoch, 1)
        aligned = datetime.fromtimestamp(start, tz=IST)
        assert aligned.second == 0
        assert aligned.minute == 17

    def test_5m_alignment(self):
        dt = datetime(2025, 3, 3, 9, 22, 30, tzinfo=IST)
        epoch = int(dt.timestamp())
        start = candle_start_epoch(epoch, 5)
        aligned = datetime.fromtimestamp(start, tz=IST)
        assert aligned.minute % 5 == 0

    def test_15m_alignment(self):
        dt = datetime(2025, 3, 3, 9, 28, 0, tzinfo=IST)
        epoch = int(dt.timestamp())
        start = candle_start_epoch(epoch, 15)
        aligned = datetime.fromtimestamp(start, tz=IST)
        assert aligned.minute % 15 == 0
