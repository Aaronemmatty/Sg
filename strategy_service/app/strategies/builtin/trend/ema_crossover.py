"""
EMA Crossover — classic dual-EMA trend following strategy.

Logic:
  BUY  when fast EMA crosses above slow EMA (golden cross)
  SELL when fast EMA crosses below slow EMA (death cross)
  HOLD otherwise

Confidence is proportional to the EMA spread normalised by price.
"""
from __future__ import annotations

from typing import Optional

from app.sdk import (
    BarData, Signal, SignalType, StrategyBase,
    StrategyContext, StrategyMetadata, StrategyType,
)


class EMACrossoverStrategy(StrategyBase):
    METADATA = StrategyMetadata(
        name="ema_crossover",
        version="1.0.0",
        strategy_type=StrategyType.TREND_FOLLOWING,
        author="SG Platform",
        description="Dual EMA crossover with golden/death cross signals.",
        timeframes=["5m", "15m", "1h"],
        symbols=["*"],
        min_bars_required=50,
        parameters={"fast_period": 9, "slow_period": 21, "min_confidence": 0.5},
        tags=["trend", "ema", "crossover"],
    )

    async def on_bar(self, ctx: StrategyContext) -> Optional[Signal]:
        if not self._has_enough_bars(ctx):
            return None

        fast = self._param(ctx, "fast_period", 9)
        slow = self._param(ctx, "slow_period", 21)
        min_conf = self._param(ctx, "min_confidence", 0.5)

        closes = ctx.close_prices
        fast_ema = _ema(closes, fast)
        slow_ema = _ema(closes, slow)

        if fast_ema is None or slow_ema is None:
            return None

        # Previous period values for crossover detection
        prev_closes = closes[:-1]
        prev_fast = _ema(prev_closes, fast)
        prev_slow = _ema(prev_closes, slow)

        if prev_fast is None or prev_slow is None:
            return None

        current_above = fast_ema > slow_ema
        was_above = prev_fast > prev_slow

        spread_pct = abs(fast_ema - slow_ema) / slow_ema
        confidence = min(1.0, spread_pct * 100)   # scale spread % → confidence

        if confidence < min_conf:
            return None

        if current_above and not was_above:
            ctx.state["position"] = "long"
            return self._make_signal(SignalType.BUY, confidence, ctx,
                                     metadata={"fast_ema": fast_ema, "slow_ema": slow_ema})

        if not current_above and was_above:
            ctx.state["position"] = "short"
            return self._make_signal(SignalType.SELL, confidence, ctx,
                                     metadata={"fast_ema": fast_ema, "slow_ema": slow_ema})

        return None


def _ema(prices: list[float], period: int) -> Optional[float]:
    if len(prices) < period:
        return None
    k = 2 / (period + 1)
    ema = sum(prices[:period]) / period
    for price in prices[period:]:
        ema = price * k + ema * (1 - k)
    return ema
