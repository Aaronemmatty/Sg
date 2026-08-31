"""API schemas for market data service."""

from __future__ import annotations

from datetime import date, datetime
from typing import Optional

from pydantic import BaseModel, Field


# ── Tick ──────────────────────────────────────────────────────────────────────

class TickResponse(BaseModel):
    symbol: str
    exchange: str
    last_price: float
    volume: int
    timestamp_ns: int
    open: Optional[float] = None
    high: Optional[float] = None
    low: Optional[float] = None
    bid: Optional[float] = None
    ask: Optional[float] = None


# ── OHLCV ─────────────────────────────────────────────────────────────────────

class OHLCVBar(BaseModel):
    symbol: str
    exchange: str
    timeframe: str
    open_time: int
    close_time: int
    open: float
    high: float
    low: float
    close: float
    volume: int
    vwap: float = 0.0
    trade_count: int = 0
    is_complete: bool = False


class BarsResponse(BaseModel):
    symbol: str
    timeframe: str
    from_date: str
    to_date: str
    count: int
    bars: list[OHLCVBar]


# ── Subscription ──────────────────────────────────────────────────────────────

class SubscribeRequest(BaseModel):
    symbols: list[str] = Field(..., min_length=1, max_length=500)


class SubscribeResponse(BaseModel):
    subscribed: dict[str, int]   # symbol → token
    failed: list[str]
    total: int


class UnsubscribeRequest(BaseModel):
    symbols: list[str] = Field(..., min_length=1)


# ── Backfill ──────────────────────────────────────────────────────────────────

class BackfillRequest(BaseModel):
    symbol: str
    timeframe: str = "1m"
    from_date: date
    to_date: Optional[date] = None


class BackfillResponse(BaseModel):
    symbol: str
    timeframe: str
    bars_written: int
    message: str


# ── Instruments ───────────────────────────────────────────────────────────────

class InstrumentInfo(BaseModel):
    instrument_token: int
    trading_symbol: str
    name: str
    exchange: str
    instrument_type: str
    lot_size: int
    tick_size: float


class InstrumentSearchResponse(BaseModel):
    query: str
    results: list[InstrumentInfo]
    count: int


# ── Status ────────────────────────────────────────────────────────────────────

class FeedStatus(BaseModel):
    status: str
    mode: str
    subscribed_symbols: int
    market_open: bool
    feed_stats: Optional[dict] = None
    aggregator_stats: Optional[dict] = None
    writer_stats: Optional[dict] = None


class MarketStatus(BaseModel):
    is_open: bool
    is_preopen: bool
    next_open_in_seconds: Optional[float] = None
    message: str
