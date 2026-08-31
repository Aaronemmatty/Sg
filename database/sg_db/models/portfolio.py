"""Portfolio aggregate and point-in-time snapshots."""

from datetime import datetime
from decimal import Decimal
from typing import Any, Optional
from uuid import UUID

from sqlalchemy import DateTime, Enum, ForeignKey, Index, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB, UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from sg_db.base import Base
from sg_db.enums import TradingMode
from sg_db.mixins import SoftDeleteMixin, TenantMixin, TimestampMixin, UUIDPrimaryKeyMixin
from sg_db.types import MONEY


class Portfolio(Base, UUIDPrimaryKeyMixin, TenantMixin, TimestampMixin, SoftDeleteMixin):
    """Trading portfolio / account container."""

    __tablename__ = "portfolios"
    __table_args__ = (
        UniqueConstraint("tenant_id", "name", name="uq_portfolios_tenant_name"),
        Index("ix_portfolios_tenant_active", "tenant_id", postgresql_where="deleted_at IS NULL"),
    )

    name: Mapped[str] = mapped_column(String(128), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    base_currency: Mapped[str] = mapped_column(String(3), nullable=False, default="USD")
    mode: Mapped[TradingMode] = mapped_column(
        Enum(TradingMode, name="trading_mode", create_type=False, native_enum=False),
        nullable=False,
        default=TradingMode.PAPER,
    )
    initial_capital: Mapped[Decimal] = mapped_column(MONEY, nullable=False, default=0)
    cash_balance: Mapped[Decimal] = mapped_column(MONEY, nullable=False, default=0)
    is_default: Mapped[bool] = mapped_column(nullable=False, default=False)
    settings: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    owner_id: Mapped[Optional[UUID]] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    snapshots: Mapped[list["PortfolioSnapshot"]] = relationship(back_populates="portfolio")


class PortfolioSnapshot(Base, TenantMixin, TimestampMixin):
    """Immutable portfolio state at a point in time — partitioned by snapshot_at."""

    __tablename__ = "portfolio_snapshots"
    __table_args__ = (
        Index("ix_portfolio_snapshots_tenant_portfolio_ts", "tenant_id", "portfolio_id", "snapshot_at"),
        Index("ix_portfolio_snapshots_snapshot_at", "snapshot_at"),
        {"postgresql_partition_by": "RANGE (snapshot_at)"},
    )

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        primary_key=True,
        server_default=func.gen_random_uuid(),
    )
    snapshot_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        primary_key=True,
        nullable=False,
    )
    portfolio_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("portfolios.id", ondelete="CASCADE"),
        nullable=False,
    )
    total_value: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    cash: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    equity: Mapped[Decimal] = mapped_column(MONEY, nullable=False)
    day_pnl: Mapped[Decimal] = mapped_column(MONEY, nullable=False, default=0)
    total_pnl: Mapped[Decimal] = mapped_column(MONEY, nullable=False, default=0)
    positions: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False, default=list)
    metrics: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)

    portfolio: Mapped["Portfolio"] = relationship(back_populates="snapshots")
