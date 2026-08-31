# observability_service

Platform-wide monitoring infrastructure for the SG Trading Platform.
Covers metrics (Prometheus + Grafana), distributed tracing (OpenTelemetry →
Tempo), structured logging (Loki + Promtail), and alerting (Alertmanager →
Telegram).

**This is not a 13th FastAPI microservice.** There's no `app/main.py` — the
deliverable is configuration: scrape configs, alert rules, dashboards-as-code,
and collector pipelines, wired together via a standalone Docker Compose file.
It deploys alongside the existing 12 services and is deliberately **not**
folded into the eventual master `docker-compose.yml` (that comes last, per
platform rules).

## Status

Built this session: every config file below has been syntax-validated
(YAML/JSON parse-checked). **Not yet run for real** — this sandbox has no
network access to actually pull the Docker images or hit a live Prometheus
to run `promtool check rules`. Before trusting this in production:

```bash
docker compose -f docker-compose.observability.yml --env-file .env up -d
docker compose -f docker-compose.observability.yml exec prometheus \
  promtool check rules /etc/prometheus/rules/*.yml
docker compose -f docker-compose.observability.yml exec prometheus \
  promtool check config /etc/prometheus/prometheus.yml
```

## What's confirmed vs. assumed — READ THIS FIRST

Every one of the 12 services already exposes `GET /metrics` via
`prometheus-fastapi-instrumentator` (platform convention, confirmed) — so the
HTTP-layer panels (request rate, 5xx rate, latency) and `ServiceDown` /
`HighHttp5xxRate` / `HighHttpLatencyP99` alerts work against real, existing
metric names (`up`, `http_requests_total`, `http_request_duration_seconds_bucket`)
out of the box.

**Everything domain-specific is built against an assumed custom metric name**,
because no prior handover documented each service's custom
`prometheus_client` counters/gauges — only the Redis channel contract and REST
API shapes were frozen. Every assumed metric is called out with a `description`
field directly in the dashboard JSON and an inline YAML comment in the alert
rules, naming the exact source file to check (e.g. "confirm against
`risk_engine_service` (8007)'s scoring engine output values"). See
`OPEN_ITEMS.md` for the consolidated list — isolate confirmation work there
before relying on the domain dashboards/alerts in production, per the
platform's standing rule on flagging unconfirmed cross-service assumptions.

This is the same pattern the platform already uses for REST contracts
(`market_data_client.py`, `risk_client.py`, etc. in 8010/8011/8012) — applied
here to metric names instead of REST paths.

## Architecture

```
12 services ──/metrics──────────────► Prometheus ──► Alertmanager ──► alertmanager-bot ──► Telegram
            ──OTLP (4317/4318)──────► OTel Collector ──► Tempo (traces)
            │                                      └──► Prometheus (span-derived RED metrics)
            ──stdout JSON logs──────► Promtail ──────► Loki
                                                          │
                                                          ▼
                                                       Grafana (dashboards, log↔trace↔metric correlation)

node-exporter / cadvisor / postgres-exporter / redis-exporter ──► Prometheus (infra-level)
```

## Wiring the 12 existing services (action required, not done by this PR)

This config can scrape/receive telemetry the moment each service:

1. **Metrics** — already true platform-wide (`prometheus-fastapi-instrumentator`
   established convention). No change needed for the infra dashboards/alerts.
   For the *domain* dashboards/alerts to light up, each service needs to add
   the custom `prometheus_client` counters/gauges named in `OPEN_ITEMS.md`
   (or rename the assumed metrics in this PR to match whatever they already
   export, if anything).

2. **Traces** — each service's `configure_tracing(app)` (called inside
   lifespan, per established pattern) needs `OTEL_EXPORTER_OTLP_ENDPOINT` set
   to `http://otel-collector:4317` and to actually point at this collector
   instead of a none/local exporter. Add to each service's environment in its
   own compose file:
   ```yaml
   environment:
     OTEL_EXPORTER_OTLP_ENDPOINT: http://otel-collector:4317
   ```
   and ensure each service container joins `sg_trading_net` (same network
   referenced as `external: true` in `docker-compose.observability.yml` —
   rename in that file if your actual network has a different name).

3. **Logs** — structlog's JSON renderer (production mode, established
   convention) needs to go to stdout, not a file — Promtail reads via Docker's
   log driver. Also confirm each service's Docker Compose service name
   carries the `com.docker.compose.project` label starting with `sg` (default
   compose behavior using the project directory name) so Promtail's
   `docker_sd_configs` relabel filter keeps it. See `LOGGING_STRATEGY.md` for
   the full field/level contract this assumes.

4. **Network name** — `docker-compose.observability.yml` assumes an external
   network called `sg_trading_net`. If your existing services' compose files
   use a different network name, either rename it there or add an alias.

## Running it

```bash
cp .env.example .env
# fill in TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, DATA_SOURCE_NAME
docker compose -f docker-compose.observability.yml --env-file .env up -d
```

- Grafana: http://localhost:3000 (admin / value from `GRAFANA_ADMIN_PASSWORD`,
  defaults to `changeme-on-first-login` — **change this on first login**)
- Prometheus: http://localhost:9090
- Alertmanager: http://localhost:9093
- Tempo/Loki have no exposed UI ports by design — query them through Grafana.

To get `TELEGRAM_CHAT_ID`: message your bot once, then
`GET https://api.telegram.org/bot<token>/getUpdates` and read `message.chat.id`
from the response.

## Files

```
observability_service/
├── docker-compose.observability.yml   standalone compose (NOT the master compose)
├── .env.example
├── README.md                          this file
├── LOGGING_STRATEGY.md                structured logging conventions, retention, redaction
├── RUNBOOK.md                         what to do when each alert fires
├── OPEN_ITEMS.md                      consolidated list of assumed metric names to confirm
├── prometheus/
│   ├── prometheus.yml                 scrape configs — all 12 services + exporters + otel
│   └── rules/
│       ├── infra_alerts.yml           generic SRE alerts (confirmed metrics)
│       └── domain_alerts.yml          trading-domain alerts (assumed metrics, flagged)
├── alertmanager/alertmanager.yml      severity routing + inhibition rules → Telegram
├── otel-collector/otel-collector-config.yml   OTLP receiver → Tempo + span-metrics
├── tempo/tempo.yaml                   trace storage + service-graph generator
├── loki/loki-config.yaml              log storage, 30d retention default
├── promtail/promtail-config.yaml      Docker log scraping, structlog JSON parsing, redaction
└── grafana/
    ├── provisioning/
    │   ├── datasources/datasources.yml    Prometheus + Loki + Tempo, fully cross-linked
    │   └── dashboards/dashboards.yml       provisions the two folders below
    └── dashboards/
        ├── infra/
        │   ├── platform-overview.json     all 12 services, up/down + RED metrics
        │   └── service-detail.json        single-service drilldown incl. live logs
        └── domain/
            ├── trading-pipeline.json      signal→fill→P&L funnel, kill switch, breaker
            ├── ml-platform.json           model accuracy, drift PSI, training jobs
            └── risk-engine.json           VaR, exposure, drawdown, margin, breakers
```

## Known limitations (say so explicitly, per platform convention)

- Rule files haven't been run through real `promtool check rules` (no network
  in the build sandbox) — only YAML-parsed for syntax. Run it for real before
  sign-off.
- Domain dashboards/alerts depend on custom metric names that are assumed, not
  confirmed — see `OPEN_ITEMS.md`.
- `alertmanager-bot` (metalmatze/alertmanager-bot) is the established
  open-source Alertmanager↔Telegram bridge used here rather than a hand-rolled
  service, since Alertmanager has no native Telegram receiver. It polls
  Alertmanager's API directly; no `webhook_configs` block was needed for the
  basic single-chat case used here.
- `DATA_SOURCE_NAME` for `postgres-exporter` assumes a read-only Postgres role
  (`sg_readonly`) exists. Create one rather than using a service's own
  credentials, to keep monitoring blast-radius separate from the app.
