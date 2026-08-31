-- 001_init.sql — backtesting_engine_service schema (sg_db, bt_ prefixed tables)

CREATE TABLE IF NOT EXISTS bt_runs (
    id              UUID PRIMARY KEY,
    mode            TEXT NOT NULL,
    status          TEXT NOT NULL,
    config          JSONB NOT NULL,
    walk_forward_config JSONB,
    monte_carlo_config   JSONB,
    progress_pct    DOUBLE PRECISION NOT NULL DEFAULT 0,
    error           TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    started_at      TIMESTAMPTZ,
    completed_at    TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_bt_runs_status ON bt_runs (status);
CREATE INDEX IF NOT EXISTS idx_bt_runs_created_at ON bt_runs (created_at DESC);

CREATE TABLE IF NOT EXISTS bt_trades (
    id              UUID PRIMARY KEY,
    run_id          UUID NOT NULL REFERENCES bt_runs(id) ON DELETE CASCADE,
    symbol          TEXT NOT NULL,
    action          TEXT NOT NULL,
    entry_ts        TIMESTAMPTZ NOT NULL,
    entry_price_inr DOUBLE PRECISION NOT NULL,
    exit_ts         TIMESTAMPTZ,
    exit_price_inr  DOUBLE PRECISION,
    quantity        DOUBLE PRECISION NOT NULL,
    commission_inr  DOUBLE PRECISION NOT NULL DEFAULT 0,
    slippage_inr    DOUBLE PRECISION NOT NULL DEFAULT 0,
    realized_pnl_inr DOUBLE PRECISION,
    realized_pnl_pct DOUBLE PRECISION,
    holding_period_bars INTEGER,
    exit_reason     TEXT
);

CREATE INDEX IF NOT EXISTS idx_bt_trades_run_id ON bt_trades (run_id);
CREATE INDEX IF NOT EXISTS idx_bt_trades_symbol ON bt_trades (run_id, symbol);

CREATE TABLE IF NOT EXISTS bt_equity_curve (
    run_id          UUID NOT NULL REFERENCES bt_runs(id) ON DELETE CASCADE,
    ts              TIMESTAMPTZ NOT NULL,
    equity_inr      DOUBLE PRECISION NOT NULL,
    cash_inr        DOUBLE PRECISION NOT NULL,
    drawdown_pct    DOUBLE PRECISION NOT NULL,
    benchmark_equity_inr DOUBLE PRECISION,
    PRIMARY KEY (run_id, ts)
);

CREATE TABLE IF NOT EXISTS bt_performance (
    run_id          UUID PRIMARY KEY REFERENCES bt_runs(id) ON DELETE CASCADE,
    metrics         JSONB NOT NULL,
    computed_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS bt_walk_forward_windows (
    id              UUID PRIMARY KEY,
    run_id          UUID NOT NULL REFERENCES bt_runs(id) ON DELETE CASCADE,
    window_index    INTEGER NOT NULL,
    train_start     DATE NOT NULL,
    train_end       DATE NOT NULL,
    test_start      DATE NOT NULL,
    test_end        DATE NOT NULL,
    in_sample_metrics  JSONB NOT NULL,
    out_sample_metrics JSONB NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_bt_wf_run_id ON bt_walk_forward_windows (run_id, window_index);

CREATE TABLE IF NOT EXISTS bt_walk_forward_summary (
    run_id          UUID PRIMARY KEY REFERENCES bt_runs(id) ON DELETE CASCADE,
    aggregate_out_sample_metrics JSONB NOT NULL,
    consistency_score_pct DOUBLE PRECISION NOT NULL
);

CREATE TABLE IF NOT EXISTS bt_monte_carlo_results (
    run_id          UUID PRIMARY KEY REFERENCES bt_runs(id) ON DELETE CASCADE,
    iterations      INTEGER NOT NULL,
    method          TEXT NOT NULL,
    percentiles     JSONB NOT NULL,
    probability_of_loss_pct DOUBLE PRECISION NOT NULL,
    probability_of_ruin_pct DOUBLE PRECISION NOT NULL,
    original_metrics JSONB NOT NULL,
    median_metrics   JSONB NOT NULL
);

CREATE TABLE IF NOT EXISTS bt_ohlcv_cache (
    symbol          TEXT NOT NULL,
    timeframe       TEXT NOT NULL,
    ts              TIMESTAMPTZ NOT NULL,
    open            DOUBLE PRECISION NOT NULL,
    high            DOUBLE PRECISION NOT NULL,
    low             DOUBLE PRECISION NOT NULL,
    close           DOUBLE PRECISION NOT NULL,
    volume          DOUBLE PRECISION NOT NULL DEFAULT 0,
    PRIMARY KEY (symbol, timeframe, ts)
);

COMMENT ON TABLE bt_ohlcv_cache IS
    'Local fallback store for historical OHLCV when market_data_service REST is unavailable.';
