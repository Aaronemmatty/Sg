"""Domain models for the Execution Orchestrator."""
from __future__ import annotations

import enum
from datetime import datetime, timezone
from typing import Optional
from uuid import UUID, uuid4

from pydantic import BaseModel, Field, field_validator


# ── Enumerations ──────────────────────────────────────────────────────────────


class TradeAction(str, enum.Enum):
    BUY = "BUY"
    SELL = "SELL"
    HOLD = "HOLD"


class IntentStatus(str, enum.Enum):
    ELIGIBLE = "ELIGIBLE"
    REJECTED = "REJECTED"
    HOLD = "HOLD"


class RejectionReason(str, enum.Enum):
    LOW_CONFIDENCE = "low_confidence"
    EXCESS_EXPOSURE = "excess_exposure"
    RISK_VIOLATION = "risk_violation"
    CORRELATION_VIOLATION = "correlation_violation"
    LIQUIDITY_VIOLATION = "liquidity_violation"
    DAILY_LOSS_LIMIT = "daily_loss_limit"
    POSITION_LIMIT = "position_limit"
    DRAWDOWN_LIMIT = "drawdown_limit"
    MAX_OPEN_INTENTS = "max_open_intents"
    ALLOCATION_TOO_SMALL = "allocation_too_small"


class MarketRegime(str, enum.Enum):
    TRENDING = "TRENDING"
    MEAN_REVERTING = "MEAN_REVERTING"
    VOLATILE = "VOLATILE"
    SIDEWAYS = "SIDEWAYS"
    UNKNOWN = "UNKNOWN"


# ── Input contracts (from upstream services) ──────────────────────────────────


class AggregatedSignal(BaseModel):
    """Contract published by signal_aggregation_service to sg:approved:{symbol}."""

    symbol: str
    timeframe: str
    final_signal: TradeAction
    confidence: float = Field(..., ge=0.0, le=1.0)
    contributors: list[str] = Field(default_factory=list)
    regime: Optional[str] = None
    net_score: Optional[float] = None
    agreement_ratio: Optional[float] = None
    votes: dict[str, dict] = Field(default_factory=dict)
    timestamp: datetime
    weights_version: Optional[str] = None

    @field_validator("timestamp", mode="before")
    @classmethod
    def _ensure_tz(cls, v: datetime) -> datetime:
        if isinstance(v, str):
            from datetime import datetime as dt
            v = dt.fromisoformat(v)
        if v.tzinfo is None:
            return v.replace(tzinfo=timezone.utc)
        return v


class RegimeUpdate(BaseModel):
    """Regime change event from sg:regime:{symbol}."""

    symbol: str
    regime: str
    confidence: float
    sub_regimes: list[str] = Field(default_factory=list)
    timestamp: datetime

    @field_validator("timestamp", mode="before")
    @classmethod
    def _ensure_tz(cls, v: datetime) -> datetime:
        if isinstance(v, str):
            from datetime import datetime as dt
            v = dt.fromisoformat(v)
        if v.tzinfo is None:
            return v.replace(tzinfo=timezone.utc)
        return v


# ── Portfolio / Risk state snapshots ─────────────────────────────────────────


class PositionSnapshot(BaseModel):
    """Single open position in the portfolio."""

    symbol: str
    sector: Optional[str] = None
    quantity: int = 0
    average_price: float = 0.0
    current_value_inr: float = 0.0
    weight_pct: float = 0.0             # % of total portfolio
    correlation_group: Optional[str] = None


class PortfolioState(BaseModel):
    """Portfolio snapshot — fetched from Redis or broker_service."""

    portfolio_id: str
    total_value_inr: float
    cash_inr: float
    equity_inr: float
    day_pnl_inr: float
    total_pnl_inr: float
    positions: list[PositionSnapshot] = Field(default_factory=list)
    as_of: datetime

    @property
    def utilised_pct(self) -> float:
        if self.total_value_inr <= 0:
            return 0.0
        return self.equity_inr / self.total_value_inr

    def position_for(self, symbol: str) -> Optional[PositionSnapshot]:
        return next((p for p in self.positions if p.symbol == symbol), None)

    def sector_exposure_pct(self, sector: str) -> float:
        if self.total_value_inr <= 0:
            return 0.0
        sector_val = sum(
            p.current_value_inr
            for p in self.positions
            if p.sector == sector
        )
        return sector_val / self.total_value_inr


class RiskState(BaseModel):
    """Risk snapshot — fetched from Redis or risk_engine."""

    portfolio_id: str
    daily_loss_inr: float = 0.0
    daily_loss_limit_inr: float
    drawdown_pct: float = 0.0
    max_drawdown_pct: float
    kill_switch_active: bool = False
    open_intents_count: int = 0
    correlation_matrix: dict[str, dict[str, float]] = Field(default_factory=dict)
    as_of: datetime


# ── Orchestrator output ───────────────────────────────────────────────────────


class AllocationResult(BaseModel):
    """Capital allocation recommendation."""

    allocation_inr: float
    risk_percent: float
    quantity_estimate: Optional[int] = None
    basis: str = ""                         # human-readable allocation rationale


class TradeIntent(BaseModel):
    """
    Primary output of the Execution Orchestrator.
    Published to sg:intents:{symbol} and persisted to DB.
    """

    intent_id: str = Field(default_factory=lambda: str(uuid4()))
    symbol: str
    action: TradeAction
    confidence: float
    allocation_inr: float
    risk_percent: float
    market_regime: str
    status: IntentStatus
    rejection_reasons: list[RejectionReason] = Field(default_factory=list)
    rejection_detail: Optional[str] = None
    contributors: list[str] = Field(default_factory=list)
    timeframe: str = ""
    net_score: Optional[float] = None
    agreement_ratio: Optional[float] = None
    portfolio_id: Optional[str] = None
    correlation_id: str = Field(default_factory=lambda: str(uuid4()))
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    signal_timestamp: Optional[datetime] = None

    def to_contract_dict(self) -> dict:
        """Matches the brief's canonical output shape."""
        return {
            "symbol": self.symbol,
            "action": self.action.value,
            "confidence": round(self.confidence, 4),
            "allocation": round(self.allocation_inr, 2),
            "risk_percent": round(self.risk_percent, 2),
            "market_regime": self.market_regime,
            "status": self.status.value,
            "intent_id": self.intent_id,
            "correlation_id": self.correlation_id,
            "rejection_reasons": [r.value for r in self.rejection_reasons],
            "rejection_detail": self.rejection_detail,
            "created_at": self.created_at.isoformat(),
        }


# ── Eligibility check result (internal) ──────────────────────────────────────


class EligibilityResult(BaseModel):
    """Returned by each individual eligibility check."""

    passed: bool
    check_name: str
    reason: Optional[RejectionReason] = None
    detail: Optional[str] = None
