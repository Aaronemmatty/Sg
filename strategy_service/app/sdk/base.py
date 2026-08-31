"""
StrategyBase — abstract base class for all strategies.

Every strategy (built-in or user-defined) must:
  1. Subclass StrategyBase
  2. Define class-level METADATA
  3. Implement on_bar() — returns Signal or None
  4. Optionally implement on_tick(), on_start(), on_stop()

The framework calls these methods. Strategies NEVER call the broker directly.

Example minimal strategy:
    class MyStrategy(StrategyBase):
        METADATA = StrategyMetadata(
            name="my_strategy",
            version="1.0.0",
            strategy_type=StrategyType.CUSTOM,
            author="Trader",
            description="My first strategy",
            timeframes=["5m"],
            symbols=["*"],
            min_bars_required=20,
            parameters={"fast_period": 10, "slow_period": 20},
        )

        async def on_bar(self, ctx: StrategyContext) -> Signal | None:
            closes = ctx.close_prices
            if len(closes) < self.METADATA.min_bars_required:
                return None
            # ... compute signal ...
            return Signal(signal=SignalType.BUY, confidence=0.75,
                          symbol=ctx.symbol, timeframe=ctx.timeframe)
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Optional

from app.sdk.types import (
    BarData, Signal, SignalType, StrategyContext, StrategyMetadata, TickData
)


class StrategyBase(ABC):
    """
    Abstract strategy base. Subclass this to create a strategy.

    Class attributes:
        METADATA (StrategyMetadata): required — declares strategy capabilities
    """

    METADATA: StrategyMetadata   # must be defined on every concrete class

    def __init__(self) -> None:
        self._initialized = False

    # ── Framework lifecycle hooks (override as needed) ────────────────────────

    async def on_start(self, params: dict) -> None:
        """
        Called once when strategy is started or restarted.
        Use for one-time setup: load models, initialise state, validate params.
        """
        pass

    async def on_stop(self) -> None:
        """
        Called when strategy is paused or stopped.
        Use for cleanup: save state, close handles.
        """
        pass

    # ── Core signal generation ────────────────────────────────────────────────

    @abstractmethod
    async def on_bar(self, ctx: StrategyContext) -> Optional[Signal]:
        """
        Called on every new completed bar for this strategy's symbol/timeframe.

        Rules:
          - Must return Signal or None (never raise)
          - Must complete within STRATEGY_EXECUTION_TIMEOUT_S seconds
          - Must NOT mutate ctx.bars or ctx.latest_tick
          - CAN mutate ctx.state (persisted between calls)
          - CAN read ctx.params for configuration
        """
        ...

    async def on_tick(self, ctx: StrategyContext, tick: TickData) -> Optional[Signal]:
        """
        Called on every validated tick. Override for tick-based strategies.
        Default: no-op (bar-based strategies don't need this).
        """
        return None

    async def on_signal_rejected(self, signal: Signal, reason: str) -> None:
        """
        Called when a signal was rejected by the Risk Engine.
        Override for adaptive strategies that adjust based on rejections.
        """
        pass

    # ── Helpers available to subclasses ──────────────────────────────────────

    def _param(self, ctx: StrategyContext, key: str, default=None):
        """Get a parameter value from context, falling back to METADATA default."""
        return ctx.params.get(key, self.METADATA.parameters.get(key, default))

    def _has_enough_bars(self, ctx: StrategyContext) -> bool:
        return len(ctx.bars) >= self.METADATA.min_bars_required

    def _make_signal(
        self,
        signal_type: SignalType,
        confidence: float,
        ctx: StrategyContext,
        suggested_quantity: int = 0,
        stop_loss: float | None = None,
        take_profit: float | None = None,
        metadata: dict | None = None,
    ) -> Signal:
        """Convenience factory — fills symbol/timeframe from context."""
        entry = ctx.last_bar.close if ctx.last_bar else None
        return Signal(
            signal=signal_type,
            confidence=confidence,
            symbol=ctx.symbol,
            timeframe=ctx.timeframe,
            suggested_quantity=suggested_quantity,
            stop_loss=stop_loss,
            take_profit=take_profit,
            entry_price=entry,
            metadata=metadata or {},
        )

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        # Validate METADATA at class definition time
        if not hasattr(cls, "METADATA") and not getattr(cls, "__abstractmethods__", None):
            raise TypeError(
                f"Strategy class '{cls.__name__}' must define class-level METADATA "
                f"as a StrategyMetadata instance."
            )
