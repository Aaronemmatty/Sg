"""Auth-service-owned ORM models.

These extend sg_db without modifying its core models.
All tables are tenant-scoped and follow sg_db conventions.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import INET, JSONB, UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from sg_db.base import Base
from sg_db.mixins import SoftDeleteMixin, TenantMixin, TimestampMixin, UUIDPrimaryKeyMixin


class UserSession(Base, UUIDPrimaryKeyMixin, TenantMixin, TimestampMixin, SoftDeleteMixin):
    """Active user session — tracks device, expiry, and refresh token reference."""

    __tablename__ = "user_sessions"
    __table_args__ = (
        Index("ix_user_sessions_tenant_user", "tenant_id", "user_id", postgresql_where="deleted_at IS NULL"),
        Index("ix_user_sessions_refresh_jti", "refresh_jti"),
        Index("ix_user_sessions_expires", "expires_at"),
    )

    user_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    refresh_jti: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)
    device_id: Mapped[Optional[UUID]] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("user_devices.id", ondelete="SET NULL"),
        nullable=True,
    )
    ip_address: Mapped[Optional[str]] = mapped_column(INET, nullable=True)
    user_agent: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_active_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    revoke_reason: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    metadata_: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, nullable=False, default=dict
    )


class UserDevice(Base, UUIDPrimaryKeyMixin, TenantMixin, TimestampMixin, SoftDeleteMixin):
    """Tracked device — fingerprinted by UA + IP subnet."""

    __tablename__ = "user_devices"
    __table_args__ = (
        UniqueConstraint("tenant_id", "user_id", "device_fingerprint", name="uq_user_devices_fingerprint"),
        Index("ix_user_devices_tenant_user", "tenant_id", "user_id", postgresql_where="deleted_at IS NULL"),
    )

    user_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    device_fingerprint: Mapped[str] = mapped_column(String(128), nullable=False)
    device_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    device_type: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)   # mobile/desktop/bot
    os: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    browser: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    is_trusted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    trusted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    last_seen_ip: Mapped[Optional[str]] = mapped_column(INET, nullable=True)
    last_seen_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    login_count: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)


class PasswordResetToken(Base, UUIDPrimaryKeyMixin, TenantMixin, TimestampMixin):
    """Single-use password reset token — hashed at rest."""

    __tablename__ = "password_reset_tokens"
    __table_args__ = (
        Index("ix_password_reset_token_hash", "token_hash"),
        Index("ix_password_reset_user", "user_id", "expires_at"),
    )

    user_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    token_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    used_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    ip_requested: Mapped[Optional[str]] = mapped_column(INET, nullable=True)


class EmailVerificationToken(Base, UUIDPrimaryKeyMixin, TenantMixin, TimestampMixin):
    """Single-use email verification token."""

    __tablename__ = "email_verification_tokens"
    __table_args__ = (
        Index("ix_email_verify_token_hash", "token_hash"),
        Index("ix_email_verify_user", "user_id"),
    )

    user_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    email: Mapped[str] = mapped_column(String(320), nullable=False)
    token_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    verified_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)


class OAuthAccount(Base, UUIDPrimaryKeyMixin, TenantMixin, TimestampMixin, SoftDeleteMixin):
    """OAuth2 provider account linked to a platform user."""

    __tablename__ = "oauth_accounts"
    __table_args__ = (
        UniqueConstraint("provider", "provider_user_id", name="uq_oauth_accounts_provider_uid"),
        Index("ix_oauth_accounts_user", "user_id"),
    )

    user_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    provider: Mapped[str] = mapped_column(String(32), nullable=False)           # google, github …
    provider_user_id: Mapped[str] = mapped_column(String(255), nullable=False)
    provider_email: Mapped[Optional[str]] = mapped_column(String(320), nullable=True)
    access_token_enc: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # encrypted
    refresh_token_enc: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    token_expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    raw_profile: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)


class MfaBackupCode(Base, UUIDPrimaryKeyMixin, TenantMixin, TimestampMixin):
    """Hashed one-time backup codes for MFA recovery."""

    __tablename__ = "mfa_backup_codes"
    __table_args__ = (
        Index("ix_mfa_backup_codes_user", "user_id", postgresql_where="used_at IS NULL"),
    )

    user_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    code_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    used_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
