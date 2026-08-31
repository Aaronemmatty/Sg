"""API schemas for strategy service."""
from __future__ import annotations
from datetime import datetime
from typing import Any, Optional
from pydantic import BaseModel, Field


class StartStrategyRequest(BaseModel):
    strategy_name: str
    symbol: str
    exchange: str = "NSE"
    timeframe: str = "5m"
    params: dict[str, Any] = Field(default_factory=dict)
    trading_mode: str = "paper"


class StrategyInstanceResponse(BaseModel):
    instance_id: str
    strategy_name: str
    version: str
    symbol: str
    exchange: str
    timeframe: str
    trading_mode: str
    status: str
    restart_count: int
    bars_processed: int
    signals_emitted: int
    started_at: Optional[datetime]
    stopped_at: Optional[datetime]
    error: Optional[str]
    params: dict[str, Any]


class StrategyRegistrationResponse(BaseModel):
    name: str
    version: str
    type: str
    author: str
    description: str
    timeframes: list[str]
    symbols: list[str]
    min_bars: int
    parameters: dict[str, Any]
    tags: list[str]
    is_builtin: bool
    file_hash: str
    source_path: Optional[str]
    status: str
    load_error: Optional[str]


class SignalResponse(BaseModel):
    symbol: str
    strategy_name: str
    strategy_version: str
    signal: str
    confidence: float
    timeframe: str
    suggested_quantity: int
    stop_loss: Optional[float]
    take_profit: Optional[float]
    entry_price: Optional[float]
    timestamp: str
    trading_mode: str
    metadata: dict[str, Any]


class PerformanceResponse(BaseModel):
    instance_id: str
    bars_processed: int
    signals_emitted: int
    signal_breakdown: dict[str, int]
    latency_stats: dict[str, Any]


class OkResponse(BaseModel):
    ok: bool = True
    message: str = "Success"
