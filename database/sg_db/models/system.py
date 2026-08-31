"""Platform-level system events."""

from datetime import datetime
from typing import Any, Optional
from uuid import UUID

from sqlalchemy import DateTime, Enum, Index, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from sg_db.base import Base
from sg_db.enums import SystemEventSeverity
from sg_db.mixins import UUIDPrimaryKeyMixin


class SystemEvent(Base):
    """Operational/system event stream — tenant_id nullable for platform-wide events."""

    __tablename__ = "system_events"
    __table_args__ = (
        Index("ix_system_events_tenant_created", "tenant_id", "created_at"),
        Index("ix_system_events_type_severity", "event_type", "severity", "created_at"),
        Index("ix_system_events_source", "source_service", "created_at"),
        Index("ix_system_events_correlation", "correlation_id"),
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
        nullable=False,
    )
    tenant_id: Mapped[Optional[UUID]] = mapped_column(PG_UUID(as_uuid=True), nullable=True)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    source_service: Mapped[str] = mapped_column(String(64), nullable=False)
    severity: Mapped[SystemEventSeverity] = mapped_column(
        Enum(SystemEventSeverity, name="system_event_severity", native_enum=False),
        nullable=False,
    )
    message: Mapped[str] = mapped_column(Text, nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    correlation_id: Mapped[str] = mapped_column(String(64), nullable=False)
