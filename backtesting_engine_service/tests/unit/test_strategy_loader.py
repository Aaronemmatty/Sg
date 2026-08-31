from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pandas as pd
import pytest

from app.models.domain import StrategyRef, StrategySourceType
from app.services.strategy_loader import (
    InlineRuleStrategyProvider,
    StrategyLoadError,
    build_signal_provider,
)


def _bars(closes: list[float]) -> pd.DataFrame:
    start = datetime(2024, 1, 1, tzinfo=timezone.utc)
    rows = [
        {"ts": start + timedelta(days=i), "open": c, "high": c, "low": c, "close": c, "volume": 1.0}
        for i, c in enumerate(closes)
    ]
    return pd.DataFrame(rows)


@pytest.mark.asyncio
async def test_sma_crossover_generates_buy_on_cross_above():
    rules = {
        "indicators": {
            "fast": {"type": "sma", "period": 2},
            "slow": {"type": "sma", "period": 4},
        },
        "entry_long": {"left": "fast", "op": "cross_above", "right": "slow"},
        "exit_long": {"left": "fast", "op": "cross_below", "right": "slow"},
    }
    ref = StrategyRef(source=StrategySourceType.INLINE, inline_rules=rules)
    provider = InlineRuleStrategyProvider(ref)

    # Downtrend then sharp uptrend forces a fast/slow crossover.
    closes = [100, 99, 98, 97, 96, 120, 130, 140]
    df = _bars(closes)
    await provider.prepare("TEST", df)

    signals = [provider.signal_at("TEST", i) for i in range(len(closes))]
    assert "BUY" in signals


def test_rejects_unsupported_indicator_type():
    rules = {"indicators": {"bad": {"type": "macd", "period": 10}}}
    ref = StrategyRef(source=StrategySourceType.INLINE, inline_rules=rules)
    with pytest.raises(StrategyLoadError):
        InlineRuleStrategyProvider(ref)


def test_rejects_unsupported_operator():
    rules = {
        "indicators": {"fast": {"type": "sma", "period": 2}},
        "entry_long": {"left": "fast", "op": "wibble", "right": "close"},
    }
    ref = StrategyRef(source=StrategySourceType.INLINE, inline_rules=rules)
    with pytest.raises(StrategyLoadError):
        InlineRuleStrategyProvider(ref)


def test_build_signal_provider_dispatches_on_source():
    ref = StrategyRef(source=StrategySourceType.INLINE, inline_rules={"indicators": {}})
    provider = build_signal_provider(ref)
    assert isinstance(provider, InlineRuleStrategyProvider)


@pytest.mark.asyncio
async def test_no_signal_before_indicator_warm_up_period():
    rules = {
        "indicators": {"fast": {"type": "sma", "period": 5}, "slow": {"type": "sma", "period": 10}},
        "entry_long": {"left": "fast", "op": "cross_above", "right": "slow"},
    }
    ref = StrategyRef(source=StrategySourceType.INLINE, inline_rules=rules)
    provider = InlineRuleStrategyProvider(ref)
    df = _bars([100, 101, 102])  # fewer bars than the slow period
    await provider.prepare("TEST", df)

    for i in range(len(df)):
        assert provider.signal_at("TEST", i) == "HOLD"
