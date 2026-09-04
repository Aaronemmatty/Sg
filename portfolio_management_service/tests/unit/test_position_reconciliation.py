"""
Unit tests for Position-Book Reconciliation Engine.

Covers:
  1. Matching positions between internal book and broker (no halt triggered).
  2. Quantity mismatch on one symbol (halt triggered, correct symbol/qty reported).
  3. Symbol present in broker but missing internally (halt triggered).
  4. Symbol present internally but missing in broker (halt triggered).
  5. Calendar schedule triggers (market open 09:15, hourly, market close 15:30).
"""
from __future__ import annotations

from datetime import date, datetime, time, timezone
from unittest.mock import AsyncMock, patch

import pytest

from app.services.position_reconciliation import (
    MismatchType,
    PositionMismatch,
    PositionReconciliationScheduler,
    diff_positions,
    normalize_symbol,
    reconcile_positions,
)
from sg_security.calendar import IST


def test_normalize_symbol():
    assert normalize_symbol("NSE:RELIANCE") == "RELIANCE"
    assert normalize_symbol("BSE:TATASTEEL") == "TATASTEEL"
    assert normalize_symbol("infy") == "INFY"


def test_diff_positions_matching():
    internal = {"RELIANCE": 10, "TATASTEEL": 50}
    broker = {"NSE:RELIANCE": 10, "TATASTEEL": 50}

    mismatches = diff_positions(internal, broker)
    assert len(mismatches) == 0


def test_diff_positions_quantity_mismatch():
    internal = {"RELIANCE": 10, "INFY": 25}
    broker = {"NSE:RELIANCE": 10, "NSE:INFY": 30}

    mismatches = diff_positions(internal, broker)
    assert len(mismatches) == 1
    m = mismatches[0]
    assert m.symbol == "INFY"
    assert m.internal_qty == 25
    assert m.broker_qty == 30
    assert m.mismatch_type == MismatchType.QUANTITY_MISMATCH


def test_diff_positions_missing_internally():
    internal = {"RELIANCE": 10}
    broker = {"NSE:RELIANCE": 10, "NSE:WIPRO": 100}

    mismatches = diff_positions(internal, broker)
    assert len(mismatches) == 1
    m = mismatches[0]
    assert m.symbol == "WIPRO"
    assert m.internal_qty == 0
    assert m.broker_qty == 100
    assert m.mismatch_type == MismatchType.MISSING_INTERNALLY


def test_diff_positions_missing_in_broker():
    internal = {"RELIANCE": 10, "ITC": 200}
    broker = {"NSE:RELIANCE": 10}

    mismatches = diff_positions(internal, broker)
    assert len(mismatches) == 1
    m = mismatches[0]
    assert m.symbol == "ITC"
    assert m.internal_qty == 200
    assert m.broker_qty == 0
    assert m.mismatch_type == MismatchType.MISSING_IN_BROKER


@pytest.mark.asyncio
async def test_matching_positions_no_halt_triggered():
    internal = {"RELIANCE": 15, "HDFCBANK": 40}
    broker = {"NSE:RELIANCE": 15, "NSE:HDFCBANK": 40}

    with patch(
        "app.services.position_reconciliation.trigger_kill_switch",
        new=AsyncMock(return_value=False),
    ) as mock_halt:
        result = await reconcile_positions(
            internal_positions=internal,
            broker_positions=broker,
            trigger_halt_on_mismatch=True,
        )

        assert result.matched is True
        assert result.halt_triggered is False
        assert len(result.mismatches) == 0
        assert set(result.checked_symbols) == {"RELIANCE", "HDFCBANK"}
        mock_halt.assert_not_called()


@pytest.mark.asyncio
async def test_quantity_mismatch_triggers_halt():
    internal = {"RELIANCE": 10, "INFY": 25}
    broker = {"NSE:RELIANCE": 10, "NSE:INFY": 30}

    with patch(
        "app.services.position_reconciliation.trigger_kill_switch",
        new=AsyncMock(return_value=True),
    ) as mock_halt:
        result = await reconcile_positions(
            internal_positions=internal,
            broker_positions=broker,
            trigger_halt_on_mismatch=True,
        )

        assert result.matched is False
        assert result.halt_triggered is True
        assert len(result.mismatches) == 1
        m = result.mismatches[0]
        assert m.symbol == "INFY"
        assert m.internal_qty == 25
        assert m.broker_qty == 30
        assert m.mismatch_type == MismatchType.QUANTITY_MISMATCH

        mock_halt.assert_awaited_once()
        reason_arg = mock_halt.call_args[1]["reason"]
        assert "INFY" in reason_arg
        assert "internal=25" in reason_arg
        assert "broker=30" in reason_arg


@pytest.mark.asyncio
async def test_missing_internally_triggers_halt():
    internal = {"RELIANCE": 10}
    broker = {"NSE:RELIANCE": 10, "NSE:WIPRO": 100}

    with patch(
        "app.services.position_reconciliation.trigger_kill_switch",
        new=AsyncMock(return_value=True),
    ) as mock_halt:
        result = await reconcile_positions(
            internal_positions=internal,
            broker_positions=broker,
            trigger_halt_on_mismatch=True,
        )

        assert result.matched is False
        assert result.halt_triggered is True
        assert len(result.mismatches) == 1
        m = result.mismatches[0]
        assert m.symbol == "WIPRO"
        assert m.internal_qty == 0
        assert m.broker_qty == 100
        assert m.mismatch_type == MismatchType.MISSING_INTERNALLY

        mock_halt.assert_awaited_once()
        reason_arg = mock_halt.call_args[1]["reason"]
        assert "WIPRO" in reason_arg
        assert "MISSING_INTERNALLY" in reason_arg


def test_scheduler_market_hours_triggers():
    scheduler = PositionReconciliationScheduler([
        time(9, 15),
        time(10, 15),
        time(15, 30),
    ])

    # 1. Non-trading day (Sunday: 2026-09-06)
    sunday_open = datetime(2026, 9, 6, 9, 20, tzinfo=IST)
    assert scheduler.should_trigger(sunday_open) == []

    # 2. Trading day before open (09:10 IST on Wednesday 2026-09-02)
    trading_preopen = datetime(2026, 9, 2, 9, 10, tzinfo=IST)
    assert scheduler.should_trigger(trading_preopen) == []

    # 3. Market Open (09:16 IST)
    trading_open = datetime(2026, 9, 2, 9, 16, tzinfo=IST)
    due = scheduler.should_trigger(trading_open)
    assert due == [time(9, 15)]

    scheduler.mark_executed(time(9, 15))
    assert scheduler.should_trigger(trading_open) == []

    # 4. Hourly checkpoint (10:20 IST)
    trading_hourly = datetime(2026, 9, 2, 10, 20, tzinfo=IST)
    due_hourly = scheduler.should_trigger(trading_hourly)
    assert due_hourly == [time(10, 15)]
    scheduler.mark_executed(time(10, 15))

    # 5. Market Close (15:35 IST)
    trading_close = datetime(2026, 9, 2, 15, 35, tzinfo=IST)
    due_close = scheduler.should_trigger(trading_close)
    assert due_close == [time(15, 30)]
    scheduler.mark_executed(time(15, 30))
    assert scheduler.should_trigger(trading_close) == []
