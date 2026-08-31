from __future__ import annotations

from datetime import date

import pytest
from pydantic import ValidationError

from app.models.domain import (
    BacktestConfig,
    StrategyRef,
    StrategySourceType,
    Timeframe,
    TransactionCostConfig,
)


def _base_config(**overrides):
    defaults = dict(
        name="Test Strategy",
        symbols=["RELIANCE"],
        primary_timeframe=Timeframe.D1,
        start_date=date(2024, 1, 1),
        end_date=date(2024, 6, 1),
        initial_capital_inr=1_000_000.0,
        strategy=StrategyRef(source=StrategySourceType.INLINE, inline_rules={"indicators": {}}),
    )
    defaults.update(overrides)
    return BacktestConfig(**defaults)


def test_backtest_config_valid():
    config = _base_config()
    assert config.symbols == ["RELIANCE"]
    assert config.max_position_pct == 0.25


def test_backtest_config_rejects_end_before_start():
    with pytest.raises(ValidationError):
        _base_config(start_date=date(2024, 6, 1), end_date=date(2024, 1, 1))


def test_backtest_config_rejects_empty_symbols():
    with pytest.raises(ValidationError):
        _base_config(symbols=[])


def test_transaction_cost_config_defaults():
    costs = TransactionCostConfig()
    assert costs.commission_bps == 3.0
    assert costs.slippage_bps == 5.0
    assert costs.slippage_model == "fixed_bps"


def test_transaction_cost_config_rejects_negative():
    with pytest.raises(ValidationError):
        TransactionCostConfig(commission_bps=-1)


def test_strategy_ref_registry_and_inline():
    registry_ref = StrategyRef(source=StrategySourceType.REGISTRY, name="ema_crossover")
    assert registry_ref.source == StrategySourceType.REGISTRY

    inline_ref = StrategyRef(
        source=StrategySourceType.INLINE,
        inline_rules={"indicators": {"fast": {"type": "sma", "period": 5}}},
    )
    assert inline_ref.inline_rules["indicators"]["fast"]["period"] == 5
