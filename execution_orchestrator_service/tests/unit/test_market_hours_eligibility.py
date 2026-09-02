"""Unit tests for market hours eligibility check in execution_orchestrator_service."""
from __future__ import annotations

from datetime import datetime, timezone
import pytest

from app.models.domain import AggregatedSignal, PortfolioState, RejectionReason, RiskState, TradeAction
from app.orchestrator.eligibility import check_market_hours, run_all_checks
from sg_security.calendar import IST


def _dummy_signal():
    return AggregatedSignal(
        symbol="RELIANCE",
        timeframe="5m",
        final_signal=TradeAction.BUY,
        confidence=0.85,
        contributors=["trend_following"],
        timestamp=datetime.now(timezone.utc),
    )


def _dummy_portfolio():
    return PortfolioState(
        portfolio_id="p-1",
        as_of=datetime.now(timezone.utc),
        total_value_inr=10000.0,
        cash_inr=5000.0,
        equity_inr=5000.0,
        day_pnl_inr=0.0,
        total_pnl_inr=0.0,
        unrealized_pnl_inr=0.0,
        realized_pnl_inr=0.0,
        positions=[],
    )


def _dummy_risk():
    return RiskState(
        portfolio_id="p-1",
        as_of=datetime.now(timezone.utc),
        daily_loss_inr=0.0,
        daily_loss_limit_inr=200.0,
        drawdown_pct=0.01,
        max_drawdown_pct=0.05,
        open_intents_count=0,
        correlation_matrix={},
    )


@pytest.mark.asyncio
async def test_market_hours_check_at_0914_rejected():
    dt_0914 = datetime(2026, 3, 4, 9, 14, 59, tzinfo=IST)
    res = await check_market_hours(dt_0914)
    assert res.passed is False
    assert res.reason == RejectionReason.MARKET_CLOSED


@pytest.mark.asyncio
async def test_market_hours_check_at_0915_allowed():
    dt_0915 = datetime(2026, 3, 4, 9, 15, 0, tzinfo=IST)
    res = await check_market_hours(dt_0915)
    assert res.passed is True
    assert res.reason is None


@pytest.mark.asyncio
async def test_market_hours_check_at_1530_allowed():
    dt_1530 = datetime(2026, 3, 4, 15, 30, 0, tzinfo=IST)
    res = await check_market_hours(dt_1530)
    assert res.passed is True
    assert res.reason is None


@pytest.mark.asyncio
async def test_market_hours_check_at_1531_rejected():
    dt_1531 = datetime(2026, 3, 4, 15, 31, 0, tzinfo=IST)
    res = await check_market_hours(dt_1531)
    assert res.passed is False
    assert res.reason == RejectionReason.MARKET_CLOSED


@pytest.mark.asyncio
async def test_market_hours_check_on_weekend_rejected():
    dt_sat = datetime(2026, 3, 7, 12, 0, 0, tzinfo=IST)
    res = await check_market_hours(dt_sat)
    assert res.passed is False
    assert res.reason == RejectionReason.MARKET_CLOSED


@pytest.mark.asyncio
async def test_market_hours_check_on_holiday_rejected():
    dt_hol = datetime(2026, 1, 26, 12, 0, 0, tzinfo=IST)
    res = await check_market_hours(dt_hol)
    assert res.passed is False
    assert res.reason == RejectionReason.MARKET_CLOSED


@pytest.mark.asyncio
async def test_run_all_checks_captures_market_closed_reason():
    signal = _dummy_signal()
    portfolio = _dummy_portfolio()
    risk = _dummy_risk()
    dt_closed = datetime(2026, 3, 4, 17, 0, 0, tzinfo=IST)

    results = await run_all_checks(signal, portfolio, risk, now_dt=dt_closed)
    market_check = next(r for r in results if r.check_name == "market_hours")
    assert market_check.passed is False
    assert market_check.reason == RejectionReason.MARKET_CLOSED
