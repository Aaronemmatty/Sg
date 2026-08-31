from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime

import pandas as pd

from app.core.logging import log
from app.core.metrics import BACKTEST_BARS_PROCESSED
from app.models.domain import (
    BacktestConfig,
    EquityPoint,
    OrderAction,
    SimulatedTrade,
    TransactionCostConfig,
)
from app.services.strategy_loader import SignalProvider


@dataclass
class _OpenPosition:
    symbol: str
    side: OrderAction  # BUY = long, SELL = short
    quantity: float
    entry_price: float
    entry_ts: datetime
    entry_commission: float
    entry_slippage: float
    trade_id: uuid.UUID = field(default_factory=uuid.uuid4)


def _apply_slippage(
    price: float, bar: pd.Series, costs: TransactionCostConfig, side_sign: int
) -> float:
    """side_sign: +1 when buying (price moves against us = up), -1 when selling."""
    if costs.slippage_model == "spread_proxy" and bar.get("high") is not None:
        spread_proxy_bps = max(
            0.0, ((bar["high"] - bar["low"]) / bar["close"]) * 10_000 * 0.25
        )
        slip_bps = max(costs.slippage_bps, spread_proxy_bps)
    elif costs.slippage_model == "volume_scaled" and bar.get("volume", 0):
        # Thinner volume bars get proportionally worse slippage, capped at 5x base.
        ref_volume = max(bar.get("volume", 1.0), 1.0)
        scale = min(5.0, 1.0 + (1.0 / ref_volume) * 1000)
        slip_bps = costs.slippage_bps * scale
    else:
        slip_bps = costs.slippage_bps

    return price * (1 + side_sign * slip_bps / 10_000)


def _commission(notional: float, costs: TransactionCostConfig) -> float:
    return abs(notional) * costs.commission_bps / 10_000 + costs.fixed_cost_inr


class BacktestEngine:
    """Single-pass event-driven backtest over one or more symbols.

    Execution model: a signal generated from bar[i] is filled at the OPEN of
    bar[i+1] (never the same bar's close) to avoid look-ahead bias. Positions
    are single-lot per symbol, sized to `max_position_pct` of current equity
    at entry time. Equity is marked to the latest close seen per symbol.
    """

    def __init__(self, config: BacktestConfig) -> None:
        self.config = config
        self.cash = config.initial_capital_inr
        self._open: dict[str, _OpenPosition] = {}
        self._last_close: dict[str, float] = {}
        self._trades: list[SimulatedTrade] = []
        self._equity_curve: list[EquityPoint] = []
        self._peak_equity = config.initial_capital_inr
        self._pending: dict[str, OrderAction] = {}

    def _equity(self) -> float:
        equity = self.cash
        for sym, pos in self._open.items():
            price = self._last_close.get(sym, pos.entry_price)
            if pos.side == OrderAction.BUY:
                equity += pos.quantity * price
            else:  # short: liability grows if price rises
                equity += pos.quantity * (2 * pos.entry_price - price)
        return equity

    def _position_value_at_entry_budget(self) -> float:
        return self._equity() * self.config.max_position_pct

    def _open_position(self, symbol: str, side: OrderAction, bar: pd.Series, ts: datetime) -> None:
        if symbol in self._open:
            return
        raw_price = float(bar["open"])
        side_sign = 1 if side == OrderAction.BUY else -1
        fill_price = _apply_slippage(raw_price, bar, self.config.costs, side_sign)
        budget = self._position_value_at_entry_budget()
        quantity = budget / fill_price if fill_price > 0 else 0.0
        if quantity <= 0:
            return
        notional = quantity * fill_price
        commission = _commission(notional, self.config.costs)
        slippage_cost = abs(fill_price - raw_price) * quantity

        if side == OrderAction.BUY:
            self.cash -= notional + commission
        else:
            self.cash += notional - commission  # short proceeds, minus cost

        self._open[symbol] = _OpenPosition(
            symbol=symbol,
            side=side,
            quantity=quantity,
            entry_price=fill_price,
            entry_ts=ts,
            entry_commission=commission,
            entry_slippage=slippage_cost,
        )

    def _close_position(
        self, symbol: str, bar: pd.Series, ts: datetime, reason: str
    ) -> None:
        pos = self._open.pop(symbol, None)
        if pos is None:
            return
        raw_price = float(bar["open"])
        side_sign = -1 if pos.side == OrderAction.BUY else 1
        fill_price = _apply_slippage(raw_price, bar, self.config.costs, side_sign)
        notional = pos.quantity * fill_price
        commission = _commission(notional, self.config.costs)
        slippage_cost = abs(fill_price - raw_price) * pos.quantity

        if pos.side == OrderAction.BUY:
            self.cash += notional - commission
            pnl = (fill_price - pos.entry_price) * pos.quantity - commission - pos.entry_commission
        else:
            self.cash -= notional + commission
            pnl = (pos.entry_price - fill_price) * pos.quantity - commission - pos.entry_commission

        entry_notional = pos.entry_price * pos.quantity
        pnl_pct = (pnl / entry_notional * 100) if entry_notional else 0.0

        self._trades.append(
            SimulatedTrade(
                trade_id=pos.trade_id,
                symbol=symbol,
                action=pos.side,
                entry_ts=pos.entry_ts,
                entry_price_inr=pos.entry_price,
                exit_ts=ts,
                exit_price_inr=fill_price,
                quantity=pos.quantity,
                commission_inr=commission + pos.entry_commission,
                slippage_inr=slippage_cost + pos.entry_slippage,
                realized_pnl_inr=pnl,
                realized_pnl_pct=pnl_pct,
                exit_reason=reason,
            )
        )

    def run(
        self,
        bars_by_symbol: dict[str, pd.DataFrame],
        signal_provider: SignalProvider,
        benchmark_df: pd.DataFrame | None = None,
    ) -> tuple[list[SimulatedTrade], list[EquityPoint]]:
        index_maps: dict[str, dict[pd.Timestamp, int]] = {
            sym: {ts: i for i, ts in enumerate(df["ts"])} for sym, df in bars_by_symbol.items()
        }
        timeline = sorted(set().union(*[set(df["ts"]) for df in bars_by_symbol.values()]))

        benchmark_lookup: dict[pd.Timestamp, float] = {}
        benchmark_start: float | None = None
        if benchmark_df is not None and not benchmark_df.empty:
            for row in benchmark_df.itertuples(index=False):
                benchmark_lookup[row.ts] = row.close
            benchmark_start = float(benchmark_df.iloc[0]["close"])
        last_benchmark_close: float | None = benchmark_start

        for ts in timeline:
            # 1. Execute any signals pending from the previous bar, at this bar's open.
            for symbol, action in list(self._pending.items()):
                idx_map = index_maps.get(symbol)
                if idx_map is None or ts not in idx_map:
                    continue
                bar = bars_by_symbol[symbol].iloc[idx_map[ts]]
                if action == OrderAction.BUY:
                    if symbol in self._open and self._open[symbol].side == OrderAction.SELL:
                        self._close_position(symbol, bar, ts, "signal_flip")
                    self._open_position(symbol, OrderAction.BUY, bar, ts)
                elif action == OrderAction.SELL:
                    if symbol in self._open and self._open[symbol].side == OrderAction.BUY:
                        self._close_position(symbol, bar, ts, "signal_exit")
                    elif self.config.allow_short and symbol not in self._open:
                        self._open_position(symbol, OrderAction.SELL, bar, ts)
                del self._pending[symbol]

            # 2. Mark prices and generate new signals for bars present at this ts.
            for symbol, idx_map in index_maps.items():
                if ts not in idx_map:
                    continue
                idx = idx_map[ts]
                bar = bars_by_symbol[symbol].iloc[idx]
                self._last_close[symbol] = float(bar["close"])
                BACKTEST_BARS_PROCESSED.inc()

                signal = signal_provider.signal_at(symbol, idx)
                if signal in ("BUY", "SELL"):
                    self._pending[symbol] = OrderAction(signal)

            # 3. Snapshot equity / drawdown / benchmark.
            equity = self._equity()
            self._peak_equity = max(self._peak_equity, equity)
            drawdown_pct = (
                (equity - self._peak_equity) / self._peak_equity * 100
                if self._peak_equity
                else 0.0
            )

            benchmark_equity = None
            if ts in benchmark_lookup:
                last_benchmark_close = benchmark_lookup[ts]
            if last_benchmark_close is not None and benchmark_start:
                benchmark_equity = (
                    self.config.initial_capital_inr * last_benchmark_close / benchmark_start
                )

            self._equity_curve.append(
                EquityPoint(
                    ts=ts,
                    equity_inr=equity,
                    cash_inr=self.cash,
                    drawdown_pct=drawdown_pct,
                    benchmark_equity_inr=benchmark_equity,
                )
            )

        # Close out any still-open positions at the final bar for clean accounting.
        if timeline:
            final_ts = timeline[-1]
            for symbol in list(self._open.keys()):
                idx_map = index_maps[symbol]
                if final_ts in idx_map:
                    bar = bars_by_symbol[symbol].iloc[idx_map[final_ts]]
                    self._close_position(symbol, bar, final_ts, "end_of_backtest")

        log.info(
            "backtest_engine_run_complete",
            symbols=list(bars_by_symbol.keys()),
            bars=len(timeline),
            trades=len(self._trades),
        )
        return self._trades, self._equity_curve
