"""
Persistence models for the regime detection service.

Follows the platform-wide conventions already established by the other services:
UUID primary keys, tenant_id row-level-security column, TimestampMixin, SoftDeleteMixin,
and partitioning by timestamp for high-volume append-mostly tables (mirroring
`market_data.MarketBar`, `signals.Signal`, and `risk.RiskEvent`).

NOTE ON IMPORTS: this file assumes `sg_db.common` exposes `Base`, `TimestampMixin`,
`SoftDeleteMixin`, `TenantMixin`, and a `uuid_pk()` column factory, since the brief states
these already exist platform-wide. If your actual package path differs, this is the only
file that needs to change — everything else in this service talks to the ORM only through
`app/services/market_data_client.py` and `app/db/session.py`.
"""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    Float,
    ForeignKey,
    Index,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

try:
    # Shared platform base classes (already exist in sg_db per the project brief).
    from sg_db.common import Base, SoftDeleteMixin, TenantMixin, TimestampMixin, uuid_pk
except ImportError:  # pragma: no cover - allows this service to run standalone for tests/dev
    from app.db._sg_db_compat import (  # type: ignore
        Base,
        SoftDeleteMixin,
        TenantMixin,
        TimestampMixin,
        uuid_pk,
    )


class RegimeSnapshot(Base, TimestampMixin, SoftDeleteMixin, TenantMixin):
    """
    One classification result per (symbol, timeframe, timestamp).

    Partitioned by `timestamp` (range, monthly) in the same style as `market_data.MarketBar`
    and `signals.Signal` — see app/db/migrations for the partition DDL.
    """

    __tablename__ = "regime_snapshots"
    __table_args__ = (
        UniqueConstraint("symbol", "timeframe", "timestamp", "tenant_id", name="uq_regime_snapshot"),
        Index("ix_regime_snapshots_symbol_tf_ts", "symbol", "timeframe", "timestamp"),
        {"postgresql_partition_by": "RANGE (timestamp)"},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    symbol: Mapped[str] = mapped_column(String(32), nullable=False)
    exchange: Mapped[str] = mapped_column(String(16), nullable=False, default="NSE")
    timeframe: Mapped[str] = mapped_column(String(8), nullable=False)
    timestamp: Mapped[datetime] = mapped_column(nullable=False)

    regime: Mapped[str] = mapped_column(String(32), nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    sub_regimes: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    features: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    model_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    is_override: Mapped[bool] = mapped_column(default=False)

    def __repr__(self) -> str:  # pragma: no cover
        return f"<RegimeSnapshot {self.symbol}:{self.timeframe} {self.regime}@{self.timestamp}>"


class RegimeTransitionRecord(Base, TimestampMixin, SoftDeleteMixin, TenantMixin):
    """Audit trail of confirmed regime changes (post-debounce), used for alerts/history."""

    __tablename__ = "regime_transitions"
    __table_args__ = (
        Index("ix_regime_transitions_symbol_tf_ts", "symbol", "timeframe", "timestamp"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    symbol: Mapped[str] = mapped_column(String(32), nullable=False)
    timeframe: Mapped[str] = mapped_column(String(8), nullable=False)
    timestamp: Mapped[datetime] = mapped_column(nullable=False)

    from_regime: Mapped[str | None] = mapped_column(String(32), nullable=True)
    to_regime: Mapped[str] = mapped_column(String(32), nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    trigger_reason: Mapped[str] = mapped_column(String(64), nullable=False)

    snapshot_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("regime_snapshots.id"), nullable=True
    )
    snapshot: Mapped["RegimeSnapshot | None"] = relationship(viewonly=True)

    def __repr__(self) -> str:  # pragma: no cover
        return f"<RegimeTransition {self.symbol} {self.from_regime}->{self.to_regime}@{self.timestamp}>"
