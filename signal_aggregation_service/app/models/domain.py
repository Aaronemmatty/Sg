"""Domain models for the signal aggregation engine."""
from __future__ import annotations

import enum
from datetime import datetime, timezone
from typing import Optional

from pydantic import BaseModel, Field, field_validator


class SignalAction(str, enum.Enum):
    BUY = "BUY"
    SELL = "SELL"
    HOLD = "HOLD"


class StrategySignal(BaseModel):
    """Raw signal as read from `signal:{strategy}:{symbol}:{tf}` / sg:signals:{symbol}."""

    strategy: str
    symbol: str
    timeframe: str
    action: SignalAction
    confidence: float = Field(..., ge=0.0, le=1.0)
    timestamp: datetime

    @field_validator("timestamp")
    @classmethod
    def _ensure_tz(cls, v: datetime) -> datetime:
        if v.tzinfo is None:
            return v.replace(tzinfo=timezone.utc)
        return v


class SignalVote(BaseModel):
    """
    Canonical, normalized representation of one strategy's opinion, ready for weighting.
    direction: -1 (SELL), 0 (HOLD), +1 (BUY). signed_strength = direction * confidence.
    """

    strategy: str
    direction: int = Field(..., ge=-1, le=1)
    confidence: float = Field(..., ge=0.0, le=1.0)
    raw_action: SignalAction
    is_stale: bool = False

    @property
    def signed_strength(self) -> float:
        return self.direction * self.confidence


class RegimeRef(BaseModel):
    """Lightweight reference to the current regime, as published by regime_detection_service."""

    regime: str
    confidence: float
    sub_regimes: list[str] = Field(default_factory=list)
    timestamp: datetime


class WeightSet(BaseModel):
    """Effective weights actually used for one aggregation run, after renormalization."""

    regime: str
    raw_weights: dict[str, float]  # configured weights for strategies that voted
    effective_weights: dict[str, float]  # renormalized so they sum to 1.0
    unmapped_strategies: list[str] = Field(default_factory=list)


class ConflictReport(BaseModel):
    net_score: float
    agreement_ratio: float = Field(..., ge=0.0, le=1.0)
    voting_strategies: int
    buy_weight: float
    sell_weight: float
    hold_weight: float


class AggregatedSignalResult(BaseModel):
    """Matches the platform-wide output contract for signal_aggregation_service."""

    symbol: str
    timeframe: str
    final_signal: SignalAction
    confidence: float = Field(..., ge=0.0, le=1.0)
    contributors: list[str]
    regime: Optional[str] = None
    net_score: Optional[float] = None
    agreement_ratio: Optional[float] = None
    votes: dict[str, dict] = Field(default_factory=dict)  # strategy -> {action, confidence, weight}
    timestamp: datetime
    weights_version: Optional[str] = None
    is_published: bool = True
    cost_gate_passed: bool = True
    cost_gate_details: Optional[dict] = None

    @field_validator("timestamp")
    @classmethod
    def _ensure_tz(cls, v: datetime) -> datetime:
        if v.tzinfo is None:
            return v.replace(tzinfo=timezone.utc)
        return v

    def to_contract_dict(self) -> dict:
        """Minimal shape exactly matching the brief's example output."""
        return {
            "symbol": self.symbol,
            "final_signal": self.final_signal.value,
            "confidence": round(self.confidence, 4),
            "contributors": self.contributors,
        }


class WeightOverrideRequest(BaseModel):
    regime: str
    weights: dict[str, float]


class WeightOverrideResponse(BaseModel):
    regime: str
    effective_weights: dict[str, float]
    source: str  # "static_default" | "db_override" | "merged"
