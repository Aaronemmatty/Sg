from __future__ import annotations

from datetime import date, timedelta

import pandas as pd

from app.core.logging import log
from app.core.metrics import WALK_FORWARD_WINDOWS
from app.models.domain import (
    BacktestConfig,
    PerformanceMetrics,
    WalkForwardConfig,
    WalkForwardResult,
    WalkForwardWindowResult,
)
from app.services.backtest_engine import BacktestEngine
from app.services.performance_engine import compute_performance
from app.services.strategy_loader import SignalProvider, build_signal_provider


def _slice_bars(df: pd.DataFrame, start: date, end: date) -> pd.DataFrame:
    mask = (df["ts"].dt.date >= start) & (df["ts"].dt.date <= end)
    return df.loc[mask].reset_index(drop=True)


async def run_walk_forward(
    config: BacktestConfig,
    wf_config: WalkForwardConfig,
    bars_by_symbol: dict[str, pd.DataFrame],
    benchmark_df: pd.DataFrame | None,
) -> WalkForwardResult:
    """Rolling (or anchored/expanding) window walk-forward analysis.

    NOTE — scope limitation: this service does not perform parameter
    optimisation on the train window (no optimiser is wired up yet). The
    in-sample metrics are the same strategy config evaluated on the train
    slice, giving a baseline to compare against out-of-sample performance —
    i.e. this measures robustness/consistency across time, not overfitting
    from re-fit parameters. A future optimiser hook can slot in here.
    """
    windows: list[WalkForwardWindowResult] = []

    overall_start = config.start_date
    overall_end = config.end_date

    window_index = 0
    train_start = overall_start
    train_window_days = wf_config.train_window_days

    while True:
        train_end = train_start + timedelta(days=train_window_days)
        test_start = train_end + timedelta(days=1)
        test_end = test_start + timedelta(days=wf_config.test_window_days)

        if test_end > overall_end:
            break

        train_bars = {sym: _slice_bars(df, train_start, train_end) for sym, df in bars_by_symbol.items()}
        test_bars = {sym: _slice_bars(df, test_start, test_end) for sym, df in bars_by_symbol.items()}

        in_sample_metrics = await _run_slice(config, train_bars, benchmark_df, train_start, train_end)
        out_sample_metrics = await _run_slice(config, test_bars, benchmark_df, test_start, test_end)

        windows.append(
            WalkForwardWindowResult(
                window_index=window_index,
                train_start=train_start,
                train_end=train_end,
                test_start=test_start,
                test_end=test_end,
                in_sample_metrics=in_sample_metrics,
                out_sample_metrics=out_sample_metrics,
            )
        )
        WALK_FORWARD_WINDOWS.inc()
        window_index += 1

        if wf_config.anchored:
            # Expanding window: train_start stays fixed, train window grows.
            train_window_days += wf_config.step_days
        else:
            # Rolling window: train_start advances, window size fixed.
            train_start = train_start + timedelta(days=wf_config.step_days)

    if not windows:
        log.warning(
            "walk_forward_no_windows_fit",
            start=overall_start.isoformat(),
            end=overall_end.isoformat(),
        )
        empty = PerformanceMetrics(total_return_pct=0.0, max_drawdown_pct=0.0)
        return WalkForwardResult(windows=[], aggregate_out_sample_metrics=empty, consistency_score_pct=0.0)

    positive_oos = sum(1 for w in windows if w.out_sample_metrics.total_return_pct > 0)
    consistency_score_pct = positive_oos / len(windows) * 100

    aggregate = _aggregate_metrics([w.out_sample_metrics for w in windows])

    return WalkForwardResult(
        windows=windows,
        aggregate_out_sample_metrics=aggregate,
        consistency_score_pct=round(consistency_score_pct, 2),
    )


async def _run_slice(
    config: BacktestConfig,
    bars_by_symbol: dict[str, pd.DataFrame],
    benchmark_df: pd.DataFrame | None,
    slice_start: date,
    slice_end: date,
) -> PerformanceMetrics:
    if all(df.empty for df in bars_by_symbol.values()):
        return PerformanceMetrics(total_return_pct=0.0, max_drawdown_pct=0.0)

    provider: SignalProvider = build_signal_provider(config.strategy)
    try:
        for sym, df in bars_by_symbol.items():
            if not df.empty:
                await provider.prepare(sym, df)

        engine = BacktestEngine(config)
        trades, equity_curve = engine.run(bars_by_symbol, provider, benchmark_df)
        return compute_performance(equity_curve, trades, config.initial_capital_inr)
    finally:
        await provider.aclose()


def _aggregate_metrics(metrics_list: list[PerformanceMetrics]) -> PerformanceMetrics:
    if not metrics_list:
        return PerformanceMetrics(total_return_pct=0.0, max_drawdown_pct=0.0)

    def avg(attr: str) -> float | None:
        vals = [getattr(m, attr) for m in metrics_list if getattr(m, attr) is not None]
        return round(sum(vals) / len(vals), 4) if vals else None

    return PerformanceMetrics(
        total_return_pct=avg("total_return_pct") or 0.0,
        cagr_pct=avg("cagr_pct"),
        sharpe_ratio=avg("sharpe_ratio"),
        sortino_ratio=avg("sortino_ratio"),
        calmar_ratio=avg("calmar_ratio"),
        max_drawdown_pct=min((m.max_drawdown_pct for m in metrics_list), default=0.0),
        volatility_annualized_pct=avg("volatility_annualized_pct"),
        win_rate_pct=avg("win_rate_pct"),
        profit_factor=avg("profit_factor"),
        num_trades=sum(m.num_trades for m in metrics_list),
        alpha_pct=avg("alpha_pct"),
        beta=avg("beta"),
        information_ratio=avg("information_ratio"),
        final_equity_inr=metrics_list[-1].final_equity_inr,
    )
