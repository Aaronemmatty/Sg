#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════════════════
# SG Trading Platform — Health Check Script
# ═══════════════════════════════════════════════════════════════════
# Usage:
#   ./scripts/health_check.sh           # check all services
#   ./scripts/health_check.sh --watch   # continuous monitoring
#   ./scripts/health_check.sh --json    # machine-readable output
#
# Runs from the HOST against the 127.0.0.1-bound ports the master compose
# publishes (see requirement #6) — this is why curl-from-host works fine
# here even though curl-from-inside-the-containers does not (see
# docs/DEPLOYMENT_NOTES.md "Healthcheck mechanism").

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(dirname "$SCRIPT_DIR")"

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
CYAN='\033[0;36m'; NC='\033[0m'; BOLD='\033[1m'; DIM='\033[2m'

JSON_MODE=false
WATCH_MODE=false

for arg in "$@"; do
    case $arg in
        --json)  JSON_MODE=true ;;
        --watch) WATCH_MODE=true ;;
    esac
done

declare -A SERVICES=(
    [auth_service]="8001"
    [market_data_service]="8002"
    [broker_service]="8003"
    [strategy_service]="8004"
    [regime_detection_service]="8005"
    [execution_orchestrator_service]="8006"
    [risk_engine_service]="8007"
    [execution_engine_service]="8008"
    [portfolio_management_service]="8009"
    [backtesting_engine_service]="8010"
    [ml_platform_service]="8011"
    [ai_analyst_service]="8012"
    [signal_aggregation_service]="8013"
)

declare -A SERVICE_LABELS=(
    [auth_service]="Auth Service"
    [market_data_service]="Market Data"
    [broker_service]="Broker Service"
    [strategy_service]="Strategy Service"
    [regime_detection_service]="Regime Detection"
    [execution_orchestrator_service]="Exec Orchestrator"
    [risk_engine_service]="Risk Engine"
    [execution_engine_service]="Execution Engine"
    [portfolio_management_service]="Portfolio Mgmt"
    [backtesting_engine_service]="Backtesting"
    [ml_platform_service]="ML Platform"
    [ai_analyst_service]="AI Analyst"
    [signal_aggregation_service]="Signal Aggregation"
)

# Note: dashboard has no host-published port (it's reached only through
# nginx — see docker-compose.yml), so it's checked via nginx instead.
check_service() {
    local name="$1"
    local port="$2"
    local url="http://127.0.0.1:${port}/health"
    local start_ms; start_ms=$(($(date +%s%N) / 1000000))

    local response
    if response=$(curl -sf --max-time 3 "$url" 2>/dev/null); then
        local end_ms; end_ms=$(($(date +%s%N) / 1000000))
        local latency_ms=$((end_ms - start_ms))
        local status; status=$(echo "$response" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('status','ok'))" 2>/dev/null || echo "ok")
        echo "ok|${latency_ms}|${status}"
    else
        echo "down|0|unreachable"
    fi
}

check_dashboard_via_nginx() {
    local start_ms; start_ms=$(($(date +%s%N) / 1000000))
    if curl -sf --max-time 3 "http://127.0.0.1/" -o /dev/null 2>/dev/null; then
        local end_ms; end_ms=$(($(date +%s%N) / 1000000))
        echo "ok|$((end_ms - start_ms))|ok"
    else
        echo "down|0|unreachable"
    fi
}

check_infra() {
    local name="$1"
    case "$name" in
        postgres)
            if docker exec sg_postgres pg_isready -U "${POSTGRES_USER:-sg_user}" -d "${POSTGRES_DB:-sg_db}" &>/dev/null; then
                echo "ok|0|healthy"
            else
                echo "down|0|unreachable"
            fi
            ;;
        redis)
            local pw; pw=$(grep REDIS_PASSWORD "$ROOT_DIR/.env" 2>/dev/null | cut -d= -f2 || echo "")
            if docker exec sg_redis redis-cli -a "$pw" --no-auth-warning ping &>/dev/null; then
                echo "ok|0|healthy"
            else
                echo "down|0|unreachable"
            fi
            ;;
        mlflow)
            if curl -sf --max-time 3 "http://127.0.0.1:5000/health" -o /dev/null 2>/dev/null; then
                echo "ok|0|healthy"
            else
                echo "down|0|unreachable"
            fi
            ;;
    esac
}

run_checks() {
    local all_healthy=true
    local json_entries=()
    local timestamp; timestamp=$(date -u +%Y-%m-%dT%H:%M:%SZ)

    if [[ "$JSON_MODE" == false ]]; then
        echo ""
        echo -e "${BOLD}═══ SG Trading Platform — Health Check ═══${NC}"
        echo -e "${DIM}$(date '+%Y-%m-%d %H:%M:%S')${NC}"
        echo ""
        echo -e "${BOLD}  Infrastructure${NC}"
    fi

    for infra in postgres redis mlflow; do
        local result; result=$(check_infra "$infra")
        local state; state=$(echo "$result" | cut -d'|' -f1)
        local label="${infra^}"
        if [[ "$state" == "ok" ]]; then
            [[ "$JSON_MODE" == false ]] && echo -e "    ${GREEN}●${NC} ${label}"
        else
            all_healthy=false
            [[ "$JSON_MODE" == false ]] && echo -e "    ${RED}●${NC} ${label} — DOWN"
        fi
        json_entries+=("{\"service\":\"$infra\",\"state\":\"$state\",\"type\":\"infra\"}")
    done

    [[ "$JSON_MODE" == false ]] && echo -e "\n${BOLD}  Platform Services${NC}"

    for name in auth_service market_data_service broker_service strategy_service \
                regime_detection_service execution_orchestrator_service risk_engine_service \
                execution_engine_service portfolio_management_service backtesting_engine_service \
                ml_platform_service ai_analyst_service signal_aggregation_service; do
        local port="${SERVICES[$name]}"
        local label="${SERVICE_LABELS[$name]}"
        local result; result=$(check_service "$name" "$port")
        local state; state=$(echo "$result" | cut -d'|' -f1)
        local latency; latency=$(echo "$result" | cut -d'|' -f2)

        if [[ "$JSON_MODE" == false ]]; then
            if [[ "$state" == "ok" ]]; then
                printf "    ${GREEN}●${NC} %-32s ${DIM}%sms${NC}\n" "$label" "$latency"
            else
                printf "    ${RED}●${NC} %-32s ${RED}DOWN${NC}\n" "$label"
            fi
        else
            json_entries+=("{\"service\":\"$name\",\"label\":\"$label\",\"state\":\"$state\",\"latency_ms\":$latency,\"port\":$port}")
        fi

        [[ "$state" != "ok" ]] && all_healthy=false
    done

    [[ "$JSON_MODE" == false ]] && echo -e "\n${BOLD}  Frontend${NC}"
    local dash_result; dash_result=$(check_dashboard_via_nginx)
    local dash_state; dash_state=$(echo "$dash_result" | cut -d'|' -f1)
    if [[ "$JSON_MODE" == false ]]; then
        if [[ "$dash_state" == "ok" ]]; then
            echo -e "    ${GREEN}●${NC} Dashboard (via nginx :80)"
        else
            echo -e "    ${RED}●${NC} Dashboard (via nginx :80) — DOWN"
        fi
    else
        json_entries+=("{\"service\":\"dashboard\",\"state\":\"$dash_state\",\"type\":\"frontend\"}")
    fi
    [[ "$dash_state" != "ok" ]] && all_healthy=false

    if [[ "$JSON_MODE" == true ]]; then
        local overall; overall=$([[ "$all_healthy" == true ]] && echo "healthy" || echo "degraded")
        echo "{"
        echo "  \"timestamp\": \"$timestamp\","
        echo "  \"overall\": \"$overall\","
        echo "  \"services\": [$(IFS=,; echo "${json_entries[*]}")]"
        echo "}"
    else
        echo ""
        if [[ "$all_healthy" == true ]]; then
            echo -e "  ${GREEN}${BOLD}All services healthy${NC}"
        else
            echo -e "  ${RED}${BOLD}Some services are DOWN — check logs${NC}"
            echo -e "  ${DIM}./sg logs <service>${NC}"
        fi
        echo ""
    fi

    [[ "$all_healthy" == true ]]
}

if [[ "$WATCH_MODE" == true ]]; then
    while true; do
        clear
        run_checks || true
        echo -e "${DIM}Refreshing every 5s — Ctrl+C to stop${NC}"
        sleep 5
    done
else
    run_checks
fi
