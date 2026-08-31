"""
Example user strategy — drop this file into /app/strategies/ and it
will be hot-loaded within seconds.

Copy this file, rename it, and implement your own on_bar() logic.
Do NOT modify files in app/strategies/builtin/ — those are platform-owned.
"""
from __future__ import annotations
from typing import Optional

# Import ONLY from app.sdk — never import internal framework modules
from app.sdk import (
    BarData, Signal, SignalType,
    StrategyBase, StrategyContext, StrategyMetadata, StrategyType,
)


class MyCustomStrategy(StrategyBase):
    """
    Minimal working strategy — VWAP deviation signal.

    BUY  when price drops > threshold % below VWAP
    SELL when price rises > threshold % above VWAP
    """

    METADATA = StrategyMetadata(
        name="vwap_deviation",
        version="1.0.0",
        strategy_type=StrategyType.CUSTOM,
        author="Your Name",
        description="Signal when price deviates significantly from VWAP.",
        timeframes=["5m", "15m"],
        symbols=["*"],
        min_bars_required=10,
        parameters={
            "deviation_pct": 0.5,       # % deviation from VWAP to trigger
            "min_confidence": 0.55,
        },
        tags=["vwap", "deviation", "custom"],
    )

    async def on_start(self, params: dict) -> None:
        """Called once at strategy start. Validate params here."""
        dev = params.get("deviation_pct", 0.5)
        if dev <= 0 or dev > 10:
            raise ValueError(f"deviation_pct must be in (0, 10], got {dev}")

    async def on_bar(self, ctx: StrategyContext) -> Optional[Signal]:
        if not self._has_enough_bars(ctx):
            return None

        bar = ctx.last_bar
        if not bar or not bar.vwap or bar.vwap == 0:
            return None

        dev_pct   = self._param(ctx, "deviation_pct", 0.5)
        min_conf  = self._param(ctx, "min_confidence", 0.55)

        deviation = (bar.close - bar.vwap) / bar.vwap * 100  # % from VWAP

        if deviation < -dev_pct:
            # Price is significantly below VWAP — mean-reversion BUY
            confidence = min(1.0, abs(deviation) / (dev_pct * 2))
            if confidence < min_conf:
                return None
            return self._make_signal(
                SignalType.BUY, confidence, ctx,
                take_profit=round(bar.vwap, 2),
                metadata={"vwap": bar.vwap, "deviation_pct": round(deviation, 3)},
            )

        if deviation > dev_pct:
            # Price is significantly above VWAP — mean-reversion SELL
            confidence = min(1.0, deviation / (dev_pct * 2))
            if confidence < min_conf:
                return None
            return self._make_signal(
                SignalType.SELL, confidence, ctx,
                take_profit=round(bar.vwap, 2),
                metadata={"vwap": bar.vwap, "deviation_pct": round(deviation, 3)},
            )

        return None

    async def on_stop(self) -> None:
        """Called when strategy is paused or stopped."""
        pass

    async def on_signal_rejected(self, signal: Signal, reason: str) -> None:
        """Called if Risk Engine rejects our signal — adapt if needed."""
        pass
