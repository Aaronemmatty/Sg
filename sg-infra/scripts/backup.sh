#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════════════════
# SG Trading Platform — Backup Script
# ═══════════════════════════════════════════════════════════════════
# Usage:
#   ./scripts/backup.sh                   # full backup
#   ./scripts/backup.sh --postgres-only   # DB only
#   ./scripts/backup.sh --restore <file>  # restore from backup
#
# Backups saved to: ./backups/YYYY-MM-DD_HHMMSS/
# Retention: last 7 daily + last 4 weekly backups kept
# ═══════════════════════════════════════════════════════════════════

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(dirname "$SCRIPT_DIR")"
BACKUP_DIR="$ROOT_DIR/backups"
TIMESTAMP=$(date '+%Y-%m-%d_%H%M%S')
BACKUP_PATH="$BACKUP_DIR/$TIMESTAMP"
ENV_FILE="$ROOT_DIR/.env"

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'; BOLD='\033[1m'

log()  { echo -e "${BOLD}[$(date '+%H:%M:%S')]${NC} $*"; }
ok()   { echo -e "${GREEN}✓${NC} $*"; }
warn() { echo -e "${YELLOW}⚠${NC} $*"; }
err()  { echo -e "${RED}✗${NC} $*"; }
die()  { err "$*"; exit 1; }

# Load env
if [[ -f "$ENV_FILE" ]]; then
    set -a; source "$ENV_FILE"; set +a
else
    die ".env file not found at $ENV_FILE"
fi

POSTGRES_USER="${POSTGRES_USER:-sg_user}"
POSTGRES_DB="${POSTGRES_DB:-sg_db}"
POSTGRES_PASSWORD="${POSTGRES_PASSWORD:-}"
REDIS_PASSWORD="${REDIS_PASSWORD:-}"

# ─── Postgres backup ─────────────────────────────────────────────
backup_postgres() {
    log "Backing up PostgreSQL..."
    mkdir -p "$BACKUP_PATH/postgres"

    local dump_file="$BACKUP_PATH/postgres/sg_db_${TIMESTAMP}.sql.gz"

    docker exec sg_postgres pg_dump \
        -U "$POSTGRES_USER" \
        -d "$POSTGRES_DB" \
        --no-password \
        --verbose \
        --format=custom \
        | gzip > "$dump_file"

    local size; size=$(du -sh "$dump_file" | cut -f1)
    ok "PostgreSQL backup: $dump_file ($size)"

    # Also dump schema only for reference
    docker exec sg_postgres pg_dump \
        -U "$POSTGRES_USER" \
        -d "$POSTGRES_DB" \
        --schema-only \
        | gzip > "$BACKUP_PATH/postgres/schema_${TIMESTAMP}.sql.gz"
    ok "Schema backup saved"
}

# ─── Redis backup ────────────────────────────────────────────────
backup_redis() {
    log "Backing up Redis..."
    mkdir -p "$BACKUP_PATH/redis"

    # Trigger BGSAVE and wait
    docker exec sg_redis redis-cli -a "$REDIS_PASSWORD" BGSAVE
    sleep 3

    # Copy the RDB file out of container
    docker cp sg_redis:/data/dump.rdb "$BACKUP_PATH/redis/dump_${TIMESTAMP}.rdb"
    gzip "$BACKUP_PATH/redis/dump_${TIMESTAMP}.rdb"

    local size; size=$(du -sh "$BACKUP_PATH/redis/dump_${TIMESTAMP}.rdb.gz" | cut -f1)
    ok "Redis backup: $BACKUP_PATH/redis/dump_${TIMESTAMP}.rdb.gz ($size)"
}

# ─── MLflow artifacts backup ─────────────────────────────────────
backup_mlflow() {
    log "Backing up MLflow artifacts..."
    mkdir -p "$BACKUP_PATH/mlflow"

    docker run --rm \
        -v sg_mlflow_data:/source:ro \
        -v "$BACKUP_PATH/mlflow":/dest \
        alpine sh -c "cd /source && tar czf /dest/mlflow_${TIMESTAMP}.tar.gz ."

    local size; size=$(du -sh "$BACKUP_PATH/mlflow/mlflow_${TIMESTAMP}.tar.gz" | cut -f1)
    ok "MLflow backup: $size"
}

# ─── Metadata manifest ───────────────────────────────────────────
write_manifest() {
    cat > "$BACKUP_PATH/manifest.json" << EOF
{
  "timestamp": "$TIMESTAMP",
  "created_at": "$(date -u +%Y-%m-%dT%H:%M:%SZ)",
  "platform_version": "${VERSION:-unknown}",
  "postgres_db": "$POSTGRES_DB",
  "contents": ["postgres", "redis", "mlflow"],
  "restore_command": "bash scripts/backup.sh --restore $BACKUP_PATH"
}
EOF
    ok "Manifest written"
}

# ─── Retention policy ────────────────────────────────────────────
apply_retention() {
    log "Applying retention policy (keep 7 daily, 4 weekly)..."
    local backups=()
    while IFS= read -r -d '' dir; do
        backups+=("$dir")
    done < <(find "$BACKUP_DIR" -maxdepth 1 -mindepth 1 -type d -print0 | sort -z)

    local count=${#backups[@]}
    local keep=7

    if [[ $count -gt $keep ]]; then
        local to_delete=$(( count - keep ))
        for (( i=0; i<to_delete; i++ )); do
            warn "Removing old backup: ${backups[$i]}"
            rm -rf "${backups[$i]}"
        done
    fi
    ok "Retention applied — ${count} → $(( count > keep ? keep : count )) backups kept"
}

# ─── Restore ─────────────────────────────────────────────────────
restore_backup() {
    local backup_path="$1"
    [[ -d "$backup_path" ]] || die "Backup directory not found: $backup_path"
    [[ -f "$backup_path/manifest.json" ]] || die "Not a valid backup directory (no manifest.json)"

    warn "⚠ RESTORE WILL OVERWRITE CURRENT DATA ⚠"
    read -rp "Type YES to confirm: " confirm
    [[ "$confirm" == "YES" ]] || die "Restore cancelled"

    log "Restoring from $backup_path..."

    # Restore PostgreSQL
    if [[ -d "$backup_path/postgres" ]]; then
        log "Restoring PostgreSQL..."
        local dump; dump=$(find "$backup_path/postgres" -name "sg_db_*.sql.gz" | head -1)
        [[ -n "$dump" ]] || die "No postgres dump found"

        gunzip -c "$dump" | docker exec -i sg_postgres pg_restore \
            -U "$POSTGRES_USER" \
            -d "$POSTGRES_DB" \
            --clean --if-exists \
            --no-password \
            --verbose
        ok "PostgreSQL restored"
    fi

    # Restore Redis
    if [[ -d "$backup_path/redis" ]]; then
        log "Restoring Redis..."
        local rdb; rdb=$(find "$backup_path/redis" -name "dump_*.rdb.gz" | head -1)
        if [[ -n "$rdb" ]]; then
            # Stop redis, replace rdb, restart
            docker stop sg_redis
            gunzip -c "$rdb" | docker cp /dev/stdin sg_redis:/data/dump.rdb
            docker start sg_redis
            sleep 3
            ok "Redis restored"
        fi
    fi

    # Restore MLflow
    if [[ -d "$backup_path/mlflow" ]]; then
        log "Restoring MLflow artifacts..."
        local tar; tar=$(find "$backup_path/mlflow" -name "mlflow_*.tar.gz" | head -1)
        if [[ -n "$tar" ]]; then
            docker run --rm \
                -v sg_mlflow_data:/dest \
                -v "$(dirname "$tar")":/source:ro \
                alpine sh -c "cd /dest && tar xzf /source/$(basename "$tar")"
            ok "MLflow restored"
        fi
    fi

    ok "Restore complete from $backup_path"
}

# ─── Entry point ─────────────────────────────────────────────────
case "${1:-full}" in
    --restore)
        [[ -n "${2:-}" ]] || die "Usage: $0 --restore <backup_path>"
        restore_backup "$2"
        ;;
    --postgres-only)
        mkdir -p "$BACKUP_PATH"
        backup_postgres
        write_manifest
        ;;
    full|"")
        log "═══ Full Backup — $TIMESTAMP ═══"
        mkdir -p "$BACKUP_PATH"
        backup_postgres
        backup_redis
        backup_mlflow
        write_manifest
        apply_retention
        echo ""
        ok "═══ Backup complete: $BACKUP_PATH ═══"
        du -sh "$BACKUP_PATH"
        ;;
    *)
        die "Unknown command: $1. Use: full | --postgres-only | --restore <path>"
        ;;
esac
