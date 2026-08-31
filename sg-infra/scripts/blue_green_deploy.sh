#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════════════════
# SG Trading Platform — Blue-Green Deploy
# ═══════════════════════════════════════════════════════════════════
# Usage:
#   ./scripts/blue_green_deploy.sh                    # deploy all app services
#   ./scripts/blue_green_deploy.sh auth_service        # deploy one service
#   ./scripts/blue_green_deploy.sh --rollback          # rollback last deploy
#   ./scripts/blue_green_deploy.sh --status            # show which slot is live
#
# How it works:
#   - Two compose project names: sg_blue and sg_green
#   - One is always LIVE, the other is IDLE
#   - Deploy builds/starts new images in the IDLE slot
#   - Health checks all APP services in IDLE
#   - If healthy: nginx switches traffic to IDLE (now LIVE)
#   - If unhealthy: IDLE app services are torn down, LIVE keeps running
#   - Old LIVE slot's app services kept for 60s then stopped (rollback window)
#
# ── IMPORTANT — infra is NEVER duplicated ──────────────────────────
# postgres / redis / mlflow / the observability stack / nginx are singleton
# services with FIXED (non-project-scoped) container_names in
# docker/docker-compose.yml. Only the 13 platform services + dashboard are
# blue/green-scoped (their container_name uses ${COMPOSE_PROJECT_NAME}).
# This script therefore NEVER calls `up`/`down`/`build` on the whole file —
# every compose invocation below is scoped to APP_SERVICES, by design. An
# earlier version of this script called `up -d` / `down --remove-orphans`
# with no service list, which — given the master compose now lists infra
# in the SAME file — would have tried to create a second Postgres/Redis/
# nginx under the green project (failing on container_name collision) or,
# worse, on `down`, stopped the shared infra out from under the live slot.
# Do not remove the explicit service lists below.
# ═══════════════════════════════════════════════════════════════════

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(dirname "$SCRIPT_DIR")"
COMPOSE_FILE="$ROOT_DIR/docker/docker-compose.yml"
ENV_FILE="$ROOT_DIR/.env"
SLOT_FILE="$ROOT_DIR/.current_slot"       # persists: "blue" or "green"
ROLLBACK_FILE="$ROOT_DIR/.previous_slot"
LOG_FILE="$ROOT_DIR/logs/deploy.log"

mkdir -p "$ROOT_DIR/logs"

# ─── Colours ─────────────────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
BLUE='\033[0;34m'; NC='\033[0m'; BOLD='\033[1m'

log()  { echo -e "${BOLD}[$(date '+%H:%M:%S')]${NC} $*" | tee -a "$LOG_FILE"; }
ok()   { echo -e "${GREEN}✓${NC} $*" | tee -a "$LOG_FILE"; }
warn() { echo -e "${YELLOW}⚠${NC} $*" | tee -a "$LOG_FILE"; }
err()  { echo -e "${RED}✗${NC} $*" | tee -a "$LOG_FILE"; }
die()  { err "$*"; exit 1; }

# ─── App-tier services only — the ONLY things blue/green ever touches ─
# (13 platform services + dashboard; ports here are container-internal,
# used only for the urlopen() probe in check_service_health, NOT host
# ports — those are bound to 127.0.0.1 per the master compose and are
# irrelevant to in-container health probing.)
declare -A SERVICE_PORTS=(
    [auth_service]=8001
    [market_data_service]=8002
    [broker_service]=8003
    [strategy_service]=8004
    [regime_detection_service]=8005
    [execution_orchestrator_service]=8006
    [risk_engine_service]=8007
    [execution_engine_service]=8008
    [portfolio_management_service]=8009
    [backtesting_engine_service]=8010
    [ml_platform_service]=8011
    [ai_analyst_service]=8012
    [signal_aggregation_service]=8013
    [dashboard]=3000
)
APP_SERVICES=("${!SERVICE_PORTS[@]}")

# ─── Determine current/next slot ─────────────────────────────────
get_current_slot() {
    if [[ -f "$SLOT_FILE" ]]; then cat "$SLOT_FILE"; else echo "blue"; fi
}

get_next_slot() {
    local current; current="$(get_current_slot)"
    if [[ "$current" == "blue" ]]; then echo "green"; else echo "blue"; fi
}

CURRENT_SLOT="$(get_current_slot)"
NEXT_SLOT="$(get_next_slot)"
CURRENT_PROJECT="sg_${CURRENT_SLOT}"
NEXT_PROJECT="sg_${NEXT_SLOT}"

# ─── Health check ────────────────────────────────────────────────
# No service image ships curl (verified against every Dockerfile in the
# repo). Try python3 (present in all 13 platform-service images) first,
# fall back to wget (present in the dashboard's node:alpine image), then
# curl as a last resort in case a future image adds it.
check_service_health() {
    local project="$1" service="$2" port="$3"
    local max_attempts=30 attempt=0
    local probe="python3 -c \"import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://localhost:${port}/health', timeout=3).status==200 else 1)\" \
                 || wget -q -T 3 -O /dev/null http://localhost:${port}/ \
                 || curl -sf --max-time 3 http://localhost:${port}/health >/dev/null"

    while [[ $attempt -lt $max_attempts ]]; do
        if docker compose -p "$project" -f "$COMPOSE_FILE" \
            exec -T "$service" sh -c "$probe" &>/dev/null; then
            ok "$service healthy"
            return 0
        fi
        attempt=$((attempt + 1))
        sleep 2
    done
    err "$service failed health check after ${max_attempts} attempts"
    return 1
}

check_all_healthy() {
    local project="$1"
    local failed=0
    for service in "${APP_SERVICES[@]}"; do
        if ! check_service_health "$project" "$service" "${SERVICE_PORTS[$service]}"; then
            failed=$((failed + 1))
        fi
    done
    return $failed
}

# ─── Nginx slot switch ────────────────────────────────────────────
switch_nginx_to_slot() {
    local slot="$1"
    log "Switching nginx upstreams to $slot slot..."
    local upstreams_conf="$ROOT_DIR/docker/nginx/conf.d/00-upstreams.conf"
    cat > "$upstreams_conf" << EOF
# ═══════════════════════════════════════════════════════════════════════
# AUTO-GENERATED by scripts/blue_green_deploy.sh — DO NOT EDIT BY HAND.
# Active slot: $slot ($(date -u +%Y-%m-%dT%H:%M:%SZ))
# ═══════════════════════════════════════════════════════════════════════

upstream dashboard     { server sg_${slot}_dashboard:3000; }
upstream portfolio_svc { server sg_${slot}_portfolio_management_service:8009; }
upstream risk_svc      { server sg_${slot}_risk_engine_service:8007; }
upstream execution_svc { server sg_${slot}_execution_engine_service:8008; }

# Singleton infra — same regardless of which slot is live.
upstream grafana { server grafana:3000; }
upstream mlflow  { server mlflow:5000; }
EOF
    # nginx itself is singleton — find whichever project is actually
    # running it rather than assuming CURRENT_PROJECT (nginx is created
    # once, by whichever slot ran `./sg up` first, and stays there).
    local nginx_project
    nginx_project="$(docker inspect sg_nginx --format '{{ index .Config.Labels "com.docker.compose.project" }}' 2>/dev/null || echo "$CURRENT_PROJECT")"
    docker compose -p "$nginx_project" -f "$COMPOSE_FILE" \
        exec -T nginx nginx -s reload 2>/dev/null \
        || docker exec sg_nginx nginx -s reload 2>/dev/null \
        || warn "Could not reload nginx — check it's running (./sg ps)"
    ok "Nginx pointing to $slot"
}

# ─── Subcommands ─────────────────────────────────────────────────
cmd_status() {
    echo ""
    echo -e "${BOLD}═══ SG Trading — Deployment Status ═══${NC}"
    echo -e "  Live slot:     ${GREEN}${CURRENT_SLOT}${NC} (project: ${CURRENT_PROJECT})"
    echo -e "  Standby slot:  ${YELLOW}${NEXT_SLOT}${NC} (project: ${NEXT_PROJECT})"
    echo ""
    echo -e "${BOLD}Running app-tier containers (live):${NC}"
    docker compose -p "$CURRENT_PROJECT" -f "$COMPOSE_FILE" ps "${APP_SERVICES[@]}" 2>/dev/null || echo "  (none)"
    echo ""
    echo -e "${BOLD}Shared infra (singleton — owned by whichever slot started it first):${NC}"
    docker ps --filter "name=sg_postgres" --filter "name=sg_redis" --filter "name=sg_mlflow" --filter "name=sg_nginx" \
        --format "  {{.Names}}: {{.Status}}" 2>/dev/null || echo "  (none)"
    echo ""
}

cmd_rollback() {
    if [[ ! -f "$ROLLBACK_FILE" ]]; then
        die "No rollback target recorded. Cannot roll back."
    fi
    local rollback_slot; rollback_slot="$(cat "$ROLLBACK_FILE")"
    warn "Rolling back from $CURRENT_SLOT → $rollback_slot"

    # Start previous slot's app services if not running (infra untouched).
    docker compose -p "sg_${rollback_slot}" -f "$COMPOSE_FILE" \
        --env-file "$ENV_FILE" up -d --no-build "${APP_SERVICES[@]}" 2>/dev/null || true

    switch_nginx_to_slot "$rollback_slot"

    echo "$rollback_slot" > "$SLOT_FILE"
    echo "$CURRENT_SLOT" > "$ROLLBACK_FILE"

    ok "Rollback complete → now on $rollback_slot"
    log "Stopping failed slot $CURRENT_SLOT's app services in background..."
    nohup docker compose -p "${CURRENT_PROJECT}" -f "$COMPOSE_FILE" \
        stop "${APP_SERVICES[@]}" &>/dev/null &
}

cmd_deploy() {
    local target_service="${1:-}"
    local -a deploy_targets

    if [[ -n "$target_service" ]]; then
        deploy_targets=("$target_service")
    else
        deploy_targets=("${APP_SERVICES[@]}")
    fi

    log "═══ SG Trading Blue-Green Deploy ═══"
    log "Current: ${CURRENT_SLOT} → Deploying to: ${NEXT_SLOT}"
    [[ -n "$target_service" ]] && log "Target service: $target_service"

    # ── 1. Build new images (app tier only) ────────────────────────
    log "Building images..."
    docker compose -p "$NEXT_PROJECT" -f "$COMPOSE_FILE" \
        --env-file "$ENV_FILE" build --parallel "${deploy_targets[@]}"
    ok "Build complete"

    # ── 2. Start new slot (app tier only — infra is shared/untouched) ─
    log "Starting $NEXT_SLOT slot..."
    docker compose -p "$NEXT_PROJECT" -f "$COMPOSE_FILE" \
        --env-file "$ENV_FILE" up -d "${deploy_targets[@]}"
    ok "$NEXT_SLOT slot started"

    # ── 3. Health check ──────────────────────────────────────────
    log "Running health checks on $NEXT_SLOT..."
    if [[ -n "$target_service" ]]; then
        if ! check_service_health "$NEXT_PROJECT" "$target_service" "${SERVICE_PORTS[$target_service]}"; then
            err "Health check failed on $NEXT_SLOT/$target_service"
            die "Deploy aborted. $CURRENT_SLOT is still live."
        fi
    elif ! check_all_healthy "$NEXT_PROJECT"; then
        err "Health checks failed on $NEXT_SLOT"
        log "Rolling back — $CURRENT_SLOT remains live"
        docker compose -p "$NEXT_PROJECT" -f "$COMPOSE_FILE" stop "${APP_SERVICES[@]}"
        die "Deploy aborted. $CURRENT_SLOT is still live."
    fi
    ok "All health checks passed"

    # ── 4. Switch traffic ────────────────────────────────────────
    switch_nginx_to_slot "$NEXT_SLOT"

    # ── 5. Record new state ──────────────────────────────────────
    echo "$CURRENT_SLOT" > "$ROLLBACK_FILE"
    echo "$NEXT_SLOT"    > "$SLOT_FILE"
    ok "State recorded: live=$NEXT_SLOT, rollback=$CURRENT_SLOT"

    # ── 6. Drain old slot (60s window) ───────────────────────────
    log "Old slot $CURRENT_SLOT's app services kept for 60s (instant rollback window)..."
    log "Run './scripts/blue_green_deploy.sh --rollback' within 60s to revert"
    sleep 60

    log "Stopping old slot $CURRENT_SLOT's app services..."
    docker compose -p "$CURRENT_PROJECT" -f "$COMPOSE_FILE" \
        stop "${APP_SERVICES[@]}" &>/dev/null &

    echo ""
    ok "═══ Deploy complete ═══"
    ok "Live: ${NEXT_SLOT} | Last deploy: $(date '+%Y-%m-%d %H:%M:%S')"
    log "To rollback: ./scripts/blue_green_deploy.sh --rollback"
}

# ─── Entry point ─────────────────────────────────────────────────
case "${1:-deploy}" in
    --status)   cmd_status ;;
    --rollback) cmd_rollback ;;
    --help|-h)
        echo "Usage: $0 [--status|--rollback|SERVICE_NAME]"
        echo "  (no args)          Deploy all app services"
        echo "  SERVICE_NAME       Deploy single service (e.g. auth_service)"
        echo "  --rollback         Revert to previous slot"
        echo "  --status           Show current deployment state"
        ;;
    *)          cmd_deploy "${1:-}" ;;
esac
