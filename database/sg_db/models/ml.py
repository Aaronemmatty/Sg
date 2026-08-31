"""ML model registry and inference predictions."""

from datetime import datetime
from decimal import Decimal
from typing import Any, Optional
from uuid import UUID

from sqlalchemy import DateTime, Enum, ForeignKey, Index, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB, UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from sg_db.base import Base
from sg_db.enums import ModelStatus
from sg_db.mixins import SoftDeleteMixin, TenantMixin, TimestampMixin, UUIDPrimaryKeyMixin


class MlModel(Base, UUIDPrimaryKeyMixin, TenantMixin, TimestampMixin, SoftDeleteMixin):
    """Model registry entry — tracks versions and deployment lifecycle."""

    __tablename__ = "ml_models"
    __table_args__ = (
        UniqueConstraint("tenant_id", "name", "version", name="uq_ml_models_tenant_name_version"),
        Index("ix_ml_models_tenant_status", "tenant_id", "status", postgresql_where="deleted_at IS NULL"),
        Index("ix_ml_models_production", "tenant_id", "name", postgresql_where="status = 'production'"),
    )

    name: Mapped[str] = mapped_column(String(128), nullable=False)
    version: Mapped[str] = mapped_column(String(32), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    framework: Mapped[str] = mapped_column(String(64), nullable=False)
    artifact_uri: Mapped[str] = mapped_column(String(512), nullable=False)
    feature_schema: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    hyperparameters: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    metrics: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    status: Mapped[ModelStatus] = mapped_column(
        Enum(ModelStatus, name="model_status", native_enum=False),
        nullable=False,
        default=ModelStatus.TRAINING,
    )
    deployed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_by: Mapped[Optional[UUID]] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    predictions: Mapped[list["MlPrediction"]] = relationship(back_populates="model")


class MlPrediction(Base, TenantMixin, TimestampMixin):
    """Point-in-time ML inference output — partitioned by predicted_at."""

    __tablename__ = "ml_predictions"
    __table_args__ = (
        Index("ix_ml_predictions_tenant_model_predicted", "tenant_id", "model_id", "predicted_at"),
        Index("ix_ml_predictions_tenant_symbol_predicted", "tenant_id", "symbol", "predicted_at"),
        Index("ix_ml_predictions_correlation", "correlation_id"),
        {"postgresql_partition_by": "RANGE (predicted_at)"},
    )

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        primary_key=True,
        server_default=func.gen_random_uuid(),
    )
    predicted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        primary_key=True,
        nullable=False,
    )
    model_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("ml_models.id", ondelete="CASCADE"),
        nullable=False,
    )
    strategy_id: Mapped[Optional[UUID]] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("strategies.id", ondelete="SET NULL"),
        nullable=True,
    )
    symbol: Mapped[str] = mapped_column(String(32), nullable=False)
    horizon: Mapped[str] = mapped_column(String(32), nullable=False)
    prediction: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    confidence: Mapped[Optional[Decimal]] = mapped_column(nullable=True)
    features_hash: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    correlation_id: Mapped[str] = mapped_column(String(64), nullable=False)
    latency_ms: Mapped[Optional[int]] = mapped_column(nullable=True)

    model: Mapped["MlModel"] = relationship(back_populates="predictions")
