# Master Compose — Findings & Design Notes

Read this before deploying. Building the master compose surfaced several
real inconsistencies in the existing repo that the spec's requirements
can't be satisfied literally without addressing. Each is documented here
with what was found, what was changed, and the alternative if you'd
rather resolve it differently.

## 1. Port conflict: signal_aggregation_service vs execution_orchestrator_service

Both `signal_aggregation_service/.env.example` (`SERVICE_PORT=8006`) and
`signal_aggregation_service/app/config.py` (`SERVICE_PORT: int = 8006`)
hardcode the same port already used by `execution_orchestrator_service`
(8006 — confirmed in its own `.env.example`, Dockerfile, and the original
sg-infra draft compose). Two containers can't both publish host port 8006.

**Resolution:** signal_aggregation_service is re-homed to **8013** (next
free slot after ai_analyst_service/8012) via a `SERVICE_PORT` environment
override in `docker-compose.yml`. The app already reads its bind port from
this env var, so no code change was needed — only the compose-level
override, plus matching updates in `scripts/blue_green_deploy.sh`,
`scripts/health_check.sh`, and `sg-dashboard`'s `SIGNAL_AGGREGATION_URL`.

**Alternative:** if you'd rather signal_aggregation_service keep its
literal repo-default port, renumber execution_orchestrator_service instead
(it's referenced in more places — sg-dashboard, nginx SSE config,
inter-service URLs — so re-homing signal_aggregation_service touches less).

## 2. Healthcheck mechanism: no service image has `curl`

The spec asks for `curl -f http://localhost:<port>/health` healthchecks.
Checked every Dockerfile in the repo: **none of the 13 platform services'
runtime stages install curl** (auth_service, market_data_service, and
broker_service install curl only in their *builder* stage, which is
discarded; the rest never install it at all). The literal healthcheck as
specified would fail with "executable file not found" on every container.

**Resolution:** `docker-compose.yml` uses
`python3 -c "import urllib.request; urllib.request.urlopen(...)"` instead.
python3 is guaranteed in every one of these images (it's the interpreter
running the app) and is exactly the pattern auth_service,
market_data_service, broker_service, regime_detection_service and
signal_aggregation_service already bake into their own Dockerfile
`HEALTHCHECK` lines — so this isn't a new convention, it's standardizing
on the one that's already proven. `scripts/blue_green_deploy.sh`'s
in-container health probe was updated the same way (with a wget/curl
fallback chain, since the dashboard's node:alpine image has wget but not
curl either). `scripts/health_check.sh` is unaffected — it curls from the
**host** against the 127.0.0.1-published ports, where curl is the
operator's own machine, not the container.

**Alternative:** add `RUN apt-get install -y curl` (or `apk add curl` for
alpine-based images) to each service's runtime stage if you want the
literal curl-based healthcheck. Not done here since it means rebuilding
every service's Dockerfile, which is outside this prompt's stated scope
(wiring the master compose, not patching the 13 services again).

## 3. Blue/green compatibility: the existing script would have duplicated or destroyed shared infra

`scripts/blue_green_deploy.sh` (as delivered going into this prompt) calls
`docker compose -p $NEXT_PROJECT ... up -d` and
`docker compose -p $CURRENT_PROJECT ... down --remove-orphans` with **no
service arguments** — i.e. against the whole compose file. Once Postgres/
Redis/MLflow/observability/nginx are merged into that same file (which
this prompt requires), that unscoped invocation would have:

- tried to start a **second Postgres/Redis/nginx container** under the
  `sg_green` project the first time you deployed (failing outright on
  `container_name` collision, since those have fixed names — or worse,
  succeeding and mounting the *same* Postgres data volume from two
  separate containers if container_name weren't fixed), and
- on the post-deploy "stop the old slot" step, **torn down the live
  Postgres/Redis/nginx** along with the old app containers, since
  `down --remove-orphans` stops everything Compose believes that project
  owns.

**Resolution — two changes, both required together:**

1. **Infra/observability/nginx have fixed, non-project-scoped
   `container_name`s** (`sg_postgres`, `sg_redis`, `sg_mlflow`, `sg_nginx`,
   `sg_prometheus`, etc.) — they are singletons, started once by whichever
   project runs `./sg up` first (sg_blue, by convention), and are never
   touched by blue/green.
2. **The 13 platform services + dashboard use
   `container_name: ${COMPOSE_PROJECT_NAME}_<service>`** — Compose
   interpolates the active `-p` value here, so `sg_blue_auth_service` and
   `sg_green_auth_service` coexist on the shared network without
   colliding. Their inter-service URLs (`AUTH_SERVICE_URL`,
   `MARKET_DATA_SERVICE_URL`, etc.) use the same
   `${COMPOSE_PROJECT_NAME}_...` pattern, so each slot's services only ever
   call **their own slot's** copies — never round-robin into the other
   slot's containers. `scripts/blue_green_deploy.sh` was rewritten to pass
   an explicit `APP_SERVICES` list (the 13 services + dashboard) to every
   `build`/`up`/`stop` call, and **never** invokes those verbs against the
   whole file. `cmd_status` and the final stop step in `cmd_deploy` were
   fixed the same way.

This requires `${COMPOSE_PROJECT_NAME}` interpolation, which depends on
Docker Compose actually exposing that as an interpolation variable when
invoked with `-p`. This is standard, documented Compose V2 behavior, but
if you're on an older Compose version, verify with:
`docker compose -p sg_blue config | grep container_name` before relying
on it in production.

## 4. nginx didn't actually switch slots

The original `switch_nginx_to_slot()` wrote a `set $active_dashboard ...;`
line into `active_slot.conf` — but `platform.conf`'s `upstream` blocks were
static (`server dashboard:3000;`) and never referenced that variable. The
blue/green "traffic switch" step was therefore cosmetic; nginx kept
routing to whatever `dashboard:3000` resolved to regardless of which slot
had actually been health-checked.

**Resolution:** split nginx config into `00-upstreams.conf` (generated,
contains the `upstream` blocks pointing at the live slot's container
names — e.g. `server sg_green_dashboard:3000;`) and `10-platform.conf`
(static `location` blocks only, never touched by a deploy).
`switch_nginx_to_slot()` now rewrites `00-upstreams.conf` with the literal
slot-prefixed container names and reloads nginx — so the switch is real.
The SSE upstreams (`portfolio_svc`, `risk_svc`, `execution_svc`) get the
same treatment, since they're proxied through nginx too.

## 5. Database name mismatch (`sg_db` vs `sg_platform`)

auth_service's and strategy_service's own standalone dev
`docker-compose.yml` files default to a database called `sg_platform`;
every other service's `.env.example` (and the prompt itself: *"PostgreSQL
17 (sg_db)"*) uses `sg_db`. **Resolution:** the master compose standardizes
on `sg_db` for all 13 services — their standalone dev compose files are
unaffected and untouched.

## 6. Two divergent, stale observability configs

`sg-infra/docker/prometheus/` (an earlier, incomplete attempt — postgres/
redis exporters assumed running as sidecars on ports that don't match the
actual exporter containers, a different rule file, no Loki/Tempo/
Alertmanager job at all) coexists with the complete, tested
`observability_service/` stack delivered in Prompt 6. **Resolution:** the
master compose pulls exclusively from `observability_service/` per the
prompt's explicit instruction ("merge into master compose, do not
duplicate"). The stale `sg-infra/docker/prometheus/` directory is left in
place (nothing in this delivery deletes it) but is no longer referenced —
recommend deleting it in a follow-up cleanup to avoid future confusion.

## 7. Build-context path bug

The file lives at `sg-infra/docker/docker-compose.yml` (confirmed by where
`./sg` already points), but the pre-existing draft master compose used
`context: ../auth_service` — one level too shallow; `auth_service` is a
sibling of `sg-infra/`, two levels up from `sg-infra/docker/`, not one.
Every service `context:` in the delivered file uses `../../<service>`.
Same fix applied to all `observability_service/...` config mounts.

## 8. Migrations are inconsistent across services and only partially automated here

- `database/` (the shared core-schema package: tenants, users, roles,
  portfolios, etc.) uses Alembic and reads `DATABASE_URL`. A one-shot
  `migrate` service runs this (`./sg migrate`).
- auth_service, execution_orchestrator_service, regime_detection_service,
  and signal_aggregation_service ship their **own** Alembic setup inside
  their image (alembic.ini + migrations copied at build time).
- risk_engine_service ships a `sql/` directory of raw SQL scripts, not
  Alembic.
- execution_engine_service, portfolio_management_service,
  backtesting_engine_service, and ai_analyst_service copy a `migrations/`
  directory into their image whose tooling wasn't independently verified
  here.
- ml_platform_service's Dockerfile copies no migration tooling at all.

**This delivery only automates the shared core-schema migration.**
Verify and run each service's own migration mechanism before going live —
this is a pre-existing gap in the repo, not something introduced by the
master compose, but it's surfaced here because "one-command startup"
implies migrations are handled, and right now they're only partially
handled.

## 9. Why `sg_network` is `external: true`

Requirement #1 asks for a single bridge network. Declaring it normally
(not external) inside the compose file would make Compose namespace it per
*project* (`sg_blue_sg_network` vs `sg_green_sg_network`), which defeats
the entire point — nginx (singleton) couldn't reach either slot's
containers, and the two slots couldn't share Postgres/Redis. `./sg up`
creates `sg_network` once, outside any project's ownership, specifically so
both `sg_blue` and `sg_green` — and the singleton infra — all land on the
same network regardless of which project started them.
