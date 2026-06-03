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

if [ -f "$ROOT_DIR/.env" ]; then
    set -a; . "$ROOT_DIR/.env"; set +a
fi

PROJECT="${COMPOSE_PROJECT_NAME:-convoyplan}"
PG_USER="${POSTGRES_USER:-convoyplan}"
PG_DB="${POSTGRES_DB:-convoyplan}"
DB_CONTAINER="${DB_CONTAINER:-${PROJECT}-db-1}"

SRC="${1:-}"
if [ -z "$SRC" ] || [ ! -d "$SRC" ]; then
    echo "Usage: $0 <backup-folder>" >&2
    exit 1
fi

echo "WARNING: this overwrites the current database and uploaded files from:"
echo "         $SRC"
read -r -p "Type 'RESTORE' to continue: " confirm
[ "$confirm" = "RESTORE" ] || { echo "Aborted."; exit 1; }

# 1) Database
if [ -f "$SRC/database.sql.gz" ]; then
    echo "[restore] importing database…"
    gunzip -c "$SRC/database.sql.gz" | docker exec -i "$DB_CONTAINER" psql -U "$PG_USER" -d "$PG_DB"
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

echo "[restore] done — restart the stack:  docker compose restart backend caddy"
