"""
Domain models for the regime detection engine.

These are pure Pydantic models used internally and at the API boundary. They are
intentionally decoupled from the SQLAlchemy persistence models in `app/models/db.py`.
"""
from __future__ import annotations

import enum
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field, field_validator


class RegimeType(str, enum.Enum):
    TRENDING = "TRENDING"
    RANGING = "RANGING"
    HIGH_VOLATILITY = "HIGH_VOLATILITY"
    LOW_VOLATILITY = "LOW_VOLATILITY"
    RISK_ON = "RISK_ON"
    RISK_OFF = "RISK_OFF"
    BULLISH = "BULLISH"
    BEARISH = "BEARISH"
    SIDEWAYS = "SIDEWAYS"


# Regimes are grouped into independent axes. A symbol can simultaneously be e.g.
# TRENDING (structure axis) + BULLISH (direction axis) + LOW_VOLATILITY (vol axis)
# + RISK_ON (breadth axis). The engine picks one *primary* regime (the structure axis,
# unless a vol/breadth extreme dominates) and reports the rest as sub_regimes, matching
# the output contract which has a single `regime` field plus a `sub_regimes` list.
STRUCTURE_REGIMES = {RegimeType.TRENDING, RegimeType.RANGING, RegimeType.SIDEWAYS}
VOLATILITY_REGIMES = {RegimeType.HIGH_VOLATILITY, RegimeType.LOW_VOLATILITY}
DIRECTION_REGIMES = {RegimeType.BULLISH, RegimeType.BEARISH}
BREADTH_REGIMES = {RegimeType.RISK_ON, RegimeType.RISK_OFF}


class FeatureSet(BaseModel):
    """Technical features computed for a single symbol/timeframe at a point in time."""

    adx: float = Field(..., description="Average Directional Index (trend strength)")
    atr: float = Field(..., description="Average True Range, absolute price units")
    atr_pct: float = Field(..., description="ATR as a percentage of close price")
    bb_width: float = Field(..., description="Bollinger Band width, normalized by mid-band")
    volume_ratio: float = Field(..., description="Current volume / rolling average volume")
    trend_slope: float = Field(..., description="Normalized linear-regression slope of close")
    returns_std: float = Field(..., description="Rolling std-dev of log returns (realized vol)")
    vix_proxy: Optional[float] = Field(None, description="India VIX level if available, else None")
    breadth_pct: Optional[float] = Field(
        None, description="Pct of universe advancing, only set for market-wide symbol"
    )
    close: float = Field(..., description="Latest close price, for reference/logging")

    def as_dict(self) -> dict:
        return self.model_dump(exclude_none=True, exclude={"close"})


class RegimeResult(BaseModel):
    """Matches the platform-wide output contract for regime_detection_service."""

    regime: RegimeType
    confidence: float = Field(..., ge=0.0, le=1.0)
    sub_regimes: list[RegimeType] = Field(default_factory=list)
    symbol: str
    timeframe: str
    timestamp: datetime
    features: dict[str, float]
    model_version: Optional[str] = None
    is_override: bool = Field(
        default=False, description="True when this is a per-symbol override of the market regime"
    )

    @field_validator("timestamp")
    @classmethod
    def _ensure_tz(cls, v: datetime) -> datetime:
        if v.tzinfo is None:
            from datetime import timezone

            return v.replace(tzinfo=timezone.utc)
        return v


class RegimeTransition(BaseModel):
    symbol: str
    timeframe: str
    from_regime: Optional[RegimeType]
    to_regime: RegimeType
    confidence: float
    timestamp: datetime
    trigger_reason: str = Field(
        ..., description="e.g. 'structure_flip', 'volatility_spike', 'breadth_shift'"
    )


class BreadthSnapshot(BaseModel):
    advancing: int
    declining: int
    unchanged: int
    universe_size: int
    advance_pct: float
    breadth_regime: RegimeType  # RISK_ON or RISK_OFF
    timestamp: datetime


class BacktestRequest(BaseModel):
    symbol: str
    timeframe: str = "5m"
    start: datetime
    end: datetime


class BacktestResultPoint(BaseModel):
    timestamp: datetime
    regime: RegimeType
    confidence: float
    sub_regimes: list[RegimeType]


class BacktestResponse(BaseModel):
    symbol: str
    timeframe: str
    points: list[BacktestResultPoint]
    transitions: list[RegimeTransition]
