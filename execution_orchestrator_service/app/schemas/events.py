"""Event contracts — Redis pub/sub wire format."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Optional

from pydantic import BaseModel, Field, field_validator

from app.models.domain import (
    AggregatedSignal,
    IntentStatus,
    RejectionReason,
    TradeAction,
    TradeIntent,
)


# ── Inbound event (sg:approved:{symbol}) ─────────────────────────────────────


class ApprovedSignalEvent(BaseModel):
    """Wire format published by signal_aggregation_service."""

    symbol: str
    timeframe: str
    final_signal: str        # TradeAction value
    confidence: float
    net_score: Optional[float] = None
    agreement_ratio: Optional[float] = None
    contributors: list[str] = Field(default_factory=list)
    votes: dict[str, Any] = Field(default_factory=dict)
    regime: Optional[str] = None
    timestamp: str           # ISO-8601 string
    weights_version: Optional[str] = None

    @classmethod
    def from_redis_message(cls, raw: str) -> "ApprovedSignalEvent":
        data = json.loads(raw)
        return cls(**data)

    def to_domain(self) -> AggregatedSignal:
        ts = datetime.fromisoformat(self.timestamp)
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        return AggregatedSignal(
            symbol=self.symbol,
            timeframe=self.timeframe,
            final_signal=TradeAction(self.final_signal),
            confidence=self.confidence,
            contributors=self.contributors,
            regime=self.regime,
            net_score=self.net_score,
            agreement_ratio=self.agreement_ratio,
            votes=self.votes,
            timestamp=ts,
            weights_version=self.weights_version,
        )


# ── Inbound event (sg:regime:{symbol}) ───────────────────────────────────────


class RegimeEvent(BaseModel):
    """Wire format published by regime_detection_service."""

    symbol: str
    regime: str
    confidence: float
    sub_regimes: list[str] = Field(default_factory=list)
    timestamp: str

    @classmethod
    def from_redis_message(cls, raw: str) -> "RegimeEvent":
        data = json.loads(raw)
        return cls(**data)


# ── Outbound event (sg:intents:{symbol}) ─────────────────────────────────────


class TradeIntentEvent(BaseModel):
    """Wire format published to sg:intents:{symbol} → risk_engine consumes."""

    intent_id: str
    correlation_id: str
    symbol: str
    action: str                         # TradeAction value
    confidence: float
    allocation_inr: float
    risk_percent: float
    market_regime: str
    status: str                         # IntentStatus value
    rejection_reasons: list[str] = Field(default_factory=list)
    rejection_detail: Optional[str] = None
    contributors: list[str] = Field(default_factory=list)
    timeframe: str = ""
    net_score: Optional[float] = None
    agreement_ratio: Optional[float] = None
    portfolio_id: Optional[str] = None
    created_at: str                     # ISO-8601
    signal_timestamp: Optional[str] = None

    @classmethod
    def from_domain(cls, intent: TradeIntent) -> "TradeIntentEvent":
        return cls(
            intent_id=intent.intent_id,
            correlation_id=intent.correlation_id,
            symbol=intent.symbol,
            action=intent.action.value,
            confidence=intent.confidence,
            allocation_inr=intent.allocation_inr,
            risk_percent=intent.risk_percent,
            market_regime=intent.market_regime,
            status=intent.status.value,
            rejection_reasons=[r.value for r in intent.rejection_reasons],
            rejection_detail=intent.rejection_detail,
            contributors=intent.contributors,
            timeframe=intent.timeframe,
            net_score=intent.net_score,
            agreement_ratio=intent.agreement_ratio,
            portfolio_id=intent.portfolio_id,
            created_at=intent.created_at.isoformat(),
            signal_timestamp=(
                intent.signal_timestamp.isoformat()
                if intent.signal_timestamp
                else None
            ),
        )

    def to_json(self) -> str:
        return self.model_dump_json()

    @classmethod
    def channel(cls, symbol: str, prefix: str = "sg:intents") -> str:
        return f"{prefix}:{symbol}"
