from __future__ import annotations

import numpy as np

from app.models.domain import EquityPoint, PerformanceMetrics, SimulatedTrade

TRADING_DAYS_PER_YEAR = 252
RISK_FREE_RATE = 0.0


def _daily_returns(equity: np.ndarray) -> np.ndarray:
    if len(equity) < 2:
        return np.array([])
    prev = equity[:-1]
    cur = equity[1:]
    with np.errstate(divide="ignore", invalid="ignore"):
        rets = np.where(prev != 0, (cur - prev) / prev, 0.0)
    return rets


def _max_drawdown(equity: np.ndarray) -> tuple[float, int]:
    if len(equity) == 0:
        return 0.0, 0
    running_max = np.maximum.accumulate(equity)
    drawdowns = np.where(running_max != 0, (equity - running_max) / running_max, 0.0)
    max_dd_pct = float(drawdowns.min() * 100) if len(drawdowns) else 0.0

    # Longest run (in bars) spent at/under the trough's preceding peak.
    duration = 0
    longest = 0
    for dd in drawdowns:
        if dd < 0:
            duration += 1
            longest = max(longest, duration)
        else:
            duration = 0
    return max_dd_pct, longest


def compute_performance(
    equity_curve: list[EquityPoint],
    trades: list[SimulatedTrade],
    initial_capital_inr: float,
    bars_per_year: int = TRADING_DAYS_PER_YEAR,
) -> PerformanceMetrics:
    if not equity_curve:
        return PerformanceMetrics(
            total_return_pct=0.0, max_drawdown_pct=0.0, final_equity_inr=initial_capital_inr
        )

    equity = np.array([p.equity_inr for p in equity_curve], dtype=float)
    final_equity = float(equity[-1])
    total_return_pct = (
        (final_equity - initial_capital_inr) / initial_capital_inr * 100
        if initial_capital_inr
        else 0.0
    )

    n_bars = len(equity)
    years = max(n_bars / bars_per_year, 1e-9)
    cagr_pct = (
        ((final_equity / initial_capital_inr) ** (1 / years) - 1) * 100
        if initial_capital_inr > 0 and final_equity > 0
        else None
    )

    rets = _daily_returns(equity)
    volatility_annualized_pct = (
        float(np.std(rets, ddof=1) * np.sqrt(bars_per_year) * 100) if len(rets) > 1 else None
    )

    sharpe = None
    sortino = None
    if len(rets) > 1 and np.std(rets, ddof=1) > 0:
        excess = rets - RISK_FREE_RATE / bars_per_year
        sharpe = float(np.mean(excess) / np.std(rets, ddof=1) * np.sqrt(bars_per_year))
        downside = rets[rets < 0]
        if len(downside) > 1 and np.std(downside, ddof=1) > 0:
            sortino = float(np.mean(excess) / np.std(downside, ddof=1) * np.sqrt(bars_per_year))

    max_dd_pct, max_dd_duration = _max_drawdown(equity)
    calmar = (
        float(cagr_pct / abs(max_dd_pct)) if cagr_pct is not None and max_dd_pct < 0 else None
    )

    closed = [t for t in trades if t.realized_pnl_inr is not None]
    num_trades = len(closed)
    wins = [t.realized_pnl_inr for t in closed if t.realized_pnl_inr and t.realized_pnl_inr > 0]
    losses = [t.realized_pnl_inr for t in closed if t.realized_pnl_inr and t.realized_pnl_inr <= 0]
    win_rate_pct = (len(wins) / num_trades * 100) if num_trades else None
    gross_profit = sum(wins) if wins else 0.0
    gross_loss = abs(sum(losses)) if losses else 0.0
    if gross_loss > 0:
        profit_factor: float | None = gross_profit / gross_loss
    elif wins:
        # No losing trades at all — profit factor is unbounded. Cap it to a
        # large finite sentinel so the value stays valid JSON for API consumers.
        profit_factor = 9999.0
    else:
        profit_factor = None
    avg_win = float(np.mean(wins)) if wins else None
    avg_loss = float(np.mean(losses)) if losses else None
    expectancy = (
        (sum(t.realized_pnl_inr for t in closed) / num_trades) if num_trades else None
    )

    alpha_pct = None
    beta = None
    information_ratio = None
    benchmark_equity = [p.benchmark_equity_inr for p in equity_curve]
    if all(b is not None for b in benchmark_equity) and len(benchmark_equity) > 1:
        bench = np.array(benchmark_equity, dtype=float)
        bench_rets = _daily_returns(bench)
        if len(bench_rets) == len(rets) and len(bench_rets) > 1 and np.var(bench_rets) > 0:
            beta = float(np.cov(rets, bench_rets)[0, 1] / np.var(bench_rets))
            bench_total_return = (bench[-1] - bench[0]) / bench[0] * 100 if bench[0] else 0.0
            alpha_pct = float(total_return_pct - beta * bench_total_return)
            active_returns = rets - bench_rets
            tracking_error = np.std(active_returns, ddof=1)
            if tracking_error > 0:
                information_ratio = float(
                    np.mean(active_returns) / tracking_error * np.sqrt(bars_per_year)
                )

    return PerformanceMetrics(
        total_return_pct=round(total_return_pct, 4),
        cagr_pct=round(cagr_pct, 4) if cagr_pct is not None else None,
        sharpe_ratio=round(sharpe, 4) if sharpe is not None else None,
        sortino_ratio=round(sortino, 4) if sortino is not None else None,
        calmar_ratio=round(calmar, 4) if calmar is not None else None,
        max_drawdown_pct=round(max_dd_pct, 4),
        max_drawdown_duration_days=max_dd_duration,
        volatility_annualized_pct=(
            round(volatility_annualized_pct, 4) if volatility_annualized_pct is not None else None
        ),
        win_rate_pct=round(win_rate_pct, 2) if win_rate_pct is not None else None,
        profit_factor=round(profit_factor, 4) if profit_factor is not None else None,
        avg_win_inr=round(avg_win, 2) if avg_win is not None else None,
        avg_loss_inr=round(avg_loss, 2) if avg_loss is not None else None,
        expectancy_inr=round(expectancy, 2) if expectancy is not None else None,
        num_trades=num_trades,
        alpha_pct=round(alpha_pct, 4) if alpha_pct is not None else None,
        beta=round(beta, 4) if beta is not None else None,
        information_ratio=round(information_ratio, 4) if information_ratio is not None else None,
        final_equity_inr=round(final_equity, 2),
    )
