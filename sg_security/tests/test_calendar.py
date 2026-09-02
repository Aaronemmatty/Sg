"""Unit tests for shared NSE market calendar and session gating."""
from __future__ import annotations

from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

import pytest

from sg_security.calendar import (
    IST,
    MARKET_CLOSE,
    MARKET_OPEN,
    NSE_HOLIDAYS,
    ensure_ist,
    is_market_open,
    is_preopen,
    is_trading_day,
    seconds_to_market_open,
)


def test_trading_days_and_weekends():
    # 2026-03-02 is Monday (regular trading day)
    mon = datetime(2026, 3, 2, 10, 0, tzinfo=IST)
    assert is_trading_day(mon) is True

    # 2026-03-07 is Saturday
    sat = datetime(2026, 3, 7, 10, 0, tzinfo=IST)
    assert is_trading_day(sat) is False
    assert is_market_open(sat) is False

    # 2026-03-08 is Sunday
    sun = datetime(2026, 3, 8, 10, 0, tzinfo=IST)
    assert is_trading_day(sun) is False
    assert is_market_open(sun) is False


def test_nse_holidays():
    # 2026-01-26 (Republic Day) is Monday
    rep_day = datetime(2026, 1, 26, 10, 0, tzinfo=IST)
    assert is_trading_day(rep_day) is False
    assert is_market_open(rep_day) is False

    # 2025-08-15 (Independence Day) is Friday
    ind_day = datetime(2025, 8, 15, 11, 30, tzinfo=IST)
    assert is_trading_day(ind_day) is False
    assert is_market_open(ind_day) is False


def test_intraday_market_open_boundaries():
    # Regular trading day: Wednesday 2026-03-04
    # 09:14:59 IST -> Pre-open / Before continuous open (REJECTED)
    dt_0914 = datetime(2026, 3, 4, 9, 14, 59, tzinfo=IST)
    assert is_market_open(dt_0914) is False
    assert is_preopen(dt_0914) is True

    # 09:15:00 IST -> Exactly market open (ALLOWED)
    dt_0915 = datetime(2026, 3, 4, 9, 15, 0, tzinfo=IST)
    assert is_market_open(dt_0915) is True

    # 09:20:00 IST -> Mid-morning continuous trading (ALLOWED)
    dt_0920 = datetime(2026, 3, 4, 9, 20, 0, tzinfo=IST)
    assert is_market_open(dt_0920) is True

    # 15:30:00 IST -> Market closing boundary (ALLOWED)
    dt_1530 = datetime(2026, 3, 4, 15, 30, 0, tzinfo=IST)
    assert is_market_open(dt_1530) is True

    # 15:30:01 IST -> Post-close (REJECTED)
    dt_1530_01 = datetime(2026, 3, 4, 15, 30, 1, tzinfo=IST)
    assert is_market_open(dt_1530_01) is False

    # 15:31:00 IST -> Post-close (REJECTED)
    dt_1531 = datetime(2026, 3, 4, 15, 31, 0, tzinfo=IST)
    assert is_market_open(dt_1531) is False


def test_utc_to_ist_conversion():
    # 09:15 IST = 03:45 UTC
    utc_open = datetime(2026, 3, 4, 3, 45, 0, tzinfo=timezone.utc)
    assert is_market_open(utc_open) is True

    # 09:14 IST = 03:44 UTC (REJECTED)
    utc_before = datetime(2026, 3, 4, 3, 44, 0, tzinfo=timezone.utc)
    assert is_market_open(utc_before) is False

    # 15:30 IST = 10:00 UTC
    utc_close = datetime(2026, 3, 4, 10, 0, 0, tzinfo=timezone.utc)
    assert is_market_open(utc_close) is True

    # 15:31 IST = 10:01 UTC (REJECTED)
    utc_after = datetime(2026, 3, 4, 10, 1, 0, tzinfo=timezone.utc)
    assert is_market_open(utc_after) is False


def test_seconds_to_market_open():
    # At 09:00 IST on a trading day -> 15 minutes = 900 seconds
    dt = datetime(2026, 3, 4, 9, 0, 0, tzinfo=IST)
    sec = seconds_to_market_open(dt)
    assert sec == 900.0
