-- execution_engine_service (8008) — initial schema
-- Database: sg_db (shared with other services, separate tables/namespace)

CREATE TABLE IF NOT EXISTS exec_orders (
    order_id              UUID PRIMARY KEY,
    intent_id             UUID NOT NULL,
    correlation_id        UUID NOT NULL,
    symbol                TEXT NOT NULL,
    action                TEXT NOT NULL CHECK (action IN ('BUY', 'SELL')),
    state                 TEXT NOT NULL,

    approved_allocation_inr NUMERIC(16, 2) NOT NULL,
    quantity              INTEGER,
    order_type            TEXT,
    limit_price           NUMERIC(16, 4),
    validity              TEXT NOT NULL DEFAULT 'DAY',
    execution_style       TEXT NOT NULL,

    risk_band             TEXT NOT NULL,
    market_regime         TEXT,

    broker_order_id       TEXT,
    idempotency_key       TEXT NOT NULL,

    intended_price_inr    NUMERIC(16, 4),
    avg_fill_price_inr    NUMERIC(16, 4),
    filled_quantity       INTEGER NOT NULL DEFAULT 0,

    retry_count           INTEGER NOT NULL DEFAULT 0,
    last_error            TEXT,

    created_at            TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at            TIMESTAMPTZ NOT NULL DEFAULT now(),
    held_until            TIMESTAMPTZ
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_orders_idempotency_key ON exec_orders (idempotency_key);
CREATE INDEX IF NOT EXISTS ix_orders_intent_id ON exec_orders (intent_id);
CREATE INDEX IF NOT EXISTS ix_orders_symbol ON exec_orders (symbol);
CREATE INDEX IF NOT EXISTS ix_orders_state ON exec_orders (state);
CREATE INDEX IF NOT EXISTS ix_orders_broker_order_id ON exec_orders (broker_order_id);
CREATE INDEX IF NOT EXISTS ix_orders_state_updated_at ON exec_orders (state, updated_at);

CREATE TABLE IF NOT EXISTS executions (
    execution_id          UUID PRIMARY KEY,
    order_id              UUID NOT NULL REFERENCES exec_orders (order_id) ON DELETE CASCADE,
    broker_execution_id    TEXT,
    fill_quantity         INTEGER NOT NULL,
    fill_price_inr        NUMERIC(16, 4) NOT NULL,
    fill_timestamp         TIMESTAMPTZ NOT NULL DEFAULT now(),
    slippage_inr           NUMERIC(16, 4),
    slippage_bps           NUMERIC(10, 4)
);

CREATE INDEX IF NOT EXISTS ix_executions_order_id ON executions (order_id);

-- Full audit trail of every state transition / decision, consistent with
-- risk_decisions / risk_audit_logs pattern in risk_engine_service.
CREATE TABLE IF NOT EXISTS execution_audit_logs (
    audit_id              BIGSERIAL PRIMARY KEY,
    order_id              UUID NOT NULL,
    intent_id             UUID,
    from_state            TEXT,
    to_state              TEXT NOT NULL,
    actor                 TEXT NOT NULL DEFAULT 'system',   -- 'system' | username | 'risk_officer:<user>'
    reason                TEXT,
    detail                JSONB,
    created_at            TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS ix_execution_audit_logs_order_id ON execution_audit_logs (order_id);
CREATE INDEX IF NOT EXISTS ix_execution_audit_logs_created_at ON execution_audit_logs (created_at);

-- Idempotency ledger: prevents double-submission to broker_service on retry
-- or on duplicate Redis delivery of the same intent.
CREATE TABLE IF NOT EXISTS idempotency_keys (
    idempotency_key       TEXT PRIMARY KEY,
    order_id              UUID NOT NULL,
    created_at            TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_at            TIMESTAMPTZ NOT NULL
);

CREATE INDEX IF NOT EXISTS ix_idempotency_keys_expires_at ON idempotency_keys (expires_at);

-- RISK_HOLD parking: intents that arrived with status=RISK_HOLD.
-- Stored separately from `exec_orders` until promoted (state -> ROUTING) or expired.
CREATE TABLE IF NOT EXISTS held_intents (
    intent_id             UUID PRIMARY KEY,
    order_id              UUID NOT NULL,
    symbol                TEXT NOT NULL,
    raw_payload           JSONB NOT NULL,
    held_at               TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_at            TIMESTAMPTZ NOT NULL,
    resolved              BOOLEAN NOT NULL DEFAULT FALSE
);

CREATE INDEX IF NOT EXISTS ix_held_intents_expires_at ON held_intents (expires_at) WHERE NOT resolved;
