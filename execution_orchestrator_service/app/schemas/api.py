"""Pydantic API schemas — execution orchestrator."""
from __future__ import annotations

from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, Field

from app.models.domain import (
    IntentStatus,
    MarketRegime,
    RejectionReason,
    TradeAction,
)


# ── Shared ────────────────────────────────────────────────────────────────────


class PaginationMeta(BaseModel):
    page: int
    page_size: int
    total: int


# ── Trade Intent schemas ──────────────────────────────────────────────────────


class TradeIntentResponse(BaseModel):
    intent_id: str
    correlation_id: str
    symbol: str
    timeframe: Optional[str]
    action: TradeAction
    status: IntentStatus
    confidence: float
    allocation_inr: float
    risk_percent: float
    market_regime: str
    rejection_reasons: list[RejectionReason] = Field(default_factory=list)
    rejection_detail: Optional[str] = None
    contributors: list[str] = Field(default_factory=list)
    net_score: Optional[float] = None
    agreement_ratio: Optional[float] = None
    portfolio_id: Optional[str] = None
    snapshot_portfolio_value_inr: Optional[float] = None
    snapshot_daily_loss_inr: Optional[float] = None
    snapshot_drawdown_pct: Optional[float] = None
    signal_timestamp: Optional[datetime] = None
    created_at: datetime

    model_config = {"from_attributes": True}


class TradeIntentListResponse(BaseModel):
    items: list[TradeIntentResponse]
    meta: PaginationMeta


# ── Manual signal injection (testing / manual override) ──────────────────────


class ManualSignalRequest(BaseModel):
    symbol: str = Field(..., min_length=1, max_length=32)
    action: TradeAction
    confidence: float = Field(..., ge=0.0, le=1.0)
    timeframe: str = Field(default="1D")
    regime: Optional[str] = None
    net_score: Optional[float] = None
    agreement_ratio: Optional[float] = None
    contributors: list[str] = Field(default_factory=list)


# ── Audit log schemas ─────────────────────────────────────────────────────────


class AuditCheckResponse(BaseModel):
    check_name: str
    passed: bool
    reason: Optional[str] = None
    detail: Optional[str] = None
    created_at: datetime

    model_config = {"from_attributes": True}


class AuditLogResponse(BaseModel):
    intent_id: str
    symbol: str
    checks: list[AuditCheckResponse]


# ── Health / Status ───────────────────────────────────────────────────────────


class HealthResponse(BaseModel):
    status: str
    service: str
    version: str
    environment: str


class ReadyResponse(BaseModel):
    status: str
    redis: bool
    database: bool
    consumer_running: bool
    open_intents: int


# ── Orchestrator config snapshot (readonly) ───────────────────────────────────


class OrchestratorConfigResponse(BaseModel):
    min_confidence: float
    min_liquidity_pct: float          # 3% of live portfolio value (dynamic)
    max_position_pct: float
    max_sector_exposure_pct: float
    max_correlation_score: float
    default_risk_pct: float
    max_allocation_pct: float         # 20% of live balance (dynamic)
    min_allocation_pct: float         # 4% of live balance (dynamic)
    daily_loss_limit_pct: float
    max_portfolio_drawdown_pct: float
    max_open_intents: int
