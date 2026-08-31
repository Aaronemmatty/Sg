"""Tenant aggregate — root of multi-tenant isolation."""

from typing import TYPE_CHECKING, Any, Optional

if TYPE_CHECKING:
    from sg_db.models.identity import User

from sqlalchemy import Enum, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from sg_db.base import Base
from sg_db.enums import TenantStatus
from sg_db.mixins import SoftDeleteMixin, TimestampMixin, UUIDPrimaryKeyMixin


class Tenant(Base, UUIDPrimaryKeyMixin, TimestampMixin, SoftDeleteMixin):
    """Top-level tenant (organization) record."""

    __tablename__ = "tenants"
    __table_args__ = (
        UniqueConstraint("slug", name="uq_tenants_slug"),
    )

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    slug: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[TenantStatus] = mapped_column(
        Enum(TenantStatus, name="tenant_status", native_enum=False),
        nullable=False,
        default=TenantStatus.ACTIVE,
    )
    settings: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    billing_email: Mapped[Optional[str]] = mapped_column(String(320), nullable=True)

    users: Mapped[list["User"]] = relationship(back_populates="tenant")
