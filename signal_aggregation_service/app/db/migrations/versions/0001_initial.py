"""create aggregated_signals and strategy_weight_overrides tables

Revision ID: 0001_initial
Revises:
Create Date: 2026-06-25

"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision: str = "0001_initial"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # aggregated_signals: partitioned by RANGE(timestamp), monthly, mirroring
    # regime_snapshots / signals.Signal / market_data.MarketBar.
    op.execute(
        """
        CREATE TABLE aggregated_signals (
            id UUID NOT NULL DEFAULT gen_random_uuid(),
            tenant_id UUID NOT NULL,
            symbol VARCHAR(32) NOT NULL,
            timeframe VARCHAR(8) NOT NULL,
            "timestamp" TIMESTAMPTZ NOT NULL,
            final_signal VARCHAR(8) NOT NULL,
            confidence DOUBLE PRECISION NOT NULL,
            contributors JSONB NOT NULL DEFAULT '[]'::jsonb,
            regime VARCHAR(32),
            net_score DOUBLE PRECISION,
            agreement_ratio DOUBLE PRECISION,
            votes JSONB NOT NULL DEFAULT '{}'::jsonb,
            weights_version VARCHAR(64),
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            deleted_at TIMESTAMPTZ,
            is_deleted BOOLEAN NOT NULL DEFAULT false,
            PRIMARY KEY (id, "timestamp"),
            CONSTRAINT uq_aggregated_signal UNIQUE (symbol, timeframe, "timestamp", tenant_id)
        ) PARTITION BY RANGE ("timestamp");
        """
    )
    op.execute(
        "CREATE INDEX ix_aggregated_signals_symbol_tf_ts ON aggregated_signals (symbol, timeframe, \"timestamp\");"
    )
    op.execute("ALTER TABLE aggregated_signals ENABLE ROW LEVEL SECURITY;")
    op.execute(
        """
        CREATE POLICY tenant_isolation_aggregated_signals ON aggregated_signals
        USING (tenant_id = current_setting('app.tenant_id')::uuid);
        """
    )

    op.execute(
        """
        DO $$
        DECLARE
            start_month date := date_trunc('month', now()) - interval '2 months';
            i int;
            part_start date;
            part_end date;
            part_name text;
        BEGIN
            FOR i IN 0..5 LOOP
                part_start := start_month + (i || ' months')::interval;
                part_end := start_month + ((i + 1) || ' months')::interval;
                part_name := format('aggregated_signals_%s', to_char(part_start, 'YYYY_MM'));
                EXECUTE format(
                    'CREATE TABLE IF NOT EXISTS %I PARTITION OF aggregated_signals FOR VALUES FROM (%L) TO (%L);',
                    part_name, part_start, part_end
                );
            END LOOP;
        END $$;
        """
    )

    # strategy_weight_overrides: low-volume config table, not partitioned.
    op.create_table(
        "strategy_weight_overrides",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=False, index=True),
        sa.Column("regime", sa.String(32), nullable=False),
        sa.Column("strategy", sa.String(64), nullable=False),
        sa.Column("weight", sa.Float, nullable=False),
        sa.Column("updated_by", sa.String(128), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("is_deleted", sa.Boolean, nullable=False, server_default=sa.text("false")),
        sa.UniqueConstraint("regime", "strategy", "tenant_id", name="uq_weight_override"),
    )
    op.create_index("ix_weight_overrides_regime", "strategy_weight_overrides", ["regime"])
    op.execute("ALTER TABLE strategy_weight_overrides ENABLE ROW LEVEL SECURITY;")
    op.execute(
        """
        CREATE POLICY tenant_isolation_weight_overrides ON strategy_weight_overrides
        USING (tenant_id = current_setting('app.tenant_id')::uuid);
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS strategy_weight_overrides CASCADE;")
    op.execute("DROP TABLE IF EXISTS aggregated_signals CASCADE;")
