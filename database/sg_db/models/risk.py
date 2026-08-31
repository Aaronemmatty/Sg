"""Risk management events."""

from datetime import datetime
from typing import Any, Optional
from uuid import UUID

from sqlalchemy import DateTime, Enum, ForeignKey, Index, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from sg_db.base import Base
from sg_db.enums import RiskEventType, RiskSeverity
from sg_db.mixins import TenantMixin, TimestampMixin, UUIDPrimaryKeyMixin


class RiskEvent(Base, TenantMixin):
    """Risk limit breach, pre-trade rejection, or kill-switch event."""

    __tablename__ = "risk_events"
    __table_args__ = (
        Index("ix_risk_events_tenant_portfolio_created", "tenant_id", "portfolio_id", "created_at"),
        Index("ix_risk_events_tenant_type_severity", "tenant_id", "event_type", "severity"),
        Index("ix_risk_events_unresolved", "tenant_id", "resolved_at", postgresql_where="resolved_at IS NULL"),
        Index("ix_risk_events_order", "order_id", postgresql_where="order_id IS NOT NULL"),
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
    portfolio_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    event_type: Mapped[RiskEventType] = mapped_column(
        Enum(RiskEventType, name="risk_event_type", native_enum=False),
        nullable=False,
    )
    severity: Mapped[RiskSeverity] = mapped_column(
        Enum(RiskSeverity, name="risk_severity", native_enum=False),
        nullable=False,
    )
    order_id: Mapped[Optional[UUID]] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    order_created_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    strategy_id: Mapped[Optional[UUID]] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("strategies.id", ondelete="SET NULL"),
        nullable=True,
    )
    message: Mapped[str] = mapped_column(Text, nullable=False)
    details: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    correlation_id: Mapped[str] = mapped_column(String(64), nullable=False)
    resolved_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    resolved_by: Mapped[Optional[UUID]] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    resolution_note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
