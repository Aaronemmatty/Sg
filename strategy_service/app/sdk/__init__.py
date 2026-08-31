"""
Strategy SDK — public API for strategy authors.

Import ONLY these symbols in your strategy files:

    from app.sdk import (
        StrategyBase, StrategyMetadata, StrategyType,
        BarData, TickData, Signal, SignalType,
        StrategyContext, TradingMode,
    )
"""
from app.sdk.base import StrategyBase
from app.sdk.types import (
    BarData,
    Signal,
    SignalType,
    StrategyContext,
    StrategyMetadata,
    StrategyStatus,
    StrategyType,
    TradingMode,
    TickData,
)

__all__ = [
    "StrategyBase",
    "StrategyMetadata",
    "StrategyType",
    "StrategyStatus",
    "TradingMode",
    "BarData",
    "TickData",
    "Signal",
    "SignalType",
    "StrategyContext",
]
