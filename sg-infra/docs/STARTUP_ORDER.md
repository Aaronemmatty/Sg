# Startup Order & Timing — SG Trading Platform

This describes what `./sg up` actually does, in what order, and how long to
wait before concluding something is actually broken (vs. just still
booting). Timings are estimates based on what each service does at
startup (model loads, import-heavy dependencies, DB pool init, etc.) —
not measured production telemetry. Treat them as planning numbers, and
tighten them once you've watched a few real startups (`./sg health
--watch`).

## Dependency graph (what waits on what)

```
postgres ──┬──► migrate (one-shot, run manually: ./sg migrate)
           │
           ├──► mlflow
           │
           └──► auth_service ◄── redis
                    │
       ┌────────────┼─────────────────────────────────────────┐
       ▼            ▼                                         ▼
market_data_service  ai_analyst_service          (everything else needing
       │                                          only postgres+redis+auth)
       ├──► broker_service
       ├──► strategy_service
       ├──► regime_detection_service
       ├──► portfolio_management_service
       └──► backtesting_engine_service
                │
                ▼
       execution_orchestrator_service ──► (needs auth + postgres/redis only;
                                            calls broker/portfolio at runtime,
                                            doesn't block startup on them)
       risk_engine_service ──► execution_engine_service
       broker_service + risk_engine_service ──► execution_engine_service

regime_detection_service + strategy_service (started, not nec. healthy)
       └──► signal_aggregation_service

auth_service ──► dashboard ──► nginx

prometheus/loki/tempo/alertmanager/otel-collector/grafana/exporters: no
dependency on the app tier at all — they start in parallel with everything
above. node-exporter/cadvisor/redis-exporter have no meaningful "healthy"
state to wait for; postgres-exporter and grafana wait on postgres /
prometheus+loki+tempo respectively.
```

## Per-component boot time (rough, cold start with images already built/pulled)

| Component | Typical time to "healthy" | Why |
|---|---|---|
| redis | 2–5s | trivial |
| postgres | 10–20s | first-boot init + `pg_isready` |
| node-exporter / cadvisor / otel-collector / alertmanager | 2–10s | no DB, fast boot |
| auth_service | 10–20s | waits on postgres+redis, then RSA key parse + pool init |
| market_data_service, broker_service, strategy_service, execution_orchestrator_service, risk_engine_service, execution_engine_service, portfolio_management_service, ai_analyst_service, signal_aggregation_service | 10–20s | standard FastAPI boot once their deps are healthy |
| regime_detection_service | 15–25s | loads a joblib-pickled classifier model on top of the standard boot |
| mlflow | 20–35s | installs psycopg at container start, then opens backend store |
| backtesting_engine_service | 20–30s | heavier numerical-stack import (pandas/numpy + Monte Carlo deps) |
| ml_platform_service | **25–45s (slowest platform service)** | heaviest dependency import (sklearn/pandas + MLflow client) + first MLflow handshake |
| dashboard | 10–20s | Next.js standalone server boot, after auth_service is healthy |
| nginx | <5s | after dashboard is healthy |
| prometheus | 10–15s | TSDB open |
| loki / tempo | 10–15s | small local stores |
| grafana | **20–40s (slowest observability service)** | provisions datasources/dashboards + sqlite init on first boot |
| postgres-exporter / redis-exporter | 5–10s | once their target DB is healthy |

## Recommended wait before declaring a deploy failed

- **Per-service** (used by `scripts/blue_green_deploy.sh`): 60s (30 attempts
  × 2s). This is generous for everything except a genuinely broken image.
- **Whole-stack `./sg up` from cold**: budget **3 minutes (180s)** after
  `docker compose up -d` returns before treating "still unhealthy" as a
  real failure. The critical path is postgres (~20s) → auth_service
  (~20s more) → everything else in parallel, with ml_platform_service and
  grafana as the long poles (~45s and ~40s respectively, but those start
  immediately in parallel with auth_service rather than after it). 180s
  comfortably covers that with margin for a cold disk cache or a busy
  laptop.
- **Blue-green deploy of a single service** (`./sg deploy <service>`):
  60–90s is normally enough; ml_platform_service and backtesting_engine_
  service may occasionally need the full 60s health-check budget the
  script already gives them.
- If something is still unhealthy past 3 minutes, it's a real problem —
  check `./sg logs <service>` rather than waiting longer.

## First-time setup order

1. `./sg secrets --patch-env` — generates `.env` with random
   POSTGRES_PASSWORD/REDIS_PASSWORD/SESSION_SECRET/GRAFANA_PASSWORD/
   SECRET_KEY and a fresh JWT RS256 keypair (also exports the public key
   to `docker/secrets/auth_public_key.pem` for the Docker secret mount).
2. Manually fill in `KITE_API_KEY`/`KITE_API_SECRET` (if not using
   `KITE_MODE=mock`/`BROKER_MODE=paper`), `ANTHROPIC_API_KEY` (required —
   ai_analyst_service won't boot without it), and `DATA_SOURCE_NAME` (needs
   a dedicated read-only Postgres role — see `.env.example` for the exact
   `CREATE ROLE` step, which has to happen *after* the first `./sg up`).
3. `./sg up` — creates `sg_network` if missing, starts everything, then
   runs the health check once for you.
4. `./sg migrate` — runs the shared core-schema migration. See
   `docs/DEPLOYMENT_NOTES.md` → "Migrations" for what this does and
   doesn't cover.
5. `./sg health --watch` while things settle, if you want to watch it live.

## Native Python 3.13 Setup (Windows / Local Monorepo)

When running without Docker on Windows:

1. Ensure PostgreSQL (5432) and Redis (6379) are running locally or via lightweight containers.
2. Run the unified environment setup script:
   ```powershell
   powershell -ExecutionPolicy Bypass -File .\setup_env.ps1
   ```
   This validates Python 3.13, creates `%REPO%\.venv`, installs `database` and `sg_security` in editable mode, and installs all 13 services.
3. Launch all 13 services in separate windows:
   ```cmd
   start_all.bat
   ```
4. Stop all services when finished:
   ```cmd
   stop_all.bat
   ```
