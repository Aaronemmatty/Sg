"""Pydantic event schemas for events this service publishes/consumes."""
from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel

from app.models.domain import RegimeType


class RegimeUpdateEvent(BaseModel):
    """Published on every recalculation to `sg:regime:{symbol}`, event_type=regime_update."""

    event_type: Literal["regime_update"] = "regime_update"
    symbol: str
    timeframe: str
    regime: RegimeType
    confidence: float
    sub_regimes: list[RegimeType]
    timestamp: datetime


class RegimeChangeEvent(BaseModel):
    """Published only on a confirmed (debounced) transition, event_type=regime_change."""

    event_type: Literal["regime_change"] = "regime_change"
    symbol: str
    timeframe: str
    from_regime: RegimeType | None
    to_regime: RegimeType
    confidence: float
    trigger_reason: str
    timestamp: datetime


class CandleCompletedEvent(BaseModel):
    """Inbound event this service consumes from `sg:market:candle:{symbol}:{tf}`."""

    symbol: str
    timeframe: str
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: int
