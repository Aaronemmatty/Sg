"""
Domain models for execution_engine_service (8008).

Inbound: RiskDecision (consumed from sg:risk_approved:{symbol} — produced by
risk_engine_service / 8007, contract frozen, do not change field names).

Internal: Order, Fill/Execution records, lifecycle event payloads.

Outbound: ExecutionEvent (published to sg:executions:{symbol} for
portfolio_management_service / 8009).
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field, field_validator


# --------------------------------------------------------------------------
# Inbound contract (from risk_engine_service, 8007) — DO NOT MODIFY SHAPE
# --------------------------------------------------------------------------

class RiskStatus(StrEnum):
    RISK_APPROVED = "RISK_APPROVED"
    RISK_REJECTED = "RISK_REJECTED"
    RISK_HOLD = "RISK_HOLD"


class TradeAction(StrEnum):
    BUY = "BUY"
    SELL = "SELL"


class RiskDecision(BaseModel):
    """Mirrors the RiskDecision contract published by risk_engine_service."""

    intent_id: uuid.UUID
    symbol: str
    action: TradeAction
    product: str = "MIS"
    original_allocation_inr: float
    approved_allocation_inr: float
    risk_score: float
    risk_band: str
    var_inr: float
    var_percent_of_portfolio: float
    status: RiskStatus
    rejection_reasons: list[str] = Field(default_factory=list)
    checks: dict[str, Any] = Field(default_factory=dict)
    kill_switch_active: bool = False
    market_regime: str | None = None
    correlation_id: uuid.UUID
    evaluated_at: datetime


# --------------------------------------------------------------------------
# Internal order domain
# --------------------------------------------------------------------------

class OrderState(StrEnum):
    PENDING = "PENDING"               # received, not yet routed
    HELD = "HELD"                     # RISK_HOLD intent parked, awaiting re-evaluation/expiry
    ROUTING = "ROUTING"                # routing/sizing decision being made
    SUBMITTED = "SUBMITTED"            # sent to broker_service, awaiting ack
    ACKNOWLEDGED = "ACKNOWLEDGED"       # broker accepted, working in market
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    FILLED = "FILLED"                  # terminal
    REJECTED = "REJECTED"              # terminal - broker rejected
    CANCELLED = "CANCELLED"            # terminal - cancelled (manual or expiry)
    EXPIRED = "EXPIRED"                # terminal - HELD intent aged out, or order validity expired
    FAILED = "FAILED"                  # terminal - exhausted retries / unrecoverable error


TERMINAL_STATES = frozenset(
    {OrderState.FILLED, OrderState.REJECTED, OrderState.CANCELLED, OrderState.EXPIRED, OrderState.FAILED}
)


class OrderType(StrEnum):
    MARKET = "MARKET"
    LIMIT = "LIMIT"


class OrderValidity(StrEnum):
    DAY = "DAY"
    IOC = "IOC"


class ExecutionStyle(StrEnum):
    AGGRESSIVE = "AGGRESSIVE"   # market order, prioritize fill certainty
    PASSIVE = "PASSIVE"         # limit order with a price band, prioritize price


class Order(BaseModel):
    order_id: uuid.UUID = Field(default_factory=uuid.uuid4)
    intent_id: uuid.UUID
    correlation_id: uuid.UUID
    symbol: str
    action: TradeAction
    product: str = "MIS"
    state: OrderState = OrderState.PENDING

    approved_allocation_inr: float
    quantity: int | None = None
    order_type: OrderType | None = None
    limit_price: float | None = None
    validity: OrderValidity = OrderValidity.DAY
    execution_style: ExecutionStyle

    risk_band: str
    market_regime: str | None = None

    broker_order_id: str | None = None
    idempotency_key: str

    intended_price_inr: float | None = None   # reference price at decision time, for slippage calc
    avg_fill_price_inr: float | None = None
    filled_quantity: int = 0

    retry_count: int = 0
    last_error: str | None = None

    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    held_until: datetime | None = None

    @field_validator("symbol")
    @classmethod
    def upper_symbol(cls, v: str) -> str:
        return v.upper()


class Execution(BaseModel):
    """A single fill (partial or full) against an order."""

    execution_id: uuid.UUID = Field(default_factory=uuid.uuid4)
    order_id: uuid.UUID
    broker_execution_id: str | None = None
    fill_quantity: int
    fill_price_inr: float
    fill_timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    slippage_inr: float | None = None
    slippage_bps: float | None = None


class ExecutionEvent(BaseModel):
    """Outbound event published to sg:executions:{symbol} for portfolio_management_service."""

    event_type: str  # ORDER_SUBMITTED | ORDER_ACKNOWLEDGED | ORDER_PARTIALLY_FILLED | ORDER_FILLED |
                       # ORDER_REJECTED | ORDER_CANCELLED | ORDER_EXPIRED | ORDER_FAILED
    order_id: uuid.UUID
    intent_id: uuid.UUID
    correlation_id: uuid.UUID
    symbol: str
    action: TradeAction
    state: OrderState
    quantity: int | None = None
    filled_quantity: int = 0
    avg_fill_price_inr: float | None = None
    slippage_bps: float | None = None
    broker_order_id: str | None = None
    reason: str | None = None
    emitted_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
