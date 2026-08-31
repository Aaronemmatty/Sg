"""
Persistence models for signal_aggregation_service. Same UUID PK / tenant_id RLS /
TimestampMixin / SoftDeleteMixin conventions as the rest of the platform (see
regime_detection_service/app/models/db.py for the identical import-path rationale).
"""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Float, Index, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

try:
    from sg_db.common import Base, SoftDeleteMixin, TenantMixin, TimestampMixin, uuid_pk
except ImportError:  # pragma: no cover - standalone/test fallback
    from app.db._sg_db_compat import (  # type: ignore
        Base,
        SoftDeleteMixin,
        TenantMixin,
        TimestampMixin,
        uuid_pk,
    )


class AggregatedSignal(Base, TimestampMixin, SoftDeleteMixin, TenantMixin):
    """One consensus aggregation result per (symbol, timeframe, timestamp). Partitioned
    by `timestamp` (monthly range), mirroring `signals.Signal` / `regime_snapshots`."""

    __tablename__ = "aggregated_signals"
    __table_args__ = (
        UniqueConstraint("symbol", "timeframe", "timestamp", "tenant_id", name="uq_aggregated_signal"),
        Index("ix_aggregated_signals_symbol_tf_ts", "symbol", "timeframe", "timestamp"),
        {"postgresql_partition_by": "RANGE (timestamp)"},
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    symbol: Mapped[str] = mapped_column(String(32), nullable=False)
    timeframe: Mapped[str] = mapped_column(String(8), nullable=False)
    timestamp: Mapped[datetime] = mapped_column(nullable=False)

    final_signal: Mapped[str] = mapped_column(String(8), nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    contributors: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    regime: Mapped[str | None] = mapped_column(String(32), nullable=True)
    net_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    agreement_ratio: Mapped[float | None] = mapped_column(Float, nullable=True)
    votes: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    weights_version: Mapped[str | None] = mapped_column(String(64), nullable=True)

    def __repr__(self) -> str:  # pragma: no cover
        return f"<AggregatedSignal {self.symbol}:{self.timeframe} {self.final_signal}@{self.timestamp}>"


class StrategyWeightOverride(Base, TimestampMixin, SoftDeleteMixin, TenantMixin):
    """
    DB-backed override layer on top of the static DEFAULT_REGIME_WEIGHTS in config.py.
    One row per (tenant, regime, strategy). Updated via the /api/v1/weights endpoints;
    `updated_at` (from TimestampMixin) doubles as the change-audit timestamp, and a
    change also fires `sg:weights:updated` so live engine instances invalidate their cache.
    """

    __tablename__ = "strategy_weight_overrides"
    __table_args__ = (
        UniqueConstraint("regime", "strategy", "tenant_id", name="uq_weight_override"),
        Index("ix_weight_overrides_regime", "regime"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    regime: Mapped[str] = mapped_column(String(32), nullable=False)
    strategy: Mapped[str] = mapped_column(String(64), nullable=False)
    weight: Mapped[float] = mapped_column(Float, nullable=False)
    updated_by: Mapped[str | None] = mapped_column(String(128), nullable=True)

    def __repr__(self) -> str:  # pragma: no cover
        return f"<StrategyWeightOverride {self.regime}:{self.strategy}={self.weight}>"
