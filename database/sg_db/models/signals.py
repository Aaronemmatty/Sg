"""Strategy signal events."""

from datetime import datetime
from decimal import Decimal
from typing import Any, Optional
from uuid import UUID

from sqlalchemy import DateTime, Enum, ForeignKey, Index, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from sg_db.base import Base
from sg_db.enums import SignalSide, SignalType, Timeframe, TradingMode
from sg_db.mixins import TenantMixin
from sg_db.types import PRICE, QUANTITY


class Signal(Base, TenantMixin):
    """Strategy-generated trading signal — partitioned by created_at."""

    __tablename__ = "signals"
    __table_args__ = (
        Index("ix_signals_tenant_strategy_created", "tenant_id", "strategy_id", "created_at"),
        Index("ix_signals_tenant_symbol_created", "tenant_id", "symbol", "created_at"),
        Index("ix_signals_correlation", "correlation_id"),
        Index("ix_signals_instance_bar", "strategy_instance_id", "bar_ts"),
        {"postgresql_partition_by": "RANGE (created_at)"},
    )

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        primary_key=True,
        server_default=func.gen_random_uuid(),
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        primary_key=True,
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
    strategy_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("strategies.id", ondelete="CASCADE"),
        nullable=False,
    )
    strategy_instance_id: Mapped[str] = mapped_column(String(64), nullable=False)
    portfolio_id: Mapped[Optional[UUID]] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    symbol: Mapped[str] = mapped_column(String(32), nullable=False)
    signal_type: Mapped[SignalType] = mapped_column(
        Enum(SignalType, name="signal_type", native_enum=False),
        nullable=False,
    )
    side: Mapped[SignalSide] = mapped_column(
        Enum(SignalSide, name="signal_side", native_enum=False),
        nullable=False,
    )
    quantity: Mapped[Optional[Decimal]] = mapped_column(QUANTITY, nullable=True)
    limit_price: Mapped[Optional[Decimal]] = mapped_column(PRICE, nullable=True)
    strength: Mapped[Optional[Decimal]] = mapped_column(nullable=True)
    timeframe: Mapped[Timeframe] = mapped_column(
        Enum(Timeframe, name="timeframe", create_type=False, native_enum=False),
        nullable=False,
    )
    bar_ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    mode: Mapped[TradingMode] = mapped_column(
        Enum(TradingMode, name="trading_mode", create_type=False, native_enum=False),
        nullable=False,
        default=TradingMode.PAPER,
    )
    reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    correlation_id: Mapped[str] = mapped_column(String(64), nullable=False)
    metadata_: Mapped[dict[str, Any]] = mapped_column("metadata", JSONB, nullable=False, default=dict)

    strategy: Mapped["Strategy"] = relationship()  # noqa: F821
