-- portfolio_management_service (8009) — initial schema
-- Database: sg_db (shared with other services, separate pm_ namespace)
-- All tables use pm_ prefix to avoid collision with existing service tables.

-- ── Portfolio configuration (single-row state) ────────────────────────────

CREATE TABLE IF NOT EXISTS pm_portfolio_config (
    config_id               INTEGER PRIMARY KEY DEFAULT 1,  -- always row 1
    initial_capital_inr     NUMERIC(20, 2) NOT NULL DEFAULT 0,
    cash_balance_inr        NUMERIC(20, 2) NOT NULL DEFAULT 0,
    day_open_value_inr      NUMERIC(20, 2),                  -- NAV at market open
    updated_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT single_row CHECK (config_id = 1)
);

-- Seed default row (upserted by service on first startup via repository)
INSERT INTO pm_portfolio_config (config_id, initial_capital_inr, cash_balance_inr)
VALUES (1, 0, 0)
ON CONFLICT (config_id) DO NOTHING;

-- ── Net positions (one row per symbol) ────────────────────────────────────

CREATE TABLE IF NOT EXISTS pm_positions (
    symbol              TEXT PRIMARY KEY,
    net_quantity        INTEGER NOT NULL DEFAULT 0,
    avg_cost_inr        NUMERIC(16, 4) NOT NULL DEFAULT 0,
    market_price_inr    NUMERIC(16, 4),
    market_value_inr    NUMERIC(20, 2) NOT NULL DEFAULT 0,
    unrealized_pnl_inr  NUMERIC(20, 2) NOT NULL DEFAULT 0,
    realized_pnl_inr    NUMERIC(20, 2) NOT NULL DEFAULT 0,
    total_pnl_inr       NUMERIC(20, 2) NOT NULL DEFAULT 0,
    day_pnl_inr         NUMERIC(20, 2) NOT NULL DEFAULT 0,
    last_trade_at       TIMESTAMPTZ,
    last_mtm_at         TIMESTAMPTZ,
    version             INTEGER NOT NULL DEFAULT 1,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS ix_pm_positions_net_qty
    ON pm_positions (net_quantity)
    WHERE net_quantity != 0;

-- ── FIFO lot ledger (one row per buy fill) ─────────────────────────────────

CREATE TABLE IF NOT EXISTS pm_lots (
    lot_id              UUID PRIMARY KEY,
    symbol              TEXT NOT NULL,
    order_id            UUID NOT NULL,
    execution_event_id  UUID NOT NULL,
    original_quantity   INTEGER NOT NULL CHECK (original_quantity > 0),
    remaining_quantity  INTEGER NOT NULL CHECK (remaining_quantity >= 0),
    cost_price_inr      NUMERIC(16, 4) NOT NULL,
    status              TEXT NOT NULL DEFAULT 'OPEN'
                            CHECK (status IN ('OPEN', 'PARTIALLY_CLOSED', 'CLOSED')),
    opened_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
    closed_at           TIMESTAMPTZ,
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS ix_pm_lots_symbol_status
    ON pm_lots (symbol, status, opened_at)
    WHERE status IN ('OPEN', 'PARTIALLY_CLOSED');

CREATE INDEX IF NOT EXISTS ix_pm_lots_order_id
    ON pm_lots (order_id);

-- ── Lot consumptions (sell-side FIFO audit trail) ─────────────────────────

CREATE TABLE IF NOT EXISTS pm_lot_consumptions (
    consumption_id      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    lot_id              UUID NOT NULL REFERENCES pm_lots (lot_id) ON DELETE CASCADE,
    order_id            UUID NOT NULL,
    execution_event_id  UUID NOT NULL,
    symbol              TEXT NOT NULL,
    qty_consumed        INTEGER NOT NULL CHECK (qty_consumed > 0),
    cost_price_inr      NUMERIC(16, 4) NOT NULL,
    sell_price_inr      NUMERIC(16, 4) NOT NULL,
    realized_pnl_inr    NUMERIC(20, 4) NOT NULL,   -- (sell - cost) * qty
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS ix_pm_lot_consumptions_lot_id
    ON pm_lot_consumptions (lot_id);

CREATE INDEX IF NOT EXISTS ix_pm_lot_consumptions_symbol_created
    ON pm_lot_consumptions (symbol, created_at);

CREATE INDEX IF NOT EXISTS ix_pm_lot_consumptions_order_id
    ON pm_lot_consumptions (order_id);

-- ── Immutable trade ledger (one row per fill event) ───────────────────────

CREATE TABLE IF NOT EXISTS pm_trade_ledger (
    event_id            UUID PRIMARY KEY,   -- order_id from ExecutionEvent (unique per fill)
    order_id            UUID NOT NULL,
    symbol              TEXT NOT NULL,
    action              TEXT NOT NULL CHECK (action IN ('BUY', 'SELL')),
    filled_quantity     INTEGER NOT NULL,
    avg_fill_price_inr  NUMERIC(16, 4) NOT NULL,
    slippage_bps        NUMERIC(10, 4),
    realized_pnl_inr    NUMERIC(20, 4),     -- populated on SELL after lot consumption
    emitted_at          TIMESTAMPTZ NOT NULL,
    recorded_at         TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS ix_pm_trade_ledger_symbol_emitted
    ON pm_trade_ledger (symbol, emitted_at DESC);

CREATE INDEX IF NOT EXISTS ix_pm_trade_ledger_order_id
    ON pm_trade_ledger (order_id);

CREATE INDEX IF NOT EXISTS ix_pm_trade_ledger_emitted
    ON pm_trade_ledger (emitted_at DESC);

-- ── Daily returns (NAV per day, for performance metric computation) ────────

CREATE TABLE IF NOT EXISTS pm_daily_returns (
    date                TEXT PRIMARY KEY,    -- 'YYYY-MM-DD'
    nav_inr             NUMERIC(20, 2) NOT NULL,
    daily_return_pct    NUMERIC(10, 6) NOT NULL,
    recorded_at         TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS ix_pm_daily_returns_date
    ON pm_daily_returns (date DESC);

-- ── Portfolio snapshots ────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS pm_snapshots (
    snapshot_id             UUID PRIMARY KEY,
    snapshot_at             TIMESTAMPTZ NOT NULL,
    initial_capital_inr     NUMERIC(20, 2) NOT NULL,
    cash_balance_inr        NUMERIC(20, 2) NOT NULL,
    equity_value_inr        NUMERIC(20, 2) NOT NULL,
    total_value_inr         NUMERIC(20, 2) NOT NULL,
    day_pnl_inr             NUMERIC(20, 2) NOT NULL DEFAULT 0,
    total_pnl_inr           NUMERIC(20, 2) NOT NULL DEFAULT 0,
    total_return_pct        NUMERIC(10, 4) NOT NULL DEFAULT 0,
    gross_exposure_inr      NUMERIC(20, 2) NOT NULL DEFAULT 0,
    net_exposure_inr        NUMERIC(20, 2) NOT NULL DEFAULT 0,
    gross_exposure_pct      NUMERIC(10, 4) NOT NULL DEFAULT 0,
    open_position_count     INTEGER NOT NULL DEFAULT 0,
    positions               JSONB NOT NULL DEFAULT '[]',
    performance_30d         JSONB,
    metrics                 JSONB NOT NULL DEFAULT '{}',
    created_at              TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS ix_pm_snapshots_snapshot_at
    ON pm_snapshots (snapshot_at DESC);

-- ── Event idempotency guard ────────────────────────────────────────────────
-- Prevents re-processing duplicate Redis delivery of the same ExecutionEvent.

CREATE TABLE IF NOT EXISTS pm_processed_events (
    event_id        UUID PRIMARY KEY,
    processed_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Auto-expire old idempotency records after 7 days to prevent unbounded growth.
-- A scheduled job or pg_cron task should periodically run:
--   DELETE FROM pm_processed_events WHERE processed_at < now() - INTERVAL '7 days';
CREATE INDEX IF NOT EXISTS ix_pm_processed_events_processed_at
    ON pm_processed_events (processed_at);
