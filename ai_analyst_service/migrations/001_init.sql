-- 001_init.sql — ai_analyst_service schema (sg_db, ai_ prefixed tables)

CREATE TABLE IF NOT EXISTS ai_prompt_templates (
    id              UUID PRIMARY KEY,
    capability      TEXT NOT NULL,
    version         INTEGER NOT NULL,
    system_prompt   TEXT NOT NULL,
    user_template   TEXT NOT NULL,
    is_active       BOOLEAN NOT NULL DEFAULT false,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    created_by      TEXT,
    UNIQUE (capability, version)
);

-- Only one active version per capability.
CREATE UNIQUE INDEX IF NOT EXISTS idx_ai_prompt_templates_active
    ON ai_prompt_templates (capability)
    WHERE is_active;

CREATE TABLE IF NOT EXISTS ai_audit_log (
    id              UUID PRIMARY KEY,
    user_sub        TEXT NOT NULL,
    capability      TEXT NOT NULL,
    cache_hit       BOOLEAN NOT NULL,
    status          TEXT NOT NULL,
    latency_ms      DOUBLE PRECISION NOT NULL,
    input_tokens    INTEGER NOT NULL DEFAULT 0,
    output_tokens   INTEGER NOT NULL DEFAULT 0,
    error           TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_ai_audit_log_created_at ON ai_audit_log (created_at DESC);
CREATE INDEX IF NOT EXISTS idx_ai_audit_log_user_sub ON ai_audit_log (user_sub, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_ai_audit_log_capability ON ai_audit_log (capability, created_at DESC);

COMMENT ON TABLE ai_audit_log IS
    'Compliance/cost audit trail of every LLM-backed analysis request. Never stores prompt or response text — only metadata.';
