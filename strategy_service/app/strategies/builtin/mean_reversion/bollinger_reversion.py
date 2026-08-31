"""Bollinger Band Mean Reversion — built-in strategy."""
from __future__ import annotations
import statistics
from typing import Optional
from app.sdk import Signal, SignalType, StrategyBase, StrategyContext, StrategyMetadata, StrategyType


class BollingerReversionStrategy(StrategyBase):
    METADATA = StrategyMetadata(
        name="bollinger_reversion",
        version="1.0.0",
        strategy_type=StrategyType.MEAN_REVERSION,
        author="SG Platform",
        description="Bollinger Band mean reversion — buy near lower band, sell near upper band.",
        timeframes=["5m", "15m", "30m"],
        symbols=["*"],
        min_bars_required=25,
        parameters={"period": 20, "std_dev": 2.0, "entry_threshold": 0.95},
        tags=["mean_reversion", "bollinger", "bands"],
    )

    async def on_bar(self, ctx: StrategyContext) -> Optional[Signal]:
        if not self._has_enough_bars(ctx):
            return None

        period    = self._param(ctx, "period", 20)
        std_mult  = self._param(ctx, "std_dev", 2.0)
        threshold = self._param(ctx, "entry_threshold", 0.95)

        closes = ctx.close_prices[-period:]
        mid    = statistics.mean(closes)
        std    = statistics.stdev(closes)
        upper  = mid + std_mult * std
        lower  = mid - std_mult * std

        price = ctx.last_bar.close
        band_width = upper - lower
        if band_width == 0:
            return None

        pos_in_band = (price - lower) / band_width  # 0=lower, 1=upper

        if price <= lower * threshold:
            confidence = min(1.0, (lower - price) / (std or 1))
            return self._make_signal(
                SignalType.BUY, max(0.1, confidence), ctx,
                stop_loss=round(lower - std, 2),
                take_profit=round(mid, 2),
                metadata={"upper": round(upper, 2), "mid": round(mid, 2),
                          "lower": round(lower, 2), "pos_in_band": round(pos_in_band, 3)},
            )

        if price >= upper / threshold:
            confidence = min(1.0, (price - upper) / (std or 1))
            return self._make_signal(
                SignalType.SELL, max(0.1, confidence), ctx,
                stop_loss=round(upper + std, 2),
                take_profit=round(mid, 2),
                metadata={"upper": round(upper, 2), "mid": round(mid, 2),
                          "lower": round(lower, 2), "pos_in_band": round(pos_in_band, 3)},
            )

        return None
