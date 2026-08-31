from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from app.models.domain import (
    EquityPoint,
    MonteCarloConfig,
    OrderAction,
    SimulatedTrade,
)
from app.services.monte_carlo import run_monte_carlo


def _equity_curve(values: list[float]) -> list[EquityPoint]:
    start = datetime(2024, 1, 1, tzinfo=timezone.utc)
    return [
        EquityPoint(ts=start + timedelta(days=i), equity_inr=v, cash_inr=v, drawdown_pct=0.0)
        for i, v in enumerate(values)
    ]


def _trade(pnl: float) -> SimulatedTrade:
    return SimulatedTrade(
        trade_id=uuid.uuid4(),
        symbol="TEST",
        action=OrderAction.BUY,
        entry_ts=datetime(2024, 1, 1, tzinfo=timezone.utc),
        entry_price_inr=100.0,
        exit_ts=datetime(2024, 1, 2, tzinfo=timezone.utc),
        exit_price_inr=100.0 + pnl,
        quantity=1.0,
        realized_pnl_inr=pnl,
        realized_pnl_pct=pnl,
    )


def test_monte_carlo_trade_reshuffle_is_deterministic_with_seed():
    trades = [_trade(100), _trade(-50), _trade(200), _trade(-30)]
    curve = _equity_curve([100_000, 100_100, 100_050, 100_250, 100_220])
    config = MonteCarloConfig(iterations=500, method="trade_reshuffle", random_seed=42)

    result_a = run_monte_carlo(config, curve, trades, 100_000.0)
    result_b = run_monte_carlo(config, curve, trades, 100_000.0)

    assert result_a.percentiles == result_b.percentiles
    assert result_a.iterations == 500
    assert 0 <= result_a.probability_of_loss_pct <= 100
    assert 0 <= result_a.probability_of_ruin_pct <= 100


def test_monte_carlo_reshuffle_preserves_total_pnl_distribution_mean():
    # Reshuffling order never changes the sum of trade P&Ls, only the path —
    # so the median final equity should land close to the deterministic sum.
    trades = [_trade(1000), _trade(1000), _trade(1000)]
    curve = _equity_curve([100_000, 101_000, 102_000, 103_000])
    config = MonteCarloConfig(iterations=1000, method="trade_reshuffle", random_seed=7)

    result = run_monte_carlo(config, curve, trades, 100_000.0)
    assert result.median_metrics.final_equity_inr == 103_000.0


def test_monte_carlo_return_bootstrap_runs_without_trades():
    curve = _equity_curve([100_000, 102_000, 99_000, 101_000, 103_000])
    config = MonteCarloConfig(iterations=300, method="return_bootstrap", random_seed=1)

    result = run_monte_carlo(config, curve, [], 100_000.0)
    assert result.iterations == 300
    assert len(result.percentiles) == 5


def test_monte_carlo_handles_zero_trades_and_flat_curve_gracefully():
    curve = _equity_curve([100_000, 100_000, 100_000])
    config = MonteCarloConfig(iterations=100, method="trade_reshuffle", random_seed=3)

    result = run_monte_carlo(config, curve, [], 100_000.0)
    assert result.probability_of_loss_pct == 0.0
    assert result.probability_of_ruin_pct == 0.0
