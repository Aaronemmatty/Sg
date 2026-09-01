"""Core trading domain: strategies, orders, trades, positions."""

from datetime import datetime
from decimal import Decimal
from typing import Any, Optional
from uuid import UUID

from sqlalchemy import (
    DateTime,
    Enum,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID as PG_UUID
from sqlalchemy.orm import Mapped, foreign, mapped_column, relationship

from sg_db.base import Base
from sg_db.enums import OrderSide, OrderStatus, OrderType, StrategyStatus, TradingMode
from sg_db.mixins import SoftDeleteMixin, TenantMixin, TimestampMixin, UUIDPrimaryKeyMixin
from sg_db.types import MONEY, PRICE, QUANTITY


class Strategy(Base, UUIDPrimaryKeyMixin, TenantMixin, TimestampMixin, SoftDeleteMixin):
    """Registered trading strategy definition."""

    __tablename__ = "strategies"
    __table_args__ = (
        UniqueConstraint("tenant_id", "name", "version", name="uq_strategies_tenant_name_version"),
        Index("ix_strategies_tenant_status", "tenant_id", "status", postgresql_where="deleted_at IS NULL"),
    )

    name: Mapped[str] = mapped_column(String(128), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    version: Mapped[str] = mapped_column(String(32), nullable=False, default="1.0.0")
    strategy_type: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[StrategyStatus] = mapped_column(
        Enum(StrategyStatus, name="strategy_status", native_enum=False),
        nullable=False,
        default=StrategyStatus.DRAFT,
    )
    config: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    parameters: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    supported_timeframes: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    created_by: Mapped[Optional[UUID]] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    orders: Mapped[list["Order"]] = relationship(back_populates="strategy")


class Order(Base, TenantMixin, SoftDeleteMixin):
    """Order aggregate — partitioned monthly; PK includes created_at per PG requirements."""

    __tablename__ = "orders"
    __table_args__ = (
        UniqueConstraint("tenant_id", "idempotency_key", name="uq_orders_tenant_idempotency"),
        Index("ix_orders_tenant_portfolio_status", "tenant_id", "portfolio_id", "status"),
        Index("ix_orders_tenant_symbol_created", "tenant_id", "symbol", "created_at"),
        Index("ix_orders_correlation", "correlation_id"),
        Index("ix_orders_broker", "broker_order_id", postgresql_where="broker_order_id IS NOT NULL"),
        Index("ix_orders_active", "tenant_id", "status", postgresql_where="deleted_at IS NULL"),
        {"postgresql_partition_by": "RANGE (created_at)"},
    )

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        primary_key=True,
        server_default=func.gen_random_uuid(),
    )
    # Partition key — must be part of PK on partitioned tables.
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
    portfolio_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("portfolios.id", ondelete="CASCADE"),
        nullable=False,
    )
    strategy_id: Mapped[Optional[UUID]] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("strategies.id", ondelete="SET NULL"),
        nullable=True,
    )
    symbol: Mapped[str] = mapped_column(String(32), nullable=False)
    exchange: Mapped[str] = mapped_column(String(32), nullable=False, default="SMART")
    side: Mapped[OrderSide] = mapped_column(
        Enum(OrderSide, name="order_side", native_enum=False),
        nullable=False,
    )
    order_type: Mapped[OrderType] = mapped_column(
        Enum(OrderType, name="order_type", native_enum=False),
        nullable=False,
    )
    quantity: Mapped[Decimal] = mapped_column(QUANTITY, nullable=False)
    filled_quantity: Mapped[Decimal] = mapped_column(QUANTITY, nullable=False, default=0)
    limit_price: Mapped[Optional[Decimal]] = mapped_column(PRICE, nullable=True)
    stop_price: Mapped[Optional[Decimal]] = mapped_column(PRICE, nullable=True)
    avg_fill_price: Mapped[Optional[Decimal]] = mapped_column(PRICE, nullable=True)
    status: Mapped[OrderStatus] = mapped_column(
        Enum(OrderStatus, name="order_status", native_enum=False),
        nullable=False,
        default=OrderStatus.PENDING,
    )
    mode: Mapped[TradingMode] = mapped_column(
        Enum(TradingMode, name="trading_mode", native_enum=False),
        nullable=False,
        default=TradingMode.PAPER,
    )
    idempotency_key: Mapped[str] = mapped_column(String(64), nullable=False)
    correlation_id: Mapped[str] = mapped_column(String(64), nullable=False)
    broker_order_id: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    reject_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    metadata_: Mapped[dict[str, Any]] = mapped_column("metadata", JSONB, nullable=False, default=dict)
    submitted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    filled_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    cancelled_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    strategy: Mapped[Optional["Strategy"]] = relationship(back_populates="orders")
    trades: Mapped[list["Trade"]] = relationship(
        "Trade",
        primaryjoin="Order.id == foreign(Trade.order_id)",
        back_populates="order",
    )


class Trade(Base, TenantMixin, TimestampMixin):
    """Execution fill record — immutable after insert."""

    __tablename__ = "trades"
    __table_args__ = (
        UniqueConstraint("tenant_id", "broker_trade_id", name="uq_trades_tenant_broker_trade"),
        Index("ix_trades_tenant_order", "tenant_id", "order_id", "order_created_at"),
        Index("ix_trades_tenant_symbol_executed", "tenant_id", "symbol", "executed_at"),
        Index("ix_trades_portfolio_executed", "tenant_id", "portfolio_id", "executed_at"),
        {"postgresql_partition_by": "RANGE (executed_at)"},
    )

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        primary_key=True,
        server_default=func.gen_random_uuid(),
    )
    executed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        primary_key=True,
        nullable=False,
    )
    order_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    order_created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    portfolio_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    strategy_id: Mapped[Optional[UUID]] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("strategies.id", ondelete="SET NULL"),
        nullable=True,
    )
    symbol: Mapped[str] = mapped_column(String(32), nullable=False)
    side: Mapped[OrderSide] = mapped_column(
        Enum(OrderSide, name="order_side", create_type=False, native_enum=False),
        nullable=False,
    )
    quantity: Mapped[Decimal] = mapped_column(QUANTITY, nullable=False)
    price: Mapped[Decimal] = mapped_column(PRICE, nullable=False)
    commission: Mapped[Decimal] = mapped_column(MONEY, nullable=False, default=0)
    fees: Mapped[Decimal] = mapped_column(MONEY, nullable=False, default=0)
    mode: Mapped[TradingMode] = mapped_column(
        Enum(TradingMode, name="trading_mode", create_type=False, native_enum=False),
        nullable=False,
    )
    broker_trade_id: Mapped[str] = mapped_column(String(128), nullable=False)
    correlation_id: Mapped[str] = mapped_column(String(64), nullable=False)

    order: Mapped[Optional["Order"]] = relationship(
        "Order",
        primaryjoin="foreign(Trade.order_id) == Order.id",
        back_populates="trades",
    )


class Position(Base, UUIDPrimaryKeyMixin, TenantMixin, TimestampMixin):
    """Current position state — one row per portfolio + symbol."""

    __tablename__ = "positions"
    __table_args__ = (
        UniqueConstraint("tenant_id", "portfolio_id", "symbol", name="uq_positions_tenant_portfolio_symbol"),
        Index("ix_positions_tenant_portfolio", "tenant_id", "portfolio_id"),
        Index("ix_positions_tenant_symbol", "tenant_id", "symbol"),
    )

    portfolio_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    symbol: Mapped[str] = mapped_column(String(32), nullable=False)
    exchange: Mapped[str] = mapped_column(String(32), nullable=False, default="SMART")
    quantity: Mapped[Decimal] = mapped_column(QUANTITY, nullable=False, default=0)
    avg_cost: Mapped[Decimal] = mapped_column(PRICE, nullable=False, default=0)
    market_price: Mapped[Optional[Decimal]] = mapped_column(PRICE, nullable=True)
    market_value: Mapped[Decimal] = mapped_column(MONEY, nullable=False, default=0)
    unrealized_pnl: Mapped[Decimal] = mapped_column(MONEY, nullable=False, default=0)
    realized_pnl: Mapped[Decimal] = mapped_column(MONEY, nullable=False, default=0)
    mode: Mapped[TradingMode] = mapped_column(
        Enum(TradingMode, name="trading_mode", create_type=False, native_enum=False),
        nullable=False,
    )
    last_trade_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    version: Mapped[int] = mapped_column(nullable=False, default=1, server_default="1")
