#!/usr/bin/env bash
#
# ConvoyPlan restore — re-import a backup produced by scripts/backup.sh.
# DESTRUCTIVE: overwrites the current database and uploaded files.
#
# Usage:   scripts/restore.sh <backup-folder>
#   e.g.   scripts/restore.sh ./backups/20260603-030000
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(dirname "$SCRIPT_DIR")"

# Read a single KEY=value from .env WITHOUT sourcing it (avoids executing
# unquoted values like JAVA_OPTS=… and arbitrary code).
env_get() {
    [ -f "$ROOT_DIR/.env" ] || return 0
    sed -n "s/^$1=//p" "$ROOT_DIR/.env" | tail -n1
}

PROJECT="${COMPOSE_PROJECT_NAME:-$(env_get COMPOSE_PROJECT_NAME)}"; PROJECT="${PROJECT:-convoyplan}"
PG_USER="${POSTGRES_USER:-$(env_get POSTGRES_USER)}"; PG_USER="${PG_USER:-convoyplan}"
PG_DB="${POSTGRES_DB:-$(env_get POSTGRES_DB)}"; PG_DB="${PG_DB:-convoyplan}"
DB_CONTAINER="${DB_CONTAINER:-${PROJECT}-db-1}"
COMPOSE_FILE="$ROOT_DIR/docker-compose.yml"

SRC="${1:-}"
if [ -z "$SRC" ] || [ ! -d "$SRC" ]; then
    echo "Usage: $0 <backup-folder>" >&2
    exit 1
fi

echo "WARNING: this overwrites the current database and uploaded files from:"
echo "         $SRC"
read -r -p "Type 'RESTORE' to continue: " confirm
[ "$confirm" = "RESTORE" ] || { echo "Aborted."; exit 1; }

# Stop services that hold DB connections so --clean can drop/recreate cleanly
# and the backend never writes to a half-restored database.
stopped_services=""
if [ -f "$COMPOSE_FILE" ]; then
    echo "[restore] stopping backend/retention…"
    if docker compose -p "$PROJECT" -f "$COMPOSE_FILE" stop backend retention 2>/dev/null; then
        stopped_services=1
    fi
fi

restart_services() {
    if [ -n "$stopped_services" ]; then
        echo "[restore] restarting backend/retention…"
        docker compose -p "$PROJECT" -f "$COMPOSE_FILE" start backend retention 2>/dev/null || true
    fi
}
trap restart_services EXIT

# 1) Database — fail the whole import atomically on any SQL error. Without
# ON_ERROR_STOP/--single-transaction psql exits 0 even on a partial import,
# leaving a silently corrupt database.
if [ -f "$SRC/database.sql.gz" ]; then
    echo "[restore] importing database…"
    gunzip -c "$SRC/database.sql.gz" | docker exec -i "$DB_CONTAINER" \
        psql -v ON_ERROR_STOP=1 --single-transaction -U "$PG_USER" -d "$PG_DB"
else
    echo "[restore] (skip) database.sql.gz not found"
fi

# 2) Volumes
restore_volume() {
    local vol="$1" arc="$2"
    if [ ! -f "$SRC/$arc" ]; then
        echo "[restore] (skip) $arc not found"; return
    fi
    echo "[restore] restoring volume $vol…"
    docker run --rm -v "$vol":/dst -v "$(cd "$SRC" && pwd)":/backup alpine \
        sh -c "rm -rf /dst/* /dst/.[!.]* /dst/..?* 2>/dev/null; tar xzf /backup/$arc -C /dst"
}
restore_volume "${PROJECT}_logo_uploads" "uploads.tar.gz"
restore_volume "${PROJECT}_cert_uploads" "certs.tar.gz"

# Services are restarted by the EXIT trap. Caddy may need a reload to pick up
# restored TLS material.
echo "[restore] done — if TLS material changed, also run:  docker compose -p $PROJECT restart caddy"
