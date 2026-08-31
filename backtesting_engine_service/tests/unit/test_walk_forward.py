from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import numpy as np
import pandas as pd
import pytest

from app.models.domain import (
    BacktestConfig,
    StrategyRef,
    StrategySourceType,
    Timeframe,
    TransactionCostConfig,
    WalkForwardConfig,
)
from app.services.walk_forward import run_walk_forward


def _trending_bars(n_days: int, start: date) -> pd.DataFrame:
    rng = np.random.default_rng(11)
    start_dt = datetime(start.year, start.month, start.day, tzinfo=timezone.utc)
    closes = 100 + np.cumsum(rng.normal(0.05, 1.0, n_days))  # mild uptrend with noise
    rows = [
        {
            "ts": start_dt + timedelta(days=i),
            "open": closes[i],
            "high": closes[i] * 1.01,
            "low": closes[i] * 0.99,
            "close": closes[i],
            "volume": 1000.0,
        }
        for i in range(n_days)
    ]
    df = pd.DataFrame(rows)
    df["ts"] = pd.to_datetime(df["ts"], utc=True)
    return df


def _config() -> BacktestConfig:
    return BacktestConfig(
        name="WF Test",
        symbols=["TEST"],
        primary_timeframe=Timeframe.D1,
        start_date=date(2023, 1, 1),
        end_date=date(2023, 12, 1),
        initial_capital_inr=100_000.0,
        strategy=StrategyRef(
            source=StrategySourceType.INLINE,
            inline_rules={
                "indicators": {
                    "fast": {"type": "sma", "period": 5},
                    "slow": {"type": "sma", "period": 20},
                },
                "entry_long": {"left": "fast", "op": "cross_above", "right": "slow"},
                "exit_long": {"left": "fast", "op": "cross_below", "right": "slow"},
            },
        ),
        costs=TransactionCostConfig(commission_bps=1.0, slippage_bps=1.0),
        benchmark_symbol=None,
        max_position_pct=1.0,
    )


@pytest.mark.asyncio
async def test_walk_forward_produces_multiple_rolling_windows():
    config = _config()
    bars = {"TEST": _trending_bars(335, config.start_date)}
    wf_config = WalkForwardConfig(train_window_days=90, test_window_days=30, step_days=30)

    result = await run_walk_forward(config, wf_config, bars, None)

    assert len(result.windows) >= 2
    assert 0.0 <= result.consistency_score_pct <= 100.0
    for w in result.windows:
        assert w.test_start > w.train_end
        assert w.test_end > w.test_start


@pytest.mark.asyncio
async def test_anchored_walk_forward_expands_train_window():
    config = _config()
    bars = {"TEST": _trending_bars(335, config.start_date)}
    wf_config = WalkForwardConfig(
        train_window_days=60, test_window_days=30, step_days=30, anchored=True
    )

    result = await run_walk_forward(config, wf_config, bars, None)

    assert len(result.windows) >= 2
    # Anchored mode: every window's train_start is the same (expanding window).
    train_starts = {w.train_start for w in result.windows}
    assert len(train_starts) == 1
    # Train window length should grow across windows.
    durations = [(w.train_end - w.train_start).days for w in result.windows]
    assert durations == sorted(durations)
    assert durations[-1] > durations[0]


@pytest.mark.asyncio
async def test_walk_forward_returns_empty_result_for_too_short_range():
    config = _config()
    config = config.model_copy(update={"end_date": date(2023, 1, 20)})
    bars = {"TEST": _trending_bars(20, config.start_date)}
    wf_config = WalkForwardConfig(train_window_days=90, test_window_days=30, step_days=30)

    result = await run_walk_forward(config, wf_config, bars, None)
    assert result.windows == []
    assert result.consistency_score_pct == 0.0
