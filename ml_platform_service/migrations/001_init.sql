-- ml_platform_service (8011) — initial schema
-- All tables use ml_ prefix to avoid collision with pm_ tables from 8009.

-- ── Training jobs ─────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS ml_training_jobs (
    job_id              UUID PRIMARY KEY,
    model_type          TEXT NOT NULL,
    symbol              TEXT NOT NULL,
    target_type         TEXT NOT NULL DEFAULT 'direction',
    status              TEXT NOT NULL DEFAULT 'pending'
                            CHECK (status IN ('pending','running','completed','failed')),
    n_samples           INTEGER NOT NULL DEFAULT 0,
    train_metric        NUMERIC(10,6),
    val_metric          NUMERIC(10,6),
    test_metric         NUMERIC(10,6),
    best_params         JSONB NOT NULL DEFAULT '{}',
    mlflow_run_id       TEXT,
    model_version_id    UUID,
    error_message       TEXT,
    started_at          TIMESTAMPTZ,
    completed_at        TIMESTAMPTZ,
    duration_seconds    NUMERIC(10,2),
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS ix_ml_training_jobs_symbol_type
    ON ml_training_jobs (symbol, model_type, created_at DESC);
CREATE INDEX IF NOT EXISTS ix_ml_training_jobs_status
    ON ml_training_jobs (status);

-- ── Model versions (registry) ─────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS ml_model_versions (
    version_id              UUID PRIMARY KEY,
    model_type              TEXT NOT NULL,
    symbol                  TEXT NOT NULL,
    target_type             TEXT NOT NULL DEFAULT 'direction',
    status                  TEXT NOT NULL DEFAULT 'trained'
                                CHECK (status IN ('training','trained','validating',
                                                  'champion','challenger','retired','failed')),
    artifact_path           TEXT NOT NULL DEFAULT '',
    mlflow_run_id           TEXT,
    train_metric            NUMERIC(10,6),
    val_metric              NUMERIC(10,6),
    test_metric             NUMERIC(10,6),
    directional_accuracy    NUMERIC(10,6),
    sharpe_on_signals       NUMERIC(10,6),
    hyperparams             JSONB NOT NULL DEFAULT '{}',
    feature_count           INTEGER NOT NULL DEFAULT 0,
    n_samples               INTEGER NOT NULL DEFAULT 0,
    training_job_id         UUID REFERENCES ml_training_jobs(job_id) ON DELETE SET NULL,
    promoted_at             TIMESTAMPTZ,
    retired_at              TIMESTAMPTZ,
    created_at              TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS ix_ml_model_versions_symbol_type_status
    ON ml_model_versions (symbol, model_type, status);
CREATE INDEX IF NOT EXISTS ix_ml_model_versions_status
    ON ml_model_versions (status);

-- Only one champion per (symbol, model_type)
CREATE UNIQUE INDEX IF NOT EXISTS uq_ml_champion_per_symbol_type
    ON ml_model_versions (symbol, model_type)
    WHERE status = 'champion';

-- ── Feature snapshots (feature store persistence) ─────────────────────────

CREATE TABLE IF NOT EXISTS ml_feature_snapshots (
    snapshot_id     BIGSERIAL PRIMARY KEY,
    symbol          TEXT NOT NULL,
    timestamp       TIMESTAMPTZ NOT NULL,
    features        JSONB NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (symbol, timestamp)
);

CREATE INDEX IF NOT EXISTS ix_ml_feature_snapshots_symbol_ts
    ON ml_feature_snapshots (symbol, timestamp DESC);

-- Auto-expire snapshots older than 90 days (run via pg_cron or scheduled job):
-- DELETE FROM ml_feature_snapshots WHERE created_at < now() - INTERVAL '90 days';

-- ── Predictions ───────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS ml_predictions (
    prediction_id       UUID PRIMARY KEY,
    model_version_id    UUID NOT NULL,
    model_type          TEXT NOT NULL,
    symbol              TEXT NOT NULL,
    timestamp           TIMESTAMPTZ NOT NULL,
    direction           TEXT NOT NULL CHECK (direction IN ('LONG','SHORT','FLAT')),
    confidence          NUMERIC(8,6) NOT NULL,
    raw_probabilities   JSONB NOT NULL DEFAULT '{}',
    predicted_return    NUMERIC(12,8),
    latency_ms          NUMERIC(10,3),
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS ix_ml_predictions_symbol_created
    ON ml_predictions (symbol, created_at DESC);
CREATE INDEX IF NOT EXISTS ix_ml_predictions_model_type
    ON ml_predictions (model_type, created_at DESC);

-- ── Prediction outcomes ───────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS ml_prediction_outcomes (
    outcome_id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    prediction_id           UUID NOT NULL REFERENCES ml_predictions(prediction_id) ON DELETE CASCADE,
    symbol                  TEXT NOT NULL,
    model_type              TEXT NOT NULL,
    predicted_direction     TEXT NOT NULL,
    actual_direction        TEXT,
    actual_return           NUMERIC(12,8),
    correct                 BOOLEAN,
    outcome_at              TIMESTAMPTZ,
    recorded_at             TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (outcome_id)
);

CREATE INDEX IF NOT EXISTS ix_ml_prediction_outcomes_symbol_model
    ON ml_prediction_outcomes (symbol, model_type, outcome_at DESC);
CREATE INDEX IF NOT EXISTS ix_ml_prediction_outcomes_prediction
    ON ml_prediction_outcomes (prediction_id);

-- ── Drift reports ─────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS ml_drift_reports (
    report_id           UUID PRIMARY KEY,
    symbol              TEXT NOT NULL,
    model_version_id    UUID NOT NULL,
    feature_psi         JSONB NOT NULL DEFAULT '{}',
    overall_psi         NUMERIC(10,6) NOT NULL DEFAULT 0,
    drift_detected      BOOLEAN NOT NULL DEFAULT false,
    n_reference_samples INTEGER NOT NULL DEFAULT 0,
    n_current_samples   INTEGER NOT NULL DEFAULT 0,
    computed_at         TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS ix_ml_drift_reports_symbol_computed
    ON ml_drift_reports (symbol, computed_at DESC);
CREATE INDEX IF NOT EXISTS ix_ml_drift_reports_version
    ON ml_drift_reports (model_version_id, computed_at DESC);
