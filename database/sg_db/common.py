"""Compatibility exports for services expecting ``sg_db.common``."""

from __future__ import annotations

import uuid

from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from sg_db.base import Base
from sg_db.mixins import SoftDeleteMixin, TenantMixin, TimestampMixin, UUIDPrimaryKeyMixin


def uuid_pk() -> Mapped[uuid.UUID]:
    """Mapped UUID primary key column (compat helper for Alembic models)."""
    return mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)


__all__ = [
    "Base",
    "SoftDeleteMixin",
    "TenantMixin",
    "TimestampMixin",
    "UUIDPrimaryKeyMixin",
    "uuid_pk",
]
