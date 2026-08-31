from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pandas as pd
import pytest

from app.models.domain import (
    BacktestConfig,
    OrderAction,
    StrategyRef,
    StrategySourceType,
    Timeframe,
    TransactionCostConfig,
)
from app.services.backtest_engine import BacktestEngine
from app.services.strategy_loader import SignalProvider


class _ScriptedSignalProvider(SignalProvider):
    """Emits a fixed, pre-scripted sequence of signals for a single symbol."""

    def __init__(self, script: dict[str, list[str]]) -> None:
        self._script = script

    async def prepare(self, symbol: str, bars: pd.DataFrame) -> None:
        return None

    def signal_at(self, symbol: str, idx: int) -> str:
        seq = self._script.get(symbol, [])
        return seq[idx] if idx < len(seq) else "HOLD"


def _make_bars(closes: list[float], start: datetime | None = None) -> pd.DataFrame:
    start = start or datetime(2024, 1, 1, tzinfo=timezone.utc)
    rows = []
    for i, c in enumerate(closes):
        rows.append(
            {
                "ts": start + timedelta(days=i),
                "open": c,
                "high": c * 1.01,
                "low": c * 0.99,
                "close": c,
                "volume": 1000.0,
            }
        )
    df = pd.DataFrame(rows)
    df["ts"] = pd.to_datetime(df["ts"], utc=True)
    return df


def _config(**overrides) -> BacktestConfig:
    defaults = dict(
        name="Engine Test",
        symbols=["TEST"],
        primary_timeframe=Timeframe.D1,
        start_date=datetime(2024, 1, 1).date(),
        end_date=datetime(2024, 1, 10).date(),
        initial_capital_inr=100_000.0,
        strategy=StrategyRef(source=StrategySourceType.INLINE, inline_rules={"indicators": {}}),
        costs=TransactionCostConfig(commission_bps=0.0, slippage_bps=0.0),
        max_position_pct=1.0,
        benchmark_symbol=None,
    )
    defaults.update(overrides)
    return BacktestConfig(**defaults)


def test_buy_signal_executes_at_next_bar_open_not_same_bar():
    # Signal fires on bar 0 (close=100), execution must use bar 1's open (105),
    # never bar 0's own price — this is the no-look-ahead guarantee.
    bars = _make_bars([100, 105, 110, 90])
    script = {"TEST": ["BUY", "HOLD", "SELL", "HOLD"]}
    config = _config()

    engine = BacktestEngine(config)
    trades, equity_curve = engine.run({"TEST": bars}, _ScriptedSignalProvider(script))

    assert len(trades) == 1
    trade = trades[0]
    assert trade.entry_price_inr == pytest.approx(105.0)  # bar 1's open, not bar 0's close
    assert trade.exit_price_inr == pytest.approx(90.0)  # bar 3's open
    assert len(equity_curve) == 4


def test_zero_cost_long_trade_pnl_matches_price_delta():
    bars = _make_bars([100, 100, 200, 200])
    script = {"TEST": ["BUY", "HOLD", "SELL", "HOLD"]}
    config = _config()

    engine = BacktestEngine(config)
    trades, _ = engine.run({"TEST": bars}, _ScriptedSignalProvider(script))

    trade = trades[0]
    # Entered at bar1 open=100, exited at bar3 open=200 → 100% gain on quantity.
    expected_qty = config.initial_capital_inr / 100.0
    assert trade.quantity == pytest.approx(expected_qty, rel=1e-6)
    assert trade.realized_pnl_inr == pytest.approx(expected_qty * 100.0, rel=1e-6)


def test_commission_and_slippage_reduce_pnl():
    bars = _make_bars([100, 100, 200, 200])
    script = {"TEST": ["BUY", "HOLD", "SELL", "HOLD"]}
    config = _config(costs=TransactionCostConfig(commission_bps=10.0, slippage_bps=10.0))

    engine = BacktestEngine(config)
    trades, _ = engine.run({"TEST": bars}, _ScriptedSignalProvider(script))

    trade = trades[0]
    zero_cost_pnl = (config.initial_capital_inr / 100.0) * 100.0
    assert trade.realized_pnl_inr < zero_cost_pnl
    assert trade.commission_inr > 0
    assert trade.slippage_inr > 0


def test_open_position_force_closed_at_end_of_backtest():
    bars = _make_bars([100, 105, 110, 115])
    script = {"TEST": ["BUY", "HOLD", "HOLD", "HOLD"]}
    config = _config()

    engine = BacktestEngine(config)
    trades, _ = engine.run({"TEST": bars}, _ScriptedSignalProvider(script))

    assert len(trades) == 1
    assert trades[0].exit_reason == "end_of_backtest"
    assert trades[0].exit_ts is not None


def test_no_short_when_allow_short_false():
    bars = _make_bars([100, 95, 90, 85])
    script = {"TEST": ["SELL", "HOLD", "HOLD", "HOLD"]}
    config = _config(allow_short=False)

    engine = BacktestEngine(config)
    trades, _ = engine.run({"TEST": bars}, _ScriptedSignalProvider(script))

    assert trades == []
