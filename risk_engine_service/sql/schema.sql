-- risk_engine_service schema additions to sg_db
-- Run against the shared sg_db Postgres 17 instance.

CREATE TABLE IF NOT EXISTS risk_policies (
    policy_name         VARCHAR(64) PRIMARY KEY,
    enabled              BOOLEAN NOT NULL DEFAULT TRUE,
    params               JSONB NOT NULL DEFAULT '{}'::jsonb,
    description          TEXT,
    updated_by           VARCHAR(128),
    updated_at           TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS risk_decisions (
    id                       BIGSERIAL PRIMARY KEY,
    intent_id                UUID NOT NULL,
    correlation_id            UUID NOT NULL,
    symbol                    VARCHAR(32) NOT NULL,
    action                    VARCHAR(8) NOT NULL,
    original_allocation_inr   NUMERIC(18,2) NOT NULL,
    approved_allocation_inr   NUMERIC(18,2),
    risk_score                NUMERIC(5,2) NOT NULL,
    risk_band                 VARCHAR(16) NOT NULL,
    var_inr                   NUMERIC(18,2),
    var_percent_of_portfolio  NUMERIC(8,4),
    status                    VARCHAR(16) NOT NULL,         -- RISK_APPROVED | RISK_REJECTED | RISK_HOLD
    rejection_reasons         JSONB NOT NULL DEFAULT '[]'::jsonb,
    checks                    JSONB NOT NULL DEFAULT '{}'::jsonb,
    kill_switch_active        BOOLEAN NOT NULL DEFAULT FALSE,
    market_regime             VARCHAR(24),
    evaluated_at               TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_risk_decisions_symbol ON risk_decisions(symbol);
CREATE INDEX IF NOT EXISTS idx_risk_decisions_intent ON risk_decisions(intent_id);
CREATE INDEX IF NOT EXISTS idx_risk_decisions_evaluated_at ON risk_decisions(evaluated_at DESC);

CREATE TABLE IF NOT EXISTS risk_audit_logs (
    id              BIGSERIAL PRIMARY KEY,
    intent_id        UUID,
    event_type        VARCHAR(64) NOT NULL,     -- e.g. CHECK_FAIL, OVERRIDE, MARGIN_FALLBACK
    detail            JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_risk_audit_intent ON risk_audit_logs(intent_id);

CREATE TABLE IF NOT EXISTS kill_switch_events (
    id              BIGSERIAL PRIMARY KEY,
    previous_state    VARCHAR(32) NOT NULL,
    new_state         VARCHAR(32) NOT NULL,
    reason             TEXT,
    triggered_by       VARCHAR(16) NOT NULL,    -- MANUAL | AUTOMATIC
    actor               VARCHAR(128),             -- user id / "system"
    metadata            JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS circuit_breaker_events (
    id              BIGSERIAL PRIMARY KEY,
    symbol            VARCHAR(32) NOT NULL,
    state              VARCHAR(16) NOT NULL,     -- TRIPPED | RESET
    reason              TEXT,
    metric_value         NUMERIC(12,4),
    threshold             NUMERIC(12,4),
    created_at            TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_circuit_breaker_symbol ON circuit_breaker_events(symbol);

-- Seed default policies (idempotent)
INSERT INTO risk_policies (policy_name, enabled, params, description) VALUES
('var_limit',            TRUE, '{"max_var_percent_of_portfolio": 2.0, "confidence": 0.95, "horizon_days": 1, "method": "parametric"}', 'Max 1-day 95% VaR as % of portfolio NAV per intent'),
('drawdown_limit',       TRUE, '{"max_drawdown_percent": 10.0, "warn_drawdown_percent": 7.0}', 'Halt new risk-on intents past max drawdown from equity peak'),
('daily_loss_limit',     TRUE, '{"max_daily_loss_percent": 3.0, "warn_daily_loss_percent": 2.0}', 'Halt new intents past daily realized+unrealized loss limit'),
('concentration_limit',  TRUE, '{"max_single_position_percent": 8.0}', 'Max % of portfolio NAV in a single symbol post-trade'),
('sector_exposure_limit',TRUE, '{"max_sector_percent": 25.0}', 'Max % of portfolio NAV in a single sector post-trade'),
('correlation_limit',    TRUE, '{"max_avg_correlation": 0.75, "lookback_days": 60}', 'Max average correlation vs existing open positions'),
('volatility_limit',     TRUE, '{"max_annualized_vol_percent": 80.0, "circuit_breaker_intraday_move_percent": 7.0, "circuit_breaker_window_minutes": 5}', 'Volatility guardrails + symbol-level circuit breaker'),
('margin_check',         TRUE, '{"min_free_margin_buffer_percent": 15.0, "mode": "resilient"}', 'Ensure sufficient free margin remains after allocation'),
('position_sizing',      TRUE, '{"max_allocation_per_intent_percent": 10.0, "min_allocation_inr": 500.0}', 'Hard bounds on per-intent allocation regardless of Kelly output'),
('risk_score_threshold', TRUE, '{"reject_at_or_above": 81, "hold_band": [61, 80]}', 'Composite risk score bands controlling auto-reject / hold')
ON CONFLICT (policy_name) DO NOTHING;
