"""Donchian Channel Breakout — built-in breakout strategy."""
from __future__ import annotations
from typing import Optional
from app.sdk import Signal, SignalType, StrategyBase, StrategyContext, StrategyMetadata, StrategyType


class DonchianBreakoutStrategy(StrategyBase):
    METADATA = StrategyMetadata(
        name="donchian_breakout",
        version="1.0.0",
        strategy_type=StrategyType.BREAKOUT,
        author="SG Platform",
        description="Donchian channel breakout — buy new N-bar highs, sell new N-bar lows.",
        timeframes=["15m", "30m", "1h", "1D"],
        symbols=["*"],
        min_bars_required=25,
        parameters={"channel_period": 20, "atr_period": 14, "atr_multiplier": 1.5},
        tags=["breakout", "donchian", "channel"],
    )

    async def on_bar(self, ctx: StrategyContext) -> Optional[Signal]:
        if not self._has_enough_bars(ctx):
            return None

        period  = self._param(ctx, "channel_period", 20)
        atr_p   = self._param(ctx, "atr_period", 14)
        atr_mul = self._param(ctx, "atr_multiplier", 1.5)

        bars = ctx.bars[-period - 1:]
        if len(bars) < period + 1:
            return None

        channel_bars = bars[:-1]  # exclude current bar
        upper = max(b.high for b in channel_bars)
        lower = min(b.low  for b in channel_bars)
        atr   = _atr([b for b in ctx.bars[-atr_p - 1:]], atr_p)

        current = ctx.last_bar
        prev    = ctx.prev_bar
        if not prev:
            return None

        # Breakout up: close exceeds prior channel high
        if current.close > upper and prev.close <= upper:
            confidence = min(1.0, (current.close - upper) / (atr or 1))
            return self._make_signal(
                SignalType.BUY, min(0.95, 0.5 + confidence), ctx,
                stop_loss=round(current.close - atr * atr_mul, 2),
                metadata={"channel_high": upper, "channel_low": lower, "atr": round(atr, 2)},
            )

        # Breakout down: close falls below prior channel low
        if current.close < lower and prev.close >= lower:
            confidence = min(1.0, (lower - current.close) / (atr or 1))
            return self._make_signal(
                SignalType.SELL, min(0.95, 0.5 + confidence), ctx,
                stop_loss=round(current.close + atr * atr_mul, 2),
                metadata={"channel_high": upper, "channel_low": lower, "atr": round(atr, 2)},
            )

        return None


def _atr(bars, period: int) -> float:
    if len(bars) < 2:
        return 0.0
    trs = []
    for i in range(1, len(bars)):
        tr = max(
            bars[i].high - bars[i].low,
            abs(bars[i].high - bars[i - 1].close),
            abs(bars[i].low  - bars[i - 1].close),
        )
        trs.append(tr)
    return sum(trs[-period:]) / min(period, len(trs))
