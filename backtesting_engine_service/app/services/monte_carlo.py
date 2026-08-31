from __future__ import annotations

import numpy as np

from app.core.logging import log
from app.core.metrics import MONTE_CARLO_ITERATIONS
from app.models.domain import (
    EquityPoint,
    MonteCarloConfig,
    MonteCarloPercentile,
    MonteCarloResult,
    PerformanceMetrics,
    SimulatedTrade,
)
from app.services.performance_engine import compute_performance


def _simulate_trade_reshuffle(
    pnl_series: np.ndarray, initial_capital: float, rng: np.random.Generator
) -> tuple[float, float, float, float]:
    """Randomly reorders the realized trade-by-trade P&L sequence and
    compounds it from initial capital.
    Returns (final_equity, total_return_pct, max_dd_pct, min_equity).
    """
    shuffled = rng.permutation(pnl_series)
    equity_path = initial_capital + np.cumsum(shuffled)
    full_path = np.concatenate([[initial_capital], equity_path])
    final_equity = float(equity_path[-1]) if len(equity_path) else initial_capital
    total_return_pct = (
        (final_equity - initial_capital) / initial_capital * 100 if initial_capital else 0.0
    )
    running_max = np.maximum.accumulate(full_path)
    drawdowns = np.where(running_max != 0, (full_path - running_max) / running_max, 0.0)
    max_dd_pct = float(drawdowns.min() * 100) if len(drawdowns) else 0.0
    min_equity = float(full_path.min())
    return final_equity, total_return_pct, max_dd_pct, min_equity


def _simulate_return_bootstrap(
    daily_returns: np.ndarray,
    initial_capital: float,
    rng: np.random.Generator,
    block_size: int | None = None,
) -> tuple[float, float, float, float]:
    n = len(daily_returns)
    if n == 0:
        return initial_capital, 0.0, 0.0, initial_capital

    if block_size and block_size > 1:
        n_blocks = int(np.ceil(n / block_size))
        starts = rng.integers(0, max(n - block_size, 1) + 1, size=n_blocks)
        sampled = np.concatenate(
            [daily_returns[s : s + block_size] for s in starts]
        )[:n]
    else:
        sampled = rng.choice(daily_returns, size=n, replace=True)

    equity_path = initial_capital * np.cumprod(1 + sampled)
    final_equity = float(equity_path[-1])
    total_return_pct = (
        (final_equity - initial_capital) / initial_capital * 100 if initial_capital else 0.0
    )
    full_path = np.concatenate([[initial_capital], equity_path])
    running_max = np.maximum.accumulate(full_path)
    drawdowns = np.where(running_max != 0, (full_path - running_max) / running_max, 0.0)
    max_dd_pct = float(drawdowns.min() * 100)
    min_equity = float(full_path.min())
    return final_equity, total_return_pct, max_dd_pct, min_equity


def run_monte_carlo(
    config: MonteCarloConfig,
    equity_curve: list[EquityPoint],
    trades: list[SimulatedTrade],
    initial_capital_inr: float,
) -> MonteCarloResult:
    original_metrics = compute_performance(equity_curve, trades, initial_capital_inr)

    rng = np.random.default_rng(config.random_seed)
    closed_pnls = np.array(
        [t.realized_pnl_inr for t in trades if t.realized_pnl_inr is not None], dtype=float
    )
    equity = np.array([p.equity_inr for p in equity_curve], dtype=float)
    daily_returns = (
        np.diff(equity) / equity[:-1] if len(equity) > 1 and np.all(equity[:-1] != 0) else np.array([])
    )

    final_equities: list[float] = []
    total_returns: list[float] = []
    max_drawdowns: list[float] = []
    ruin_count = 0

    for _ in range(config.iterations):
        if config.method == "trade_reshuffle" and len(closed_pnls) > 0:
            final_equity, total_return_pct, max_dd_pct, min_equity = _simulate_trade_reshuffle(
                closed_pnls, initial_capital_inr, rng
            )
        elif config.method == "block_bootstrap" and len(daily_returns) > 0:
            final_equity, total_return_pct, max_dd_pct, min_equity = _simulate_return_bootstrap(
                daily_returns, initial_capital_inr, rng, block_size=config.block_size
            )
        elif len(daily_returns) > 0:  # return_bootstrap (default fallback too)
            final_equity, total_return_pct, max_dd_pct, min_equity = _simulate_return_bootstrap(
                daily_returns, initial_capital_inr, rng
            )
        else:
            final_equity, total_return_pct, max_dd_pct, min_equity = (
                initial_capital_inr, 0.0, 0.0, initial_capital_inr,
            )

        final_equities.append(final_equity)
        total_returns.append(total_return_pct)
        max_drawdowns.append(max_dd_pct)
        if min_equity < initial_capital_inr * 0.5:
            ruin_count += 1
        MONTE_CARLO_ITERATIONS.inc()

    final_equities_arr = np.array(final_equities)
    total_returns_arr = np.array(total_returns)
    max_dd_arr = np.array(max_drawdowns)

    percentiles: list[MonteCarloPercentile] = []
    for cl in config.confidence_levels:
        pct = cl * 100
        percentiles.append(
            MonteCarloPercentile(
                confidence_level=cl,
                final_equity_inr=float(np.percentile(final_equities_arr, pct)),
                total_return_pct=float(np.percentile(total_returns_arr, pct)),
                max_drawdown_pct=float(np.percentile(max_dd_arr, pct)),
            )
        )

    probability_of_loss_pct = float(np.mean(total_returns_arr < 0) * 100)
    probability_of_ruin_pct = float(ruin_count / config.iterations * 100) if config.iterations else 0.0

    median_metrics = PerformanceMetrics(
        total_return_pct=float(np.median(total_returns_arr)),
        max_drawdown_pct=float(np.median(max_dd_arr)),
        num_trades=original_metrics.num_trades,
        final_equity_inr=float(np.median(final_equities_arr)),
    )

    log.info(
        "monte_carlo_complete",
        iterations=config.iterations,
        method=config.method,
        probability_of_loss_pct=probability_of_loss_pct,
        probability_of_ruin_pct=probability_of_ruin_pct,
    )

    return MonteCarloResult(
        iterations=config.iterations,
        method=config.method,
        percentiles=percentiles,
        probability_of_loss_pct=round(probability_of_loss_pct, 2),
        probability_of_ruin_pct=round(probability_of_ruin_pct, 2),
        original_metrics=original_metrics,
        median_metrics=median_metrics,
    )
