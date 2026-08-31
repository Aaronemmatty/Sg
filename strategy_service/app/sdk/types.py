"""
Strategy SDK — types exposed to strategy authors.

Strategy writers import ONLY from this module:
    from app.sdk import StrategyBase, BarData, Signal, SignalType, StrategyContext

Everything else is internal to the framework.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Optional
from uuid import UUID


# ── Signal types ──────────────────────────────────────────────────────────────

class SignalType(str, Enum):
    BUY    = "BUY"
    SELL   = "SELL"
    HOLD   = "HOLD"
    EXIT   = "EXIT"     # Close existing position regardless of side
    CLOSE  = "CLOSE"    # Alias for EXIT (for clarity)


class StrategyStatus(str, Enum):
    REGISTERED = "REGISTERED"
    LOADING    = "LOADING"
    RUNNING    = "RUNNING"
    PAUSED     = "PAUSED"
    STOPPED    = "STOPPED"
    FAILED     = "FAILED"
    BACKTESTING= "BACKTESTING"


class TradingMode(str, Enum):
    LIVE     = "live"
    PAPER    = "paper"
    BACKTEST = "backtest"


class StrategyType(str, Enum):
    TREND_FOLLOWING  = "trend_following"
    MEAN_REVERSION   = "mean_reversion"
    BREAKOUT         = "breakout"
    MOMENTUM         = "momentum"
    STAT_ARB         = "stat_arb"
    ML               = "ml"
    CUSTOM           = "custom"


# ── Market data types (read-only views for strategies) ────────────────────────

@dataclass(slots=True, frozen=True)
class BarData:
    """A single OHLCV candle — immutable, passed to strategy on_bar()."""
    symbol: str
    exchange: str
    timeframe: str           # "1m", "5m", "1h", "1D"
    open_time: int           # Unix epoch seconds
    open: float
    high: float
    low: float
    close: float
    volume: int
    vwap: float = 0.0
    trade_count: int = 0

    @property
    def timestamp(self) -> datetime:
        from datetime import UTC
        return datetime.fromtimestamp(self.open_time, tz=UTC)

    @property
    def is_bullish(self) -> bool:
        return self.close > self.open

    @property
    def is_bearish(self) -> bool:
        return self.close < self.open

    @property
    def body_size(self) -> float:
        return abs(self.close - self.open)

    @property
    def range_size(self) -> float:
        return self.high - self.low


@dataclass(slots=True)
class TickData:
    """Live tick — passed to on_tick() for tick-based strategies."""
    symbol: str
    exchange: str
    last_price: float
    volume: int
    timestamp_ns: int
    bid: Optional[float] = None
    ask: Optional[float] = None


@dataclass
class Signal:
    """
    Strategy output — the canonical signal format.

    Framework contracts:
      - strategy_name and symbol are always set by the framework (not the strategy)
      - confidence must be in [0.0, 1.0]
      - suggested_quantity is a hint; Risk Engine makes final sizing decision
    """
    signal: SignalType
    confidence: float                       # 0.0 – 1.0
    symbol: str
    timeframe: str
    strategy_name: str = ""                 # set by framework
    strategy_version: str = ""             # set by framework
    suggested_quantity: int = 0            # hint to Risk Engine
    stop_loss: Optional[float] = None      # optional risk hint
    take_profit: Optional[float] = None    # optional risk hint
    entry_price: Optional[float] = None    # price at signal generation
    timestamp: datetime = field(
        default_factory=lambda: datetime.now(__import__("datetime").timezone.utc)
    )
    metadata: dict[str, Any] = field(default_factory=dict)
    trading_mode: TradingMode = TradingMode.PAPER

    def __post_init__(self):
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError(f"confidence must be in [0, 1], got {self.confidence}")

    def to_dict(self) -> dict:
        return {
            "symbol":             self.symbol,
            "strategy_name":      self.strategy_name,
            "strategy_version":   self.strategy_version,
            "signal":             self.signal.value,
            "confidence":         round(self.confidence, 4),
            "timeframe":          self.timeframe,
            "suggested_quantity": self.suggested_quantity,
            "stop_loss":          self.stop_loss,
            "take_profit":        self.take_profit,
            "entry_price":        self.entry_price,
            "timestamp":          self.timestamp.isoformat(),
            "trading_mode":       self.trading_mode.value,
            "metadata":           self.metadata,
        }


@dataclass
class StrategyContext:
    """
    Injected into every strategy at runtime.
    Provides read-only access to market state and framework services.
    Strategies MUST NOT hold a reference to this beyond a single on_bar() call.
    """
    symbol: str
    exchange: str
    timeframe: str
    trading_mode: TradingMode
    # Recent bars (oldest → newest). Strategy reads these, never writes.
    bars: list[BarData] = field(default_factory=list)
    # Latest tick (None if no tick received yet)
    latest_tick: Optional[TickData] = None
    # Strategy's own persistent state (survives between on_bar() calls)
    state: dict[str, Any] = field(default_factory=dict)
    # Parameters from strategy config
    params: dict[str, Any] = field(default_factory=dict)

    @property
    def close_prices(self) -> list[float]:
        return [b.close for b in self.bars]

    @property
    def volumes(self) -> list[int]:
        return [b.volume for b in self.bars]

    @property
    def last_bar(self) -> Optional[BarData]:
        return self.bars[-1] if self.bars else None

    @property
    def prev_bar(self) -> Optional[BarData]:
        return self.bars[-2] if len(self.bars) >= 2 else None


@dataclass
class StrategyMetadata:
    """Static metadata declared by each strategy class."""
    name: str
    version: str
    strategy_type: StrategyType
    author: str
    description: str
    timeframes: list[str]           # supported timeframes e.g. ["1m", "5m"]
    symbols: list[str]              # supported symbols or ["*"] for all
    min_bars_required: int          # minimum history before strategy produces signals
    parameters: dict[str, Any]     # default parameter values
    tags: list[str] = field(default_factory=list)
