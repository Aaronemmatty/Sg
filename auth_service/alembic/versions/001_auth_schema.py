"""Initial auth service schema — sessions, devices, tokens, oauth, MFA backup codes.

Revision ID: 001_auth_schema
Revises: 001_initial_schema  (sg_db base migration)
Create Date: 2026-01-01 00:00:00
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import INET, JSONB, UUID

revision = "001_auth_schema"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── user_sessions ─────────────────────────────────────────────────────────
    op.create_table(
        "user_sessions",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", UUID(as_uuid=True), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("refresh_jti", sa.String(128), nullable=False, unique=True),
        sa.Column("device_id", UUID(as_uuid=True), nullable=True),
        sa.Column("ip_address", INET, nullable=True),
        sa.Column("user_agent", sa.Text, nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_active_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoke_reason", sa.String(64), nullable=True),
        sa.Column("metadata", JSONB, nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_user_sessions_tenant_user", "user_sessions", ["tenant_id", "user_id"],
                    postgresql_where=sa.text("deleted_at IS NULL"))
    op.create_index("ix_user_sessions_refresh_jti", "user_sessions", ["refresh_jti"])
    op.create_index("ix_user_sessions_expires", "user_sessions", ["expires_at"])

    # ── user_devices ──────────────────────────────────────────────────────────
    op.create_table(
        "user_devices",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", UUID(as_uuid=True), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("device_fingerprint", sa.String(128), nullable=False),
        sa.Column("device_name", sa.String(255), nullable=True),
        sa.Column("device_type", sa.String(64), nullable=True),
        sa.Column("os", sa.String(64), nullable=True),
        sa.Column("browser", sa.String(64), nullable=True),
        sa.Column("is_trusted", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("trusted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_seen_ip", INET, nullable=True),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("login_count", sa.BigInteger, nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("tenant_id", "user_id", "device_fingerprint", name="uq_user_devices_fingerprint"),
    )
    op.create_index("ix_user_devices_tenant_user", "user_devices", ["tenant_id", "user_id"],
                    postgresql_where=sa.text("deleted_at IS NULL"))

    # FK from sessions → devices (deferred to avoid circular)
    op.create_foreign_key(
        "fk_user_sessions_device_id", "user_sessions", "user_devices",
        ["device_id"], ["id"], ondelete="SET NULL",
    )

    # ── password_reset_tokens ─────────────────────────────────────────────────
    op.create_table(
        "password_reset_tokens",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", UUID(as_uuid=True), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("token_hash", sa.String(255), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ip_requested", INET, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_password_reset_token_hash", "password_reset_tokens", ["token_hash"])
    op.create_index("ix_password_reset_user", "password_reset_tokens", ["user_id", "expires_at"])

    # ── email_verification_tokens ─────────────────────────────────────────────
    op.create_table(
        "email_verification_tokens",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", UUID(as_uuid=True), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("email", sa.String(320), nullable=False),
        sa.Column("token_hash", sa.String(255), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_email_verify_token_hash", "email_verification_tokens", ["token_hash"])
    op.create_index("ix_email_verify_user", "email_verification_tokens", ["user_id"])

    # ── oauth_accounts ────────────────────────────────────────────────────────
    op.create_table(
        "oauth_accounts",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", UUID(as_uuid=True), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("provider", sa.String(32), nullable=False),
        sa.Column("provider_user_id", sa.String(255), nullable=False),
        sa.Column("provider_email", sa.String(320), nullable=True),
        sa.Column("access_token_enc", sa.Text, nullable=True),
        sa.Column("refresh_token_enc", sa.Text, nullable=True),
        sa.Column("token_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("raw_profile", JSONB, nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("provider", "provider_user_id", name="uq_oauth_accounts_provider_uid"),
    )
    op.create_index("ix_oauth_accounts_user", "oauth_accounts", ["user_id"])

    # ── mfa_backup_codes ──────────────────────────────────────────────────────
    op.create_table(
        "mfa_backup_codes",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", UUID(as_uuid=True), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("code_hash", sa.String(255), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_mfa_backup_codes_user", "mfa_backup_codes", ["user_id"],
                    postgresql_where=sa.text("used_at IS NULL"))

    # ── Row-level security for all auth tables ────────────────────────────────
    for table in [
        "user_sessions", "user_devices", "password_reset_tokens",
        "email_verification_tokens", "oauth_accounts", "mfa_backup_codes",
    ]:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"""
            CREATE POLICY tenant_isolation ON {table}
            USING (tenant_id = current_setting('app.tenant_id', true)::uuid)
        """)

    # ── updated_at trigger (reuse from sg_db) ─────────────────────────────────
    for table in ["user_sessions", "user_devices", "oauth_accounts"]:
        op.execute(f"""
            CREATE TRIGGER trg_{table}_updated_at
            BEFORE UPDATE ON {table}
            FOR EACH ROW EXECUTE FUNCTION update_updated_at_column()
        """)


def downgrade() -> None:
    for table in [
        "mfa_backup_codes", "oauth_accounts", "email_verification_tokens",
        "password_reset_tokens", "user_devices", "user_sessions",
    ]:
        op.drop_table(table)
