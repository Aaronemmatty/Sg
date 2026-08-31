from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest

from app.models.domain import EquityPoint, OrderAction, SimulatedTrade
from app.services.performance_engine import compute_performance


def _equity_curve(values: list[float]) -> list[EquityPoint]:
    start = datetime(2024, 1, 1, tzinfo=timezone.utc)
    return [
        EquityPoint(
            ts=start + timedelta(days=i),
            equity_inr=v,
            cash_inr=v,
            drawdown_pct=0.0,
        )
        for i, v in enumerate(values)
    ]


def _trade(pnl: float, pct: float) -> SimulatedTrade:
    return SimulatedTrade(
        trade_id=uuid.uuid4(),
        symbol="RELIANCE",
        action=OrderAction.BUY,
        entry_ts=datetime(2024, 1, 1, tzinfo=timezone.utc),
        entry_price_inr=100.0,
        exit_ts=datetime(2024, 1, 2, tzinfo=timezone.utc),
        exit_price_inr=100.0 + pnl,
        quantity=1.0,
        realized_pnl_inr=pnl,
        realized_pnl_pct=pct,
    )


def test_empty_equity_curve_returns_zero_metrics():
    metrics = compute_performance([], [], 1_000_000.0)
    assert metrics.total_return_pct == 0.0
    assert metrics.max_drawdown_pct == 0.0
    assert metrics.final_equity_inr == 1_000_000.0


def test_monotonic_growth_has_zero_drawdown_and_positive_return():
    curve = _equity_curve([100_000, 105_000, 110_000, 120_000])
    metrics = compute_performance(curve, [], 100_000.0)
    assert metrics.total_return_pct == pytest.approx(20.0, abs=0.01)
    assert metrics.max_drawdown_pct == pytest.approx(0.0, abs=0.01)
    assert metrics.final_equity_inr == 120_000.0


def test_drawdown_detected_after_peak():
    curve = _equity_curve([100_000, 120_000, 90_000, 95_000])
    metrics = compute_performance(curve, [], 100_000.0)
    # Drawdown from peak 120_000 to trough 90_000 = -25%
    assert metrics.max_drawdown_pct == pytest.approx(-25.0, abs=0.01)


def test_win_rate_and_profit_factor():
    trades = [_trade(100.0, 1.0), _trade(-50.0, -0.5), _trade(200.0, 2.0)]
    curve = _equity_curve([100_000, 100_100, 100_050, 100_250])
    metrics = compute_performance(curve, trades, 100_000.0)
    assert metrics.num_trades == 3
    assert metrics.win_rate_pct == pytest.approx(2 / 3 * 100, abs=0.01)
    assert metrics.profit_factor == pytest.approx(300.0 / 50.0, abs=0.01)


def test_sharpe_is_none_for_flat_returns():
    curve = _equity_curve([100_000, 100_000, 100_000, 100_000])
    metrics = compute_performance(curve, [], 100_000.0)
    assert metrics.sharpe_ratio is None
