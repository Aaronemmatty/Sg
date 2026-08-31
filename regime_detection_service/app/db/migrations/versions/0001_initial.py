"""create regime_snapshots and regime_transitions tables

Revision ID: 0001_initial
Revises:
Create Date: 2026-06-24

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
    # regime_snapshots: partitioned by RANGE(timestamp), monthly partitions, mirroring
    # the existing market_data.MarketBar / signals.Signal partitioning convention.
    op.execute(
        """
        CREATE TABLE regime_snapshots (
            id UUID NOT NULL DEFAULT gen_random_uuid(),
            tenant_id UUID NOT NULL,
            symbol VARCHAR(32) NOT NULL,
            exchange VARCHAR(16) NOT NULL DEFAULT 'NSE',
            timeframe VARCHAR(8) NOT NULL,
            "timestamp" TIMESTAMPTZ NOT NULL,
            regime VARCHAR(32) NOT NULL,
            confidence DOUBLE PRECISION NOT NULL,
            sub_regimes JSONB NOT NULL DEFAULT '[]'::jsonb,
            features JSONB NOT NULL DEFAULT '{}'::jsonb,
            model_version VARCHAR(64),
            is_override BOOLEAN NOT NULL DEFAULT false,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            deleted_at TIMESTAMPTZ,
            is_deleted BOOLEAN NOT NULL DEFAULT false,
            PRIMARY KEY (id, "timestamp"),
            CONSTRAINT uq_regime_snapshot UNIQUE (symbol, timeframe, "timestamp", tenant_id)
        ) PARTITION BY RANGE ("timestamp");
        """
    )
    op.execute(
        "CREATE INDEX ix_regime_snapshots_symbol_tf_ts ON regime_snapshots (symbol, timeframe, \"timestamp\");"
    )
    op.execute("ALTER TABLE regime_snapshots ENABLE ROW LEVEL SECURITY;")
    op.execute(
        """
        CREATE POLICY tenant_isolation_regime_snapshots ON regime_snapshots
        USING (tenant_id = current_setting('app.tenant_id')::uuid);
        """
    )

    # Bootstrap a rolling set of monthly partitions (current month +/- 2 either side).
    # Operationally this should be handled by a pg_partman / cron job long-term; this
    # migration just guarantees the service has somewhere to write on day one.
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
                part_name := format('regime_snapshots_%s', to_char(part_start, 'YYYY_MM'));
                EXECUTE format(
                    'CREATE TABLE IF NOT EXISTS %I PARTITION OF regime_snapshots FOR VALUES FROM (%L) TO (%L);',
                    part_name, part_start, part_end
                );
            END LOOP;
        END $$;
        """
    )

    # regime_transitions: low-volume audit trail, not partitioned.
    op.create_table(
        "regime_transitions",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=False, index=True),
        sa.Column("symbol", sa.String(32), nullable=False),
        sa.Column("timeframe", sa.String(8), nullable=False),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("from_regime", sa.String(32), nullable=True),
        sa.Column("to_regime", sa.String(32), nullable=False),
        sa.Column("confidence", sa.Float, nullable=False),
        sa.Column("trigger_reason", sa.String(64), nullable=False),
        sa.Column("snapshot_id", UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("is_deleted", sa.Boolean, nullable=False, server_default=sa.text("false")),
    )
    op.create_index(
        "ix_regime_transitions_symbol_tf_ts", "regime_transitions", ["symbol", "timeframe", "timestamp"]
    )
    op.execute("ALTER TABLE regime_transitions ENABLE ROW LEVEL SECURITY;")
    op.execute(
        """
        CREATE POLICY tenant_isolation_regime_transitions ON regime_transitions
        USING (tenant_id = current_setting('app.tenant_id')::uuid);
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS regime_transitions CASCADE;")
    op.execute("DROP TABLE IF EXISTS regime_snapshots CASCADE;")
