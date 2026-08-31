from __future__ import annotations

import uuid
from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class IntentStatus(str, Enum):
    ELIGIBLE = "ELIGIBLE"
    REJECTED = "REJECTED"
    HOLD = "HOLD"


class TradeIntent(BaseModel):
    """Mirrors the execution_orchestrator_service (8006) output contract exactly."""

    intent_id: uuid.UUID
    symbol: str
    action: str  # BUY | SELL
    confidence: float
    allocation_inr: float
    risk_percent: float
    market_regime: str
    status: IntentStatus
    rejection_reasons: list[str] = Field(default_factory=list)
    correlation_id: uuid.UUID
    created_at: datetime


class RiskStatus(str, Enum):
    RISK_APPROVED = "RISK_APPROVED"
    RISK_REJECTED = "RISK_REJECTED"
    RISK_HOLD = "RISK_HOLD"


class RiskRejectionReason(str, Enum):
    VAR_BREACH = "var_breach"
    MARGIN_INSUFFICIENT = "margin_insufficient"
    CONCENTRATION_LIMIT = "concentration_limit"
    SECTOR_EXPOSURE_BREACH = "sector_exposure_breach"
    CORRELATION_BREACH = "correlation_breach"
    VOLATILITY_HALT = "volatility_halt"
    DAILY_LOSS_LIMIT_BREACH = "daily_loss_limit_breach"
    DRAWDOWN_LIMIT_BREACH = "drawdown_limit_breach"
    POSITION_SIZING_VIOLATION = "position_sizing_violation"
    CIRCUIT_BREAKER_TRIPPED = "circuit_breaker_tripped"
    KILL_SWITCH_ACTIVE = "kill_switch_active"
    RISK_SCORE_TOO_HIGH = "risk_score_too_high"


class RiskBand(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class CheckResult(BaseModel):
    passed: bool
    detail: str
    value: float | None = None
    threshold: float | None = None


class RiskDecision(BaseModel):
    intent_id: uuid.UUID
    symbol: str
    action: str
    original_allocation_inr: float
    approved_allocation_inr: float | None
    risk_score: float
    risk_band: RiskBand
    var_inr: float | None = None
    var_percent_of_portfolio: float | None = None
    status: RiskStatus
    rejection_reasons: list[RiskRejectionReason] = Field(default_factory=list)
    checks: dict[str, CheckResult] = Field(default_factory=dict)
    kill_switch_active: bool = False
    market_regime: str | None = None
    correlation_id: uuid.UUID
    evaluated_at: datetime = Field(default_factory=datetime.utcnow)

    def to_redis_payload(self) -> dict[str, Any]:
        return self.model_dump(mode="json")


class PortfolioSnapshot(BaseModel):
    nav_inr: float
    cash_inr: float
    peak_equity_inr: float
    daily_pnl_inr: float
    daily_start_equity_inr: float
    open_positions: dict[str, dict[str, Any]] = Field(default_factory=dict)
    sector_exposure_inr: dict[str, float] = Field(default_factory=dict)
    free_margin_inr: float | None = None
    total_margin_inr: float | None = None
