#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════════════════
# Kite Access Token Refresh
# Zerodha tokens expire at 6 AM daily.
# Run this before the trading day starts.
# ═══════════════════════════════════════════════════════════════════

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(dirname "$SCRIPT_DIR")"
ENV_FILE="$ROOT_DIR/.env"

set -a; source "$ENV_FILE"; set +a

GREEN='\033[0;32m'; RED='\033[0;31m'; NC='\033[0m'; BOLD='\033[1m'

log() { echo -e "${BOLD}[$(date '+%H:%M:%S')]${NC} $*"; }
ok()  { echo -e "${GREEN}✓${NC} $*"; }
err() { echo -e "${RED}✗${NC} $*"; }

[[ -z "${KITE_API_KEY:-}" ]]    && { err "KITE_API_KEY not set in .env"; exit 1; }
[[ -z "${KITE_API_SECRET:-}" ]] && { err "KITE_API_SECRET not set in .env"; exit 1; }

# ─── Get login URL and request token ────────────────────────────
log "Fetching Kite login URL..."
LOGIN_URL="https://kite.zerodha.com/connect/login?v=3&api_key=${KITE_API_KEY}"
echo ""
echo "Open this URL in your browser and login:"
echo "  $LOGIN_URL"
echo ""
echo "After login, you will be redirected to a URL like:"
echo "  http://127.0.0.1/?request_token=XXXXXXXX&action=login&status=success"
echo ""
read -rp "Paste the full redirect URL (or just the request_token value): " INPUT

# Extract request_token
if [[ "$INPUT" == *"request_token="* ]]; then
    REQUEST_TOKEN=$(echo "$INPUT" | sed 's/.*request_token=\([^&]*\).*/\1/')
else
    REQUEST_TOKEN="$INPUT"
fi

log "Exchanging request token for access token..."

# ─── Exchange for access token ───────────────────────────────────
CHECKSUM=$(echo -n "${KITE_API_KEY}${REQUEST_TOKEN}${KITE_API_SECRET}" \
    | sha256sum | cut -d' ' -f1)

RESPONSE=$(curl -sf -X POST "https://api.kite.trade/session/token" \
    -H "X-Kite-Version: 3" \
    -d "api_key=${KITE_API_KEY}" \
    -d "request_token=${REQUEST_TOKEN}" \
    -d "checksum=${CHECKSUM}")

ACCESS_TOKEN=$(echo "$RESPONSE" | python3 -c \
    "import sys,json; print(json.load(sys.stdin)['data']['access_token'])" 2>/dev/null)

[[ -z "$ACCESS_TOKEN" ]] && {
    err "Failed to get access token. Response: $RESPONSE"
    exit 1
}

# ─── Update .env ─────────────────────────────────────────────────
if grep -q "^KITE_ACCESS_TOKEN=" "$ENV_FILE"; then
    sed -i "s/^KITE_ACCESS_TOKEN=.*/KITE_ACCESS_TOKEN=${ACCESS_TOKEN}/" "$ENV_FILE"
else
    echo "KITE_ACCESS_TOKEN=${ACCESS_TOKEN}" >> "$ENV_FILE"
fi
ok "Access token saved to .env"

# ─── Restart affected services ───────────────────────────────────
log "Restarting market_data_service and broker_service..."
COMPOSE="docker compose -p sg_blue -f $ROOT_DIR/docker/docker-compose.yml --env-file $ENV_FILE"
$COMPOSE restart market_data_service broker_service

ok "Token refreshed. Services restarted."
log "Token expires at 6 AM tomorrow."
