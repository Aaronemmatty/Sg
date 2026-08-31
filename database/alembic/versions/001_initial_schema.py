"""Initial production schema for SG trading platform.

Revision ID: 001
Revises:
Create Date: 2026-06-07

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from sg_db.partitions import create_all_partitions

revision: str = "001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Reusable column types
UUID = postgresql.UUID(as_uuid=True)
JSONB = postgresql.JSONB(astext_type=sa.Text())
INET = postgresql.INET()
MONEY = sa.Numeric(18, 8)
PRICE = sa.Numeric(18, 8)
QUANTITY = sa.Numeric(18, 8)
TS = sa.DateTime(timezone=True)


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")
    op.execute("CREATE EXTENSION IF NOT EXISTS btree_gin")

    # ── Tenants ──────────────────────────────────────────────────────────────
    op.create_table(
        "tenants",
        sa.Column("id", UUID, server_default=sa.text("gen_random_uuid()"), primary_key=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("slug", sa.String(64), nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="active"),
        sa.Column("settings", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("billing_email", sa.String(320), nullable=True),
        sa.Column("created_at", TS, server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", TS, server_default=sa.text("now()"), nullable=False),
        sa.Column("deleted_at", TS, nullable=True),
        sa.UniqueConstraint("slug", name="uq_tenants_slug"),
    )

    # ── Identity ─────────────────────────────────────────────────────────────
    op.create_table(
        "users",
        sa.Column("id", UUID, server_default=sa.text("gen_random_uuid()"), primary_key=True),
        sa.Column("tenant_id", UUID, sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("email", sa.String(320), nullable=False),
        sa.Column("password_hash", sa.String(255), nullable=False),
        sa.Column("display_name", sa.String(255), nullable=False),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.text("true")),
        sa.Column("mfa_enabled", sa.Boolean, nullable=False, server_default=sa.text("false")),
        sa.Column("mfa_secret", sa.String(255), nullable=True),
        sa.Column("last_login_at", TS, nullable=True),
        sa.Column("preferences", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", TS, server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", TS, server_default=sa.text("now()"), nullable=False),
        sa.Column("deleted_at", TS, nullable=True),
        sa.UniqueConstraint("tenant_id", "email", name="uq_users_tenant_email"),
    )
    op.create_index("ix_users_tenant_id", "users", ["tenant_id"])
    op.create_index(
        "ix_users_tenant_active", "users", ["tenant_id"], postgresql_where=sa.text("deleted_at IS NULL")
    )

    op.create_table(
        "roles",
        sa.Column("id", UUID, server_default=sa.text("gen_random_uuid()"), primary_key=True),
        sa.Column("tenant_id", UUID, sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("is_system", sa.Boolean, nullable=False, server_default=sa.text("false")),
        sa.Column("created_at", TS, server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", TS, server_default=sa.text("now()"), nullable=False),
        sa.Column("deleted_at", TS, nullable=True),
        sa.UniqueConstraint("tenant_id", "name", name="uq_roles_tenant_name"),
    )
    op.create_index("ix_roles_tenant_id", "roles", ["tenant_id"])

    op.create_table(
        "permissions",
        sa.Column("id", UUID, server_default=sa.text("gen_random_uuid()"), primary_key=True),
        sa.Column("resource", sa.String(64), nullable=False),
        sa.Column("action", sa.String(64), nullable=False),
        sa.Column("scope", sa.String(64), nullable=True),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("created_at", TS, server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", TS, server_default=sa.text("now()"), nullable=False),
        sa.UniqueConstraint("resource", "action", "scope", name="uq_permissions_resource_action_scope"),
    )

    op.create_table(
        "user_roles",
        sa.Column("tenant_id", UUID, sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", UUID, sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("role_id", UUID, sa.ForeignKey("roles.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("granted_by", UUID, nullable=True),
        sa.Column("granted_at", TS, server_default=sa.text("now()"), nullable=False),
        sa.Column("created_at", TS, server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", TS, server_default=sa.text("now()"), nullable=False),
        sa.UniqueConstraint("tenant_id", "user_id", "role_id", name="uq_user_roles_tenant_user_role"),
    )

    op.create_table(
        "role_permissions",
        sa.Column("role_id", UUID, sa.ForeignKey("roles.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("permission_id", UUID, sa.ForeignKey("permissions.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("created_at", TS, server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", TS, server_default=sa.text("now()"), nullable=False),
    )

    op.create_table(
        "api_keys",
        sa.Column("id", UUID, server_default=sa.text("gen_random_uuid()"), primary_key=True),
        sa.Column("tenant_id", UUID, sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", UUID, sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("key_prefix", sa.String(16), nullable=False),
        sa.Column("key_hash", sa.String(255), nullable=False),
        sa.Column("scopes", JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("allowed_ips", JSONB, nullable=True),
        sa.Column("expires_at", TS, nullable=True),
        sa.Column("last_used_at", TS, nullable=True),
        sa.Column("last_used_ip", INET, nullable=True),
        sa.Column("revoked_at", TS, nullable=True),
        sa.Column("created_at", TS, server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", TS, server_default=sa.text("now()"), nullable=False),
        sa.Column("deleted_at", TS, nullable=True),
        sa.UniqueConstraint("tenant_id", "key_prefix", name="uq_api_keys_tenant_prefix"),
    )
    op.create_index("ix_api_keys_tenant_id", "api_keys", ["tenant_id"])
    op.create_index("ix_api_keys_hash", "api_keys", ["key_hash"])

    # ── Portfolios & Strategies ──────────────────────────────────────────────
    op.create_table(
        "portfolios",
        sa.Column("id", UUID, server_default=sa.text("gen_random_uuid()"), primary_key=True),
        sa.Column("tenant_id", UUID, sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("base_currency", sa.String(3), nullable=False, server_default="USD"),
        sa.Column("mode", sa.String(16), nullable=False, server_default="paper"),
        sa.Column("initial_capital", MONEY, nullable=False, server_default="0"),
        sa.Column("cash_balance", MONEY, nullable=False, server_default="0"),
        sa.Column("is_default", sa.Boolean, nullable=False, server_default=sa.text("false")),
        sa.Column("settings", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("owner_id", UUID, sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", TS, server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", TS, server_default=sa.text("now()"), nullable=False),
        sa.Column("deleted_at", TS, nullable=True),
        sa.UniqueConstraint("tenant_id", "name", name="uq_portfolios_tenant_name"),
    )
    op.create_index("ix_portfolios_tenant_id", "portfolios", ["tenant_id"])

    op.create_table(
        "strategies",
        sa.Column("id", UUID, server_default=sa.text("gen_random_uuid()"), primary_key=True),
        sa.Column("tenant_id", UUID, sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("version", sa.String(32), nullable=False, server_default="1.0.0"),
        sa.Column("strategy_type", sa.String(64), nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="draft"),
        sa.Column("config", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("parameters", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("supported_timeframes", JSONB, nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("created_by", UUID, sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", TS, server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", TS, server_default=sa.text("now()"), nullable=False),
        sa.Column("deleted_at", TS, nullable=True),
        sa.UniqueConstraint("tenant_id", "name", "version", name="uq_strategies_tenant_name_version"),
    )
    op.create_index("ix_strategies_tenant_id", "strategies", ["tenant_id"])
    op.create_index(
        "ix_strategies_tenant_status",
        "strategies",
        ["tenant_id", "status"],
        postgresql_where=sa.text("deleted_at IS NULL"),
    )

    # ── Positions (non-partitioned, current state) ─────────────────────────────
    op.create_table(
        "positions",
        sa.Column("id", UUID, server_default=sa.text("gen_random_uuid()"), primary_key=True),
        sa.Column("tenant_id", UUID, sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("portfolio_id", UUID, sa.ForeignKey("portfolios.id", ondelete="CASCADE"), nullable=False),
        sa.Column("symbol", sa.String(32), nullable=False),
        sa.Column("exchange", sa.String(32), nullable=False, server_default="SMART"),
        sa.Column("quantity", QUANTITY, nullable=False, server_default="0"),
        sa.Column("avg_cost", PRICE, nullable=False, server_default="0"),
        sa.Column("market_price", PRICE, nullable=True),
        sa.Column("market_value", MONEY, nullable=False, server_default="0"),
        sa.Column("unrealized_pnl", MONEY, nullable=False, server_default="0"),
        sa.Column("realized_pnl", MONEY, nullable=False, server_default="0"),
        sa.Column("mode", sa.String(16), nullable=False),
        sa.Column("last_trade_at", TS, nullable=True),
        sa.Column("version", sa.Integer, nullable=False, server_default="1"),
        sa.Column("created_at", TS, server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", TS, server_default=sa.text("now()"), nullable=False),
        sa.UniqueConstraint("tenant_id", "portfolio_id", "symbol", name="uq_positions_tenant_portfolio_symbol"),
    )
    op.create_index("ix_positions_tenant_portfolio", "positions", ["tenant_id", "portfolio_id"])

    # ── ML Model Registry ────────────────────────────────────────────────────
    op.create_table(
        "ml_models",
        sa.Column("id", UUID, server_default=sa.text("gen_random_uuid()"), primary_key=True),
        sa.Column("tenant_id", UUID, sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("version", sa.String(32), nullable=False),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("framework", sa.String(64), nullable=False),
        sa.Column("artifact_uri", sa.String(512), nullable=False),
        sa.Column("feature_schema", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("hyperparameters", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("metrics", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("status", sa.String(32), nullable=False, server_default="training"),
        sa.Column("deployed_at", TS, nullable=True),
        sa.Column("created_by", UUID, sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", TS, server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", TS, server_default=sa.text("now()"), nullable=False),
        sa.Column("deleted_at", TS, nullable=True),
        sa.UniqueConstraint("tenant_id", "name", "version", name="uq_ml_models_tenant_name_version"),
    )
    op.create_index("ix_ml_models_tenant_id", "ml_models", ["tenant_id"])

    # ── Notifications ────────────────────────────────────────────────────────
    op.create_table(
        "notifications",
        sa.Column("id", UUID, server_default=sa.text("gen_random_uuid()"), primary_key=True),
        sa.Column("tenant_id", UUID, sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", UUID, sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("channel", sa.String(32), nullable=False),
        sa.Column("notification_type", sa.String(64), nullable=False),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("body", sa.Text, nullable=False),
        sa.Column("payload", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("status", sa.String(32), nullable=False, server_default="pending"),
        sa.Column("read_at", TS, nullable=True),
        sa.Column("sent_at", TS, nullable=True),
        sa.Column("resource_type", sa.String(64), nullable=True),
        sa.Column("resource_id", sa.String(64), nullable=True),
        sa.Column("correlation_id", sa.String(64), nullable=True),
        sa.Column("created_at", TS, server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", TS, server_default=sa.text("now()"), nullable=False),
        sa.Column("deleted_at", TS, nullable=True),
    )
    op.create_index("ix_notifications_tenant_user_status", "notifications", ["tenant_id", "user_id", "status"])
    op.create_index(
        "ix_notifications_tenant_unread",
        "notifications",
        ["tenant_id", "user_id"],
        postgresql_where=sa.text("read_at IS NULL"),
    )

    # ── Partitioned parent tables (raw SQL for PG17 RANGE partitioning) ──────
    op.execute("""
        CREATE TABLE orders (
            id UUID NOT NULL DEFAULT gen_random_uuid(),
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            deleted_at TIMESTAMPTZ,
            tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
            portfolio_id UUID NOT NULL,
            strategy_id UUID REFERENCES strategies(id) ON DELETE SET NULL,
            symbol VARCHAR(32) NOT NULL,
            exchange VARCHAR(32) NOT NULL DEFAULT 'SMART',
            side VARCHAR(8) NOT NULL,
            order_type VARCHAR(16) NOT NULL,
            quantity NUMERIC(18,8) NOT NULL,
            filled_quantity NUMERIC(18,8) NOT NULL DEFAULT 0,
            limit_price NUMERIC(18,8),
            stop_price NUMERIC(18,8),
            avg_fill_price NUMERIC(18,8),
            status VARCHAR(32) NOT NULL DEFAULT 'pending',
            mode VARCHAR(16) NOT NULL DEFAULT 'paper',
            idempotency_key VARCHAR(64) NOT NULL,
            correlation_id VARCHAR(64) NOT NULL,
            broker_order_id VARCHAR(128),
            reject_reason TEXT,
            metadata JSONB NOT NULL DEFAULT '{}',
            submitted_at TIMESTAMPTZ,
            filled_at TIMESTAMPTZ,
            cancelled_at TIMESTAMPTZ,
            PRIMARY KEY (id, created_at),
            UNIQUE (tenant_id, idempotency_key, created_at)
        ) PARTITION BY RANGE (created_at);
    """)

    op.execute("""
        CREATE TABLE trades (
            id UUID NOT NULL DEFAULT gen_random_uuid(),
            executed_at TIMESTAMPTZ NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
            order_id UUID NOT NULL,
            order_created_at TIMESTAMPTZ NOT NULL,
            portfolio_id UUID NOT NULL,
            strategy_id UUID REFERENCES strategies(id) ON DELETE SET NULL,
            symbol VARCHAR(32) NOT NULL,
            side VARCHAR(8) NOT NULL,
            quantity NUMERIC(18,8) NOT NULL,
            price NUMERIC(18,8) NOT NULL,
            commission NUMERIC(18,8) NOT NULL DEFAULT 0,
            fees NUMERIC(18,8) NOT NULL DEFAULT 0,
            mode VARCHAR(16) NOT NULL,
            broker_trade_id VARCHAR(128) NOT NULL,
            correlation_id VARCHAR(64) NOT NULL,
            PRIMARY KEY (id, executed_at),
            UNIQUE (tenant_id, broker_trade_id, executed_at)
        ) PARTITION BY RANGE (executed_at);
    """)

    op.execute("""
        CREATE TABLE portfolio_snapshots (
            id UUID NOT NULL DEFAULT gen_random_uuid(),
            snapshot_at TIMESTAMPTZ NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
            portfolio_id UUID NOT NULL REFERENCES portfolios(id) ON DELETE CASCADE,
            total_value NUMERIC(18,8) NOT NULL,
            cash NUMERIC(18,8) NOT NULL,
            equity NUMERIC(18,8) NOT NULL,
            day_pnl NUMERIC(18,8) NOT NULL DEFAULT 0,
            total_pnl NUMERIC(18,8) NOT NULL DEFAULT 0,
            positions JSONB NOT NULL DEFAULT '[]',
            metrics JSONB NOT NULL DEFAULT '{}',
            PRIMARY KEY (id, snapshot_at)
        ) PARTITION BY RANGE (snapshot_at);
    """)

    op.execute("""
        CREATE TABLE market_bars (
            id UUID NOT NULL DEFAULT gen_random_uuid(),
            bar_ts TIMESTAMPTZ NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            symbol VARCHAR(32) NOT NULL,
            exchange VARCHAR(32) NOT NULL,
            timeframe VARCHAR(8) NOT NULL,
            open NUMERIC(18,8) NOT NULL,
            high NUMERIC(18,8) NOT NULL,
            low NUMERIC(18,8) NOT NULL,
            close NUMERIC(18,8) NOT NULL,
            volume NUMERIC(18,8) NOT NULL DEFAULT 0,
            vwap NUMERIC(18,8),
            trade_count BIGINT,
            source VARCHAR(64) NOT NULL DEFAULT 'internal',
            PRIMARY KEY (id, bar_ts),
            UNIQUE (symbol, exchange, timeframe, bar_ts)
        ) PARTITION BY RANGE (bar_ts);
    """)

    op.execute("""
        CREATE TABLE signals (
            id UUID NOT NULL DEFAULT gen_random_uuid(),
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
            strategy_id UUID NOT NULL REFERENCES strategies(id) ON DELETE CASCADE,
            strategy_instance_id VARCHAR(64) NOT NULL,
            portfolio_id UUID,
            symbol VARCHAR(32) NOT NULL,
            signal_type VARCHAR(16) NOT NULL,
            side VARCHAR(8) NOT NULL,
            quantity NUMERIC(18,8),
            limit_price NUMERIC(18,8),
            strength NUMERIC,
            timeframe VARCHAR(8) NOT NULL,
            bar_ts TIMESTAMPTZ NOT NULL,
            mode VARCHAR(16) NOT NULL DEFAULT 'paper',
            reason TEXT,
            correlation_id VARCHAR(64) NOT NULL,
            metadata JSONB NOT NULL DEFAULT '{}',
            PRIMARY KEY (id, created_at)
        ) PARTITION BY RANGE (created_at);
    """)

    op.execute("""
        CREATE TABLE risk_events (
            id UUID NOT NULL DEFAULT gen_random_uuid(),
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
            portfolio_id UUID NOT NULL,
            event_type VARCHAR(32) NOT NULL,
            severity VARCHAR(16) NOT NULL,
            order_id UUID,
            order_created_at TIMESTAMPTZ,
            strategy_id UUID REFERENCES strategies(id) ON DELETE SET NULL,
            message TEXT NOT NULL,
            details JSONB NOT NULL DEFAULT '{}',
            correlation_id VARCHAR(64) NOT NULL,
            resolved_at TIMESTAMPTZ,
            resolved_by UUID REFERENCES users(id) ON DELETE SET NULL,
            resolution_note TEXT,
            PRIMARY KEY (id, created_at)
        ) PARTITION BY RANGE (created_at);
    """)

    op.execute("""
        CREATE TABLE ml_predictions (
            id UUID NOT NULL DEFAULT gen_random_uuid(),
            predicted_at TIMESTAMPTZ NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
            model_id UUID NOT NULL REFERENCES ml_models(id) ON DELETE CASCADE,
            strategy_id UUID REFERENCES strategies(id) ON DELETE SET NULL,
            symbol VARCHAR(32) NOT NULL,
            horizon VARCHAR(32) NOT NULL,
            prediction JSONB NOT NULL,
            confidence NUMERIC,
            features_hash VARCHAR(64),
            correlation_id VARCHAR(64) NOT NULL,
            latency_ms INTEGER,
            PRIMARY KEY (id, predicted_at)
        ) PARTITION BY RANGE (predicted_at);
    """)

    op.execute("""
        CREATE TABLE audit_logs (
            id UUID NOT NULL DEFAULT gen_random_uuid(),
            created_at TIMESTAMPTZ NOT NULL,
            tenant_id UUID NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
            actor_id UUID,
            actor_type VARCHAR(16) NOT NULL,
            action VARCHAR(64) NOT NULL,
            resource_type VARCHAR(64) NOT NULL,
            resource_id VARCHAR(64) NOT NULL,
            old_values JSONB,
            new_values JSONB,
            ip_address INET,
            user_agent TEXT,
            correlation_id VARCHAR(64) NOT NULL,
            PRIMARY KEY (id, created_at)
        ) PARTITION BY RANGE (created_at);
    """)

    op.execute("""
        CREATE TABLE system_events (
            id UUID NOT NULL DEFAULT gen_random_uuid(),
            created_at TIMESTAMPTZ NOT NULL,
            tenant_id UUID,
            event_type VARCHAR(64) NOT NULL,
            source_service VARCHAR(64) NOT NULL,
            severity VARCHAR(16) NOT NULL,
            message TEXT NOT NULL,
            payload JSONB NOT NULL DEFAULT '{}',
            correlation_id VARCHAR(64) NOT NULL,
            PRIMARY KEY (id, created_at)
        ) PARTITION BY RANGE (created_at);
    """)

    # ── Monthly partitions (24 months from 2026-01) ──────────────────────────
    create_all_partitions(start_year=2026, months=24)

    # ── Partitioned table indexes ────────────────────────────────────────────
    op.create_index("ix_orders_tenant_id", "orders", ["tenant_id"])
    op.create_index("ix_orders_tenant_portfolio_status", "orders", ["tenant_id", "portfolio_id", "status"])
    op.create_index("ix_orders_tenant_symbol_created", "orders", ["tenant_id", "symbol", "created_at"])
    op.create_index("ix_orders_correlation", "orders", ["correlation_id"])
    op.create_index(
        "ix_orders_active", "orders", ["tenant_id", "status"], postgresql_where=sa.text("deleted_at IS NULL")
    )

    op.create_index("ix_trades_tenant_order", "trades", ["tenant_id", "order_id", "order_created_at"])
    op.create_index("ix_trades_tenant_symbol_executed", "trades", ["tenant_id", "symbol", "executed_at"])
    op.create_index("ix_trades_portfolio_executed", "trades", ["tenant_id", "portfolio_id", "executed_at"])

    op.create_index(
        "ix_portfolio_snapshots_tenant_portfolio_ts",
        "portfolio_snapshots",
        ["tenant_id", "portfolio_id", "snapshot_at"],
    )
    op.create_index("ix_market_bars_symbol_tf_ts", "market_bars", ["symbol", "timeframe", "bar_ts"])
    op.create_index("ix_signals_tenant_strategy_created", "signals", ["tenant_id", "strategy_id", "created_at"])
    op.create_index("ix_risk_events_tenant_portfolio_created", "risk_events", ["tenant_id", "portfolio_id", "created_at"])
    op.create_index("ix_ml_predictions_tenant_model_predicted", "ml_predictions", ["tenant_id", "model_id", "predicted_at"])
    op.create_index("ix_audit_logs_tenant_created", "audit_logs", ["tenant_id", "created_at"])
    op.create_index("ix_system_events_tenant_created", "system_events", ["tenant_id", "created_at"])

    # ── Row-Level Security (multi-tenant isolation) ──────────────────────────
    for table in (
        "users", "roles", "api_keys", "portfolios", "strategies", "positions",
        "orders", "trades", "portfolio_snapshots", "signals", "risk_events",
        "ml_models", "ml_predictions", "audit_logs", "notifications",
    ):
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"""
            CREATE POLICY tenant_isolation_{table} ON {table}
            USING (tenant_id = current_setting('app.tenant_id', true)::uuid)
            WITH CHECK (tenant_id = current_setting('app.tenant_id', true)::uuid);
        """)

    # ── Seed canonical permissions ─────────────────────────────────────────────
    op.execute("""
        INSERT INTO permissions (resource, action, scope, description) VALUES
            ('orders', 'create', 'paper', 'Create paper trading orders'),
            ('orders', 'create', 'live', 'Create live trading orders'),
            ('orders', 'read', NULL, 'View orders'),
            ('orders', 'cancel', NULL, 'Cancel open orders'),
            ('strategies', 'create', NULL, 'Register strategies'),
            ('strategies', 'deploy', NULL, 'Deploy strategies to live'),
            ('portfolios', 'read', NULL, 'View portfolios'),
            ('portfolios', 'manage', NULL, 'Manage portfolio settings'),
            ('risk', 'read', NULL, 'View risk limits and events'),
            ('risk', 'manage', NULL, 'Configure risk limits'),
            ('risk', 'kill_switch', NULL, 'Activate kill switch'),
            ('ml_models', 'read', NULL, 'View model registry'),
            ('ml_models', 'deploy', NULL, 'Promote models to production'),
            ('api_keys', 'manage', NULL, 'Manage API keys'),
            ('audit_logs', 'read', NULL, 'View audit trail'),
            ('backtests', 'run', NULL, 'Execute backtests');
    """)


def downgrade() -> None:
    tables = [
        "system_events", "audit_logs", "ml_predictions", "risk_events", "signals",
        "market_bars", "portfolio_snapshots", "trades", "orders",
        "notifications", "ml_models", "positions", "strategies", "portfolios",
        "api_keys", "role_permissions", "user_roles", "permissions", "roles", "users", "tenants",
    ]
    for table in tables:
        op.execute(f"DROP TABLE IF EXISTS {table} CASCADE")
    op.execute("DROP EXTENSION IF EXISTS btree_gin")
    op.execute("DROP EXTENSION IF EXISTS pgcrypto")
