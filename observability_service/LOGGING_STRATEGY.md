# Logging Strategy — SG Trading Platform

This describes the logging contract every service is expected to follow, and
how Loki/Promtail are configured against it. It extends, not replaces, the
existing platform convention ("structlog, JSON in production, ConsoleRenderer
in dev, `configure_logging()` at module level").

## 1. Format

Production logs are single-line JSON to stdout. Required fields on every
log record:

| Field       | Type   | Notes |
|-------------|--------|-------|
| `timestamp` | string | RFC3339Nano. Promtail uses this as the Loki ingest timestamp instead of arrival time. |
| `level`     | string | `debug` \| `info` \| `warning` \| `error` \| `critical` |
| `logger`    | string | module path, e.g. `app.services.risk_engine` |
| `event`     | string | short machine-grep-able event name, e.g. `order_filled`, `risk_intent_rejected` — not a full sentence |
| `service`   | string | matches the Prometheus `job` label for that service (e.g. `risk_engine_service`) |

Recommended/conditional fields:

| Field          | When |
|----------------|------|
| `trace_id`, `span_id` | Whenever the log is emitted inside a traced request — lets Grafana jump log→trace and trace→log via the provisioned derived fields / `tracesToLogsV2`. Requires each service's OTel instrumentation to inject these into the structlog context (e.g. a processor that pulls from `opentelemetry.trace.get_current_span()`) — **not confirmed as already wired in any service this session; this is new work, not an existing guarantee.** |
| `correlation_id` | Anywhere the platform's existing `correlation_id` (frozen on `ExecutionEvent` and propagated pipeline-wide) is in scope — lets you trace one trading decision end-to-end across services even without full distributed tracing. |
| `symbol`, `order_id`, `intent_id` | Any trading-domain log line — keep these as top-level fields, not buried in a nested blob, so Loki's JSON parser and LogQL filters can target them directly (e.g. `{service="risk_engine_service"} | json | symbol="RELIANCE"`). |

## 2. Levels — what goes where

- `debug` — verbose internals, off by default in production (configurable per
  service via existing `Settings.env` pattern).
- `info` — normal lifecycle events: requests served, orders filled, jobs
  completed, cache hits/misses.
- `warning` — degraded-but-handled conditions: a missing upstream source that
  was gracefully degraded (e.g. ai_analyst_service's context_builder marking a
  source unavailable), rate limiter fail-open, drift threshold crossed,
  fallback model in use.
- `error` — a request failed, a job failed, an upstream call failed and was
  *not* gracefully handled.
- `critical` — reserved for conditions that should page immediately even
  outside of a metric-based alert: kill switch engaged, circuit breaker open,
  unrecoverable startup failure.

`Error-level log rate` is graphed on the per-service dashboard
(`infra/service-detail.json`) as a leading indicator that's often faster to
spike than a 5xx-rate metric, especially for background-task failures (job
queues, Redis consumers) that never touch the HTTP layer at all.

## 3. Redaction

Two layers, intentionally redundant:

1. **App-level (existing, authoritative)** — structlog auto-redacts
   `api_key` / `token` / `prompt` / `system_prompt` fields, established in
   `ai_analyst_service` (8012). Every service handling secrets should carry
   the same processor — see 8012's `app/core/logging.py` for the pattern to
   copy.
2. **Promtail-level (defense in depth, this PR)** — a regex `replace` stage
   redacts `api_key` / `token` / `password` / `secret` JSON fields that reach
   the log pipeline regardless of whether the app-level redaction fired.
   This is a safety net, not a substitute — it's a generic regex over JSON
   text and won't catch every encoding a secret could appear in.

`ai_audit_log` (8012) and any equivalent audit tables remain the authoritative,
metadata-only compliance record — full prompt/response text is never logged
to either the application logger or this stack, by design.

## 4. Retention

| Store | Default retention | Configurable via |
|-------|--------------------|-------------------|
| Loki  | 30 days (720h) | `LOKI_RETENTION_HOURS` in `.env`, `limits_config.retention_period` in `loki-config.yaml` |
| Tempo | 7 days (168h)  | `compactor.compaction.block_retention` in `tempo.yaml` |
| Prometheus | 30 days | `PROMETHEUS_RETENTION` in `.env` |

These are personal-deployment defaults, intentionally short to keep local disk
usage bounded. Raise them if you need longer audit lookback — Loki and
Prometheus retention are independent of `ai_audit_log`'s own (presumably
longer/permanent) Postgres retention.

## 5. Correlation strategy — tying logs, metrics, and traces together

- **Logs → Traces**: a log line containing `"trace_id":"..."` renders a
  clickable "View Trace" button in Grafana (Loki datasource `derivedFields`).
- **Traces → Logs**: viewing a trace in Tempo offers a "Logs for this span"
  link back into Loki, scoped to the trace's time window and `service.name`
  (`tracesToLogsV2` in the Tempo datasource).
- **Metrics → Traces**: Prometheus exemplars (`exemplarTraceIdDestinations`)
  let a latency spike on a histogram panel jump directly to one of the actual
  slow requests behind it — requires each service's histogram instrumentation
  to attach exemplars, which `prometheus-fastapi-instrumentator` supports but
  may need `instrumentator.instrument(app, should_respect_env_var=False)` /
  exemplar support enabled explicitly per service — **not confirmed as already
  enabled anywhere; check before relying on this link working out of the box.**

## 6. What this stack does NOT do

- It does not replace `ai_audit_log` or any other compliance-grade audit
  table — those stay in Postgres as the system of record.
- It does not capture full request/response bodies for the LLM-calling
  service — by design, per 8012's existing redaction rules.
- It does not currently sample high-volume debug logs — if a service's debug
  volume becomes a cost/storage problem, add a Promtail `drop` stage or switch
  that service's production log level, rather than changing Loki's global
  retention.
