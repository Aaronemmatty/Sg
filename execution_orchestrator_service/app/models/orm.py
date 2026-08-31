"""SQLAlchemy ORM — trade_intents table."""
from __future__ import annotations

from datetime import datetime
from typing import Optional
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Float,
    Index,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID as PG_UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class TradeIntentORM(Base):
    __tablename__ = "trade_intents"

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        primary_key=True,
        server_default=func.gen_random_uuid(),
    )
    intent_id: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    correlation_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)

    # Signal identifiers
    symbol: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    timeframe: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    action: Mapped[str] = mapped_column(String(8), nullable=False)          # BUY | SELL | HOLD

    # Eligibility
    status: Mapped[str] = mapped_column(String(16), nullable=False, index=True)   # ELIGIBLE | REJECTED | HOLD
    rejection_reasons: Mapped[Optional[list]] = mapped_column(ARRAY(String), nullable=True)
    rejection_detail: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Signal quality
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    net_score: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    agreement_ratio: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    contributors: Mapped[Optional[list]] = mapped_column(ARRAY(String), nullable=True)

    # Allocation
    allocation_inr: Mapped[float] = mapped_column(Float, nullable=False)
    risk_percent: Mapped[float] = mapped_column(Float, nullable=False)

    # Context
    market_regime: Mapped[str] = mapped_column(String(32), nullable=False)
    portfolio_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True, index=True)

    # Snapshot values at decision time (audit)
    snapshot_portfolio_value_inr: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    snapshot_daily_loss_inr: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    snapshot_drawdown_pct: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    snapshot_open_intents: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    # Extra metadata blob
    meta: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)

    # Timestamps
    signal_timestamp: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    __table_args__ = (
        Index("ix_trade_intents_symbol_created", "symbol", "created_at"),
        Index("ix_trade_intents_status_created", "status", "created_at"),
        Index("ix_trade_intents_portfolio_status", "portfolio_id", "status"),
    )


class OrchestratorAuditLogORM(Base):
    """Full audit trail — one row per eligibility check per signal."""
    __tablename__ = "orchestrator_audit_logs"

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        primary_key=True,
        server_default=func.gen_random_uuid(),
    )
    intent_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    symbol: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    check_name: Mapped[str] = mapped_column(String(64), nullable=False)
    passed: Mapped[bool] = mapped_column(Boolean, nullable=False)
    reason: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    detail: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    __table_args__ = (
        Index("ix_audit_intent_id", "intent_id"),
        Index("ix_audit_symbol_created", "symbol", "created_at"),
    )
