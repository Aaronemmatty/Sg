"""Initial migration — trade_intents and orchestrator_audit_logs.

Revision ID: 0001
Revises: —
Create Date: 2025-01-01 00:00:00
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "trade_intents",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("intent_id", sa.String(64), nullable=False),
        sa.Column("correlation_id", sa.String(64), nullable=False),
        sa.Column("symbol", sa.String(32), nullable=False),
        sa.Column("timeframe", sa.String(16), nullable=True),
        sa.Column("action", sa.String(8), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("rejection_reasons", postgresql.ARRAY(sa.String()), nullable=True),
        sa.Column("rejection_detail", sa.Text(), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("net_score", sa.Float(), nullable=True),
        sa.Column("agreement_ratio", sa.Float(), nullable=True),
        sa.Column("contributors", postgresql.ARRAY(sa.String()), nullable=True),
        sa.Column("allocation_inr", sa.Float(), nullable=False),
        sa.Column("risk_percent", sa.Float(), nullable=False),
        sa.Column("market_regime", sa.String(32), nullable=False),
        sa.Column("portfolio_id", sa.String(64), nullable=True),
        sa.Column("snapshot_portfolio_value_inr", sa.Float(), nullable=True),
        sa.Column("snapshot_daily_loss_inr", sa.Float(), nullable=True),
        sa.Column("snapshot_drawdown_pct", sa.Float(), nullable=True),
        sa.Column("snapshot_open_intents", sa.Integer(), nullable=True),
        sa.Column("meta", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column(
            "signal_timestamp",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("intent_id", name="uq_trade_intents_intent_id"),
    )
    op.create_index("ix_trade_intents_intent_id", "trade_intents", ["intent_id"])
    op.create_index("ix_trade_intents_correlation_id", "trade_intents", ["correlation_id"])
    op.create_index("ix_trade_intents_symbol", "trade_intents", ["symbol"])
    op.create_index("ix_trade_intents_status", "trade_intents", ["status"])
    op.create_index("ix_trade_intents_portfolio_id", "trade_intents", ["portfolio_id"])
    op.create_index(
        "ix_trade_intents_symbol_created", "trade_intents", ["symbol", "created_at"]
    )
    op.create_index(
        "ix_trade_intents_status_created", "trade_intents", ["status", "created_at"]
    )
    op.create_index(
        "ix_trade_intents_portfolio_status",
        "trade_intents",
        ["portfolio_id", "status"],
    )

    op.create_table(
        "orchestrator_audit_logs",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("intent_id", sa.String(64), nullable=False),
        sa.Column("symbol", sa.String(32), nullable=False),
        sa.Column("check_name", sa.String(64), nullable=False),
        sa.Column("passed", sa.Boolean(), nullable=False),
        sa.Column("reason", sa.String(64), nullable=True),
        sa.Column("detail", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_audit_intent_id", "orchestrator_audit_logs", ["intent_id"])
    op.create_index(
        "ix_audit_symbol_created",
        "orchestrator_audit_logs",
        ["symbol", "created_at"],
    )


def downgrade() -> None:
    op.drop_table("orchestrator_audit_logs")
    op.drop_table("trade_intents")
