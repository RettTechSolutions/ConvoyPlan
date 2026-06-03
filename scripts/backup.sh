#!/usr/bin/env bash
#
# ConvoyPlan backup — PostgreSQL dump + uploaded files + TLS material.
# Produces a timestamped folder under ./backups (configurable via BACKUP_DIR).
#
# Usage:   scripts/backup.sh
# Cron:    0 3 * * *  /opt/convoyplan/scripts/backup.sh >> /var/log/convoyplan-backup.log 2>&1
#
# Env overrides: COMPOSE_PROJECT_NAME, POSTGRES_USER, POSTGRES_DB, DB_CONTAINER,
#                BACKUP_DIR, BACKUP_RETENTION_DAYS
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(dirname "$SCRIPT_DIR")"

# Load .env (POSTGRES_*, COMPOSE_PROJECT_NAME) if present.
if [ -f "$ROOT_DIR/.env" ]; then
    set -a; . "$ROOT_DIR/.env"; set +a
fi

PROJECT="${COMPOSE_PROJECT_NAME:-convoyplan}"
PG_USER="${POSTGRES_USER:-convoyplan}"
PG_DB="${POSTGRES_DB:-convoyplan}"
DB_CONTAINER="${DB_CONTAINER:-${PROJECT}-db-1}"
BACKUP_DIR="${BACKUP_DIR:-$ROOT_DIR/backups}"
RETENTION_DAYS="${BACKUP_RETENTION_DAYS:-30}"

TS="$(date +%Y%m%d-%H%M%S)"
DEST="$BACKUP_DIR/$TS"
mkdir -p "$DEST"
echo "[backup] target: $DEST"

# 1) Database (compressed SQL, restorable with psql)
echo "[backup] dumping PostgreSQL from container '$DB_CONTAINER'…"
docker exec "$DB_CONTAINER" pg_dump -U "$PG_USER" -d "$PG_DB" --no-owner --clean --if-exists \
    | gzip > "$DEST/database.sql.gz"

# 2) Named volumes (uploaded branding logos + Caddy TLS material)
backup_volume() {
    local vol="$1" out="$2"
    if docker volume inspect "$vol" >/dev/null 2>&1; then
        echo "[backup] archiving volume $vol…"
        docker run --rm -v "$vol":/src:ro -v "$DEST":/backup alpine \
            tar czf "/backup/$out" -C /src . 2>/dev/null || true
    else
        echo "[backup] (skip) volume $vol not found"
    fi
}
backup_volume "${PROJECT}_logo_uploads" "uploads.tar.gz"
backup_volume "${PROJECT}_cert_uploads" "certs.tar.gz"

# 3) Keep the stack definition next to the data for reference
cp "$ROOT_DIR/docker-compose.yml" "$DEST/" 2>/dev/null || true

# 4) Integrity checksums
( cd "$DEST" && sha256sum ./* > SHA256SUMS 2>/dev/null || true )

# 5) Prune backups older than the retention window
if [ "$RETENTION_DAYS" -gt 0 ]; then
    find "$BACKUP_DIR" -maxdepth 1 -type d -name '20*' -mtime "+$RETENTION_DAYS" \
        -exec rm -rf {} + 2>/dev/null || true
fi

echo "[backup] done — $(du -sh "$DEST" | cut -f1)"
