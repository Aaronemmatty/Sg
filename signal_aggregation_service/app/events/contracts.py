"""Pydantic event schemas for events this service publishes/consumes."""
from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel

from app.models.domain import SignalAction


class AggregatedSignalEvent(BaseModel):
    """Published on every recompute to `sg:aggregated_signal:{symbol}`."""

    symbol: str
    timeframe: str
    final_signal: SignalAction
    confidence: float
    contributors: list[str]
    regime: str | None
    net_score: float | None
    agreement_ratio: float | None
    timestamp: datetime


class StrategySignalEvent(BaseModel):
    """Inbound event this service consumes from `sg:signals:{symbol}`."""

    strategy: str
    symbol: str
    timeframe: str
    action: SignalAction
    confidence: float
    timestamp: datetime


class RegimeChangeEventRef(BaseModel):
    """Inbound event this service consumes from `sg:regime:{symbol}` (only the fields
    this service needs; see regime_detection_service for the full contract)."""

    event_type: Literal["regime_update", "regime_change"]
    symbol: str
    timeframe: str
    regime: str
    confidence: float
    timestamp: datetime


class WeightsUpdatedEvent(BaseModel):
    """Published to `sg:weights:updated` whenever a DB override is written, so other
    replicas of this service invalidate their in-process weight cache."""

    regime: str
