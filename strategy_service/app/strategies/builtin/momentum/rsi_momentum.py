"""
RSI Momentum — overbought/oversold momentum strategy for NSE equities.

Logic:
  BUY  when RSI crosses up through oversold level (default 30)
  SELL when RSI crosses down through overbought level (default 70)
  Confidence = distance from threshold normalised to 0–1
"""
from __future__ import annotations

from typing import Optional

from app.sdk import (
    Signal, SignalType, StrategyBase, StrategyContext,
    StrategyMetadata, StrategyType,
)


class RSIMomentumStrategy(StrategyBase):
    METADATA = StrategyMetadata(
        name="rsi_momentum",
        version="1.0.0",
        strategy_type=StrategyType.MOMENTUM,
        author="SG Platform",
        description="RSI-based momentum with overbought/oversold signals.",
        timeframes=["5m", "15m", "1h"],
        symbols=["*"],
        min_bars_required=30,
        parameters={
            "rsi_period":   14,
            "oversold":     30,
            "overbought":   70,
            "exit_neutral": 50,
        },
        tags=["momentum", "rsi", "oscillator"],
    )

    async def on_bar(self, ctx: StrategyContext) -> Optional[Signal]:
        if not self._has_enough_bars(ctx):
            return None

        period     = self._param(ctx, "rsi_period", 14)
        oversold   = self._param(ctx, "oversold", 30)
        overbought = self._param(ctx, "overbought", 70)

        closes = ctx.close_prices
        rsi = _rsi(closes, period)
        if rsi is None:
            return None

        prev_rsi = _rsi(closes[:-1], period) if len(closes) > period + 1 else None
        if prev_rsi is None:
            return None

        ctx.state["last_rsi"] = rsi

        # Golden zone: RSI crosses up through oversold
        if prev_rsi <= oversold < rsi:
            confidence = min(1.0, (rsi - oversold) / 20.0)
            return self._make_signal(
                SignalType.BUY, confidence, ctx,
                metadata={"rsi": round(rsi, 2), "prev_rsi": round(prev_rsi, 2)},
            )

        # Death zone: RSI crosses down through overbought
        if prev_rsi >= overbought > rsi:
            confidence = min(1.0, (overbought - rsi) / 20.0)
            return self._make_signal(
                SignalType.SELL, confidence, ctx,
                metadata={"rsi": round(rsi, 2), "prev_rsi": round(prev_rsi, 2)},
            )

        return None


def _rsi(closes: list[float], period: int) -> Optional[float]:
    if len(closes) < period + 1:
        return None
    gains, losses = [], []
    for i in range(1, len(closes)):
        diff = closes[i] - closes[i - 1]
        gains.append(max(diff, 0))
        losses.append(max(-diff, 0))

    avg_gain = sum(gains[-period:]) / period
    avg_loss = sum(losses[-period:]) / period

    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))
