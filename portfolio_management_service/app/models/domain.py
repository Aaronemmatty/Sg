"""
Domain models for portfolio_management_service (8009).

Inbound:  ExecutionEvent — consumed from sg:executions:{symbol} (published by
          execution_engine_service / 8008). Schema frozen per handover contract.

Internal: Position, Lot (FIFO cost basis), PortfolioSnapshot, PerformanceMetrics.

Outbound: PortfolioSnapshotEvent — published to sg:portfolio:events.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from decimal import Decimal
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field, field_validator


# ─────────────────────────────────────────────────────────────────────────────
# Inbound: ExecutionEvent from execution_engine_service (8008)
# DO NOT MODIFY — frozen contract.
# ─────────────────────────────────────────────────────────────────────────────

class ExecutionEventType(StrEnum):
    ORDER_SUBMITTED = "ORDER_SUBMITTED"
    ORDER_ACKNOWLEDGED = "ORDER_ACKNOWLEDGED"
    ORDER_PARTIALLY_FILLED = "ORDER_PARTIALLY_FILLED"
    ORDER_FILLED = "ORDER_FILLED"
    ORDER_REJECTED = "ORDER_REJECTED"
    ORDER_CANCELLED = "ORDER_CANCELLED"
    ORDER_EXPIRED = "ORDER_EXPIRED"
    ORDER_FAILED = "ORDER_FAILED"


class TradeAction(StrEnum):
    BUY = "BUY"
    SELL = "SELL"


class ExecutionEvent(BaseModel):
    """Mirrors ExecutionEvent published by execution_engine_service."""

    event_type: str
    order_id: uuid.UUID
    intent_id: uuid.UUID
    correlation_id: uuid.UUID
    symbol: str
    action: TradeAction
    state: str
    quantity: int | None = None
    filled_quantity: int = 0
    avg_fill_price_inr: float | None = None
    slippage_bps: float | None = None
    broker_order_id: str | None = None
    reason: str | None = None
    emitted_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    @field_validator("symbol")
    @classmethod
    def upper_symbol(cls, v: str) -> str:
        return v.upper()

    @property
    def is_fill_event(self) -> bool:
        return self.event_type in (
            ExecutionEventType.ORDER_PARTIALLY_FILLED,
            ExecutionEventType.ORDER_FILLED,
        )


# ─────────────────────────────────────────────────────────────────────────────
# Internal: FIFO lot (one per buy fill)
# ─────────────────────────────────────────────────────────────────────────────

class LotStatus(StrEnum):
    OPEN = "OPEN"
    PARTIALLY_CLOSED = "PARTIALLY_CLOSED"
    CLOSED = "CLOSED"


class Lot(BaseModel):
    """
    A single buy execution lot for FIFO cost-basis tracking.

    Sells consume open lots oldest-first. Each lot tracks:
      - original_quantity  — qty at open
      - remaining_quantity — qty still unsold
      - cost_price_inr     — fill price at open (basis for realized P&L)
    """
    lot_id: uuid.UUID = Field(default_factory=uuid.uuid4)
    symbol: str
    order_id: uuid.UUID
    execution_event_id: uuid.UUID       # event that created this lot
    original_quantity: int
    remaining_quantity: int
    cost_price_inr: Decimal
    status: LotStatus = LotStatus.OPEN
    opened_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    closed_at: datetime | None = None


class LotConsumption(BaseModel):
    """Records one (lot, qty_consumed) pair produced by a sell fill."""
    lot_id: uuid.UUID
    qty_consumed: int
    cost_price_inr: Decimal
    sell_price_inr: Decimal
    realized_pnl_inr: Decimal          # (sell_price - cost_price) * qty_consumed


# ─────────────────────────────────────────────────────────────────────────────
# Internal: net position per symbol
# ─────────────────────────────────────────────────────────────────────────────

class Position(BaseModel):
    """
    Current net position for one symbol.

    avg_cost_inr is recomputed from open lots on each buy.
    market_price_inr and unrealized_pnl_inr are updated by the MTM loop.
    realized_pnl_inr accumulates on every sell.
    """
    symbol: str
    net_quantity: int = 0                    # positive = long, zero = flat
    avg_cost_inr: Decimal = Decimal("0")     # weighted average cost of open lots
    market_price_inr: Decimal | None = None
    market_value_inr: Decimal = Decimal("0")
    unrealized_pnl_inr: Decimal = Decimal("0")
    realized_pnl_inr: Decimal = Decimal("0")
    total_pnl_inr: Decimal = Decimal("0")
    day_pnl_inr: Decimal = Decimal("0")     # reset at day open / first MTM
    last_trade_at: datetime | None = None
    last_mtm_at: datetime | None = None
    version: int = 1

    @property
    def is_flat(self) -> bool:
        return self.net_quantity == 0

    def recompute_from_mtm(self, market_price: Decimal) -> None:
        self.market_price_inr = market_price
        self.market_value_inr = market_price * self.net_quantity
        if self.net_quantity > 0:
            self.unrealized_pnl_inr = (market_price - self.avg_cost_inr) * self.net_quantity
        else:
            self.unrealized_pnl_inr = Decimal("0")
        self.total_pnl_inr = self.realized_pnl_inr + self.unrealized_pnl_inr
        self.last_mtm_at = datetime.now(timezone.utc)


# ─────────────────────────────────────────────────────────────────────────────
# Performance metrics (computed, not persisted directly)
# ─────────────────────────────────────────────────────────────────────────────

class PerformanceWindow(StrEnum):
    DAY_1 = "1d"
    DAYS_7 = "7d"
    DAYS_30 = "30d"
    DAYS_90 = "90d"
    DAYS_252 = "252d"   # ~1 trading year
    INCEPTION = "inception"


class PerformanceMetrics(BaseModel):
    """
    Computed performance metrics for a portfolio or sub-period.

    All return figures are annualized unless noted.
    All monetary figures in INR.
    """
    window: PerformanceWindow
    computed_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    # P&L
    total_pnl_inr: Decimal = Decimal("0")
    realized_pnl_inr: Decimal = Decimal("0")
    unrealized_pnl_inr: Decimal = Decimal("0")
    total_return_pct: float = 0.0

    # Risk-adjusted
    sharpe_ratio: float | None = None      # annualized, risk-free=0 (Indian T-bill approx)
    sortino_ratio: float | None = None
    calmar_ratio: float | None = None
    information_ratio: float | None = None  # vs benchmark

    # Drawdown
    max_drawdown_pct: float = 0.0
    max_drawdown_inr: Decimal = Decimal("0")
    current_drawdown_pct: float = 0.0

    # Win/loss statistics
    total_trades: int = 0
    winning_trades: int = 0
    losing_trades: int = 0
    win_rate_pct: float = 0.0
    avg_win_inr: Decimal = Decimal("0")
    avg_loss_inr: Decimal = Decimal("0")
    profit_factor: float | None = None     # gross_profit / gross_loss

    # Benchmark comparison
    benchmark_return_pct: float | None = None
    alpha: float | None = None             # Jensen's alpha
    beta: float | None = None

    # Turnover
    turnover_inr: Decimal = Decimal("0")
    commission_drag_inr: Decimal = Decimal("0")

    # CAGR (only meaningful for longer windows)
    cagr_pct: float | None = None


# ─────────────────────────────────────────────────────────────────────────────
# Portfolio snapshot (persisted + published)
# ─────────────────────────────────────────────────────────────────────────────

class PositionSummary(BaseModel):
    """Serializable position summary embedded in snapshot JSONB."""
    symbol: str
    net_quantity: int
    avg_cost_inr: float
    market_price_inr: float | None
    market_value_inr: float
    unrealized_pnl_inr: float
    realized_pnl_inr: float
    weight_pct: float             # % of total portfolio equity


class PortfolioSnapshot(BaseModel):
    """
    Point-in-time portfolio state.

    Source of truth for risk_engine's /portfolio/snapshot call —
    8009 is canonical; risk_engine should point here, not broker_service.
    """
    snapshot_id: uuid.UUID = Field(default_factory=uuid.uuid4)
    snapshot_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    # Capital
    initial_capital_inr: Decimal
    cash_balance_inr: Decimal
    equity_value_inr: Decimal              # sum of all position market values
    total_value_inr: Decimal               # cash + equity

    # P&L
    day_pnl_inr: Decimal = Decimal("0")
    total_pnl_inr: Decimal = Decimal("0")
    total_return_pct: float = 0.0

    # Exposure
    gross_exposure_inr: Decimal = Decimal("0")   # sum |market_value|
    net_exposure_inr: Decimal = Decimal("0")     # sum market_value (long - short)
    gross_exposure_pct: float = 0.0              # % of total_value
    open_position_count: int = 0

    # Positions detail
    positions: list[PositionSummary] = Field(default_factory=list)

    # Performance (30d inline, full breakdown via /performance endpoint)
    performance_30d: PerformanceMetrics | None = None

    metrics: dict[str, Any] = Field(default_factory=dict)


# ─────────────────────────────────────────────────────────────────────────────
# Outbound: portfolio event published to sg:portfolio:events
# ─────────────────────────────────────────────────────────────────────────────

class PortfolioEventType(StrEnum):
    POSITION_OPENED = "POSITION_OPENED"
    POSITION_UPDATED = "POSITION_UPDATED"
    POSITION_CLOSED = "POSITION_CLOSED"
    SNAPSHOT_READY = "SNAPSHOT_READY"


class PortfolioEvent(BaseModel):
    event_type: PortfolioEventType
    symbol: str | None = None
    snapshot_id: uuid.UUID | None = None
    emitted_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    payload: dict[str, Any] = Field(default_factory=dict)
