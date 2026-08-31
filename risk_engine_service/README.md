# risk_engine_service (port 8007)

Final pre-trade risk validation layer for the SG Trading Platform pipeline.
Sits between `execution_orchestrator_service` (8006, eligibility + Kelly
allocation) and `execution_engine` (8008, order placement).

```
sg:intents:{symbol}  →  risk_engine (8007)  →  sg:risk_approved:{symbol} | sg:risk_rejected:{symbol}
```

## Decisions made for this build

These were left open in the original spec and resolved as follows:

1. **VaR methodology: Parametric (variance-covariance).** Chosen because
   it's the only method that can run synchronously in a real-time
   pre-trade hot path without an extra heavy historical-series fetch per
   intent — it only needs the symbol's annualized volatility, which the
   volatility policy already fetches. `app/policies.py::calc_parametric_var_inr`
   is isolated behind a narrow interface so a historical-simulation or
   Monte Carlo method can be swapped in later (see `VAR_METHOD` env var,
   currently informational only — wire a second implementation when needed).

2. **Margin check: resilient with fallback chain.** `BrokerServiceClient`
   tries a live call to `broker_service` `/margins` first. On failure it
   falls back to the last cached snapshot in Redis, and if no cache
   exists either, to a conservative synthetic snapshot (50% of NAV
   assumed free) — so a broker outage degrades the engine toward
   caution rather than blocking the pipeline or fail-open. Set
   `MARGIN_CHECK_MODE=strict` to instead hard-fail when broker_service is
   unreachable, or `disabled` to skip the check entirely.

3. **Kill switch: both manual and automatic, asymmetric reset.** Manual
   activate/deactivate is a simple operator pause. Automatic halts
   (drawdown, daily loss, circuit breaker, emergency stop) are a hard
   stop: a plain "deactivate" call returns 409 and cannot clear them —
   only `/risk/kill-switch/reset`, gated to the `risk_officer` role
   (configurable via `KILL_SWITCH_AUTO_RESET_REQUIRES_ROLE`), can. This
   prevents a single careless API call from silently re-enabling trading
   after a genuine risk breach.

## What's implemented

- **Risk policies** — `risk_policies` table (seeded in `sql/schema.sql`),
  hot-reloadable via `PUT /risk/policies/{name}`, cached in-process for 15s.
- **Risk evaluation engine** — `app/evaluator.py`, runs all checks (no
  short-circuit, mirroring orchestrator's pattern): position sizing, VaR,
  drawdown, daily loss, concentration, sector exposure, correlation,
  volatility, symbol circuit breaker, margin.
- **Risk scoring** — `app/scoring.py`, weighted composite 0–100 score with
  LOW/MEDIUM/HIGH/CRITICAL bands; any hard-failed check pulls the score
  toward CRITICAL regardless of weighting.
- **Kill switch / emergency stop** — `app/kill_switch.py`, full state
  machine + audit trail in `kill_switch_events`.
- **Symbol-level circuit breakers** — `app/circuit_breaker.py`, separate
  from the global kill switch, auto-trips on intraday move breach with a
  cool-down TTL.
- **Dashboard / admin APIs** — `app/api.py`: decisions feed, per-symbol
  score, portfolio exposure, policy CRUD, kill-switch controls, circuit
  breaker controls, and an SSE live event stream at `/risk/stream`.
- **Persistence** — `risk_decisions`, `risk_audit_logs`, `kill_switch_events`,
  `circuit_breaker_events`, `risk_policies` tables.
- **Observability** — structlog JSON logs, `prometheus-fastapi-instrumentator`
  + custom metrics in `app/metrics.py`, OpenTelemetry tracing via OTLP.

## Known gaps / explicit extension points

- `SECTOR_MAP` in `app/evaluator.py` is empty — sector exposure check will
  pass-through (skipped) until a sector reference table or
  market_data_service endpoint is wired in.
- `app/clients.py::MarketDataClient` assumes `market_data_service` exposes
  `/symbols/{symbol}/volatility`, `/correlation-matrix`, and
  `/symbols/{symbol}/intraday-move` — these endpoints don't exist yet per
  the completed services list and need to be added to 8002, or pointed at
  whatever the real endpoints turn out to be.
- `BrokerServiceClient` assumes a `/margins` and `/portfolio/snapshot`
  endpoint on broker_service (8003) — same caveat.
- Historical/Monte Carlo VaR method not implemented (parametric only).
- JWT verification expects an RS256 public key file at
  `AUTH_JWT_PUBLIC_KEY_PATH`; in non-production env without that file it
  degrades to a dev stub user with `risk_officer`+`admin` roles — **do not
  ship that fallback to production** (it already fails closed when
  `ENV=production`).

## Running locally

```bash
pip install -e .
psql $POSTGRES_DSN -f sql/schema.sql
uvicorn app.main:app --reload --port 8007
```

## Endpoints

| Method | Path | Purpose |
|---|---|---|
| GET | /health, /health/ready | liveness/readiness |
| GET | /metrics | Prometheus |
| GET | /risk/decisions | recent risk decisions (filter by symbol/status) |
| GET | /risk/score/{symbol} | latest composite score for a symbol |
| GET | /risk/portfolio/exposure | current portfolio snapshot |
| GET / PUT | /risk/policies[/{name}] | view / update risk policy thresholds |
| GET | /risk/kill-switch/status | current kill switch state |
| POST | /risk/kill-switch/activate | manual halt |
| POST | /risk/kill-switch/deactivate | resume from manual halt only |
| POST | /risk/kill-switch/reset | clear an automatic halt (role-gated) |
| POST | /risk/emergency-stop | highest-severity halt |
| GET | /risk/circuit-breaker/status?symbols=A,B | per-symbol breaker state |
| POST | /risk/circuit-breaker/{symbol}/trigger\|reset | manual breaker control (role-gated) |
| GET | /risk/stream | SSE live event feed for dashboards |
