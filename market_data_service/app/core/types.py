"""Domain value objects for market data.

These are pure Python dataclasses — no SQLAlchemy, no Pydantic overhead
in the hot tick-processing path.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from decimal import Decimal
from enum import IntEnum
from typing import Optional


class Timeframe(IntEnum):
    """Candle timeframe in minutes. 375 = full NSE session (1D)."""
    M1   = 1
    M3   = 3
    M5   = 5
    M15  = 15
    M30  = 30
    H1   = 60
    H4   = 240
    D1   = 375  # NSE session minutes

    @property
    def label(self) -> str:
        labels = {1: "1m", 3: "3m", 5: "5m", 15: "15m",
                  30: "30m", 60: "1h", 240: "4h", 375: "1D"}
        return labels[self.value]

    @classmethod
    def from_minutes(cls, minutes: int) -> "Timeframe":
        return cls(minutes)


@dataclass(slots=True)
class Tick:
    """A single market tick from KiteTicker."""
    instrument_token: int
    symbol: str                 # e.g. "NSE:RELIANCE"
    exchange: str               # NSE | BSE
    last_price: float
    volume: int
    timestamp_ns: int = field(default_factory=lambda: time.time_ns())

    # Optional full-mode fields (KiteTicker full quote)
    open: Optional[float] = None
    high: Optional[float] = None
    low: Optional[float] = None
    close: Optional[float] = None           # previous close
    bid: Optional[float] = None
    ask: Optional[float] = None
    bid_qty: Optional[int] = None
    ask_qty: Optional[int] = None
    oi: Optional[int] = None                # open interest (F&O)
    last_traded_qty: Optional[int] = None
    average_price: Optional[float] = None
    buy_quantity: Optional[int] = None
    sell_quantity: Optional[int] = None

    @property
    def timestamp_s(self) -> float:
        return self.timestamp_ns / 1e9

    @property
    def trading_symbol(self) -> str:
        """Just the symbol without exchange prefix."""
        return self.symbol.split(":")[-1]


@dataclass(slots=True)
class OHLCV:
    """A completed or in-progress OHLCV candle."""
    symbol: str
    exchange: str
    timeframe: Timeframe
    open_time: int          # Unix epoch seconds (candle start)
    close_time: int         # Unix epoch seconds (candle end, exclusive)
    open: float
    high: float
    low: float
    close: float
    volume: int
    vwap: float = 0.0
    trade_count: int = 0
    is_complete: bool = False

    @classmethod
    def from_tick(cls, tick: Tick, timeframe: Timeframe, candle_start: int) -> "OHLCV":
        candle_end = candle_start + timeframe.value * 60
        return cls(
            symbol=tick.trading_symbol,
            exchange=tick.exchange,
            timeframe=timeframe,
            open_time=candle_start,
            close_time=candle_end,
            open=tick.last_price,
            high=tick.last_price,
            low=tick.last_price,
            close=tick.last_price,
            volume=tick.volume,
            trade_count=1,
        )

    def update(self, tick: Tick, tick_volume: int) -> None:
        """Update candle with a new tick (volume = delta volume)."""
        if tick.last_price > self.high:
            self.high = tick.last_price
        if tick.last_price < self.low:
            self.low = tick.last_price
        self.close = tick.last_price
        self.volume += tick_volume
        self.trade_count += 1

    def to_dict(self) -> dict:
        return {
            "symbol": self.symbol,
            "exchange": self.exchange,
            "timeframe": self.timeframe.label,
            "open_time": self.open_time,
            "close_time": self.close_time,
            "open": self.open,
            "high": self.high,
            "low": self.low,
            "close": self.close,
            "volume": self.volume,
            "vwap": round(self.vwap, 4),
            "trade_count": self.trade_count,
            "is_complete": self.is_complete,
        }


@dataclass(slots=True)
class Instrument:
    """NSE instrument metadata (from Kite instrument dump)."""
    instrument_token: int
    exchange_token: int
    trading_symbol: str
    name: str
    exchange: str           # NSE | BSE
    segment: str            # NSE | BSE | NFO-FUT | NFO-OPT
    instrument_type: str    # EQ | FUT | CE | PE
    lot_size: int
    tick_size: float
    expiry: Optional[str] = None
    strike: Optional[float] = None

    @property
    def full_symbol(self) -> str:
        return f"{self.exchange}:{self.trading_symbol}"

    @property
    def is_equity(self) -> bool:
        return self.instrument_type == "EQ"
