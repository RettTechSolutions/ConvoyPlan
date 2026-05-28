#!/usr/bin/env bash
# Self-healing watchdog for the ConvoyPlan updater service.
#
# Installed by scripts/install.sh as a systemd timer (every ~2 min). Recovers
# the stack from:
#   - Orphan <hex>_<project>-updater-1 containers stuck in "Created" state
#     (left behind when an old broken updater self-restart raced)
#   - Main updater container missing, exited, or dead
#
# Safe to re-run; no-op when the updater is healthy.
# Argument 1: absolute path to the install directory (containing docker-compose.yml + .env)
set -euo pipefail

STACK_DIR="${1:-}"
[ -z "${STACK_DIR}" ] && { echo "FEHLER: STACK_DIR-Argument fehlt" >&2; exit 2; }
[ ! -f "${STACK_DIR}/docker-compose.yml" ] && { echo "FEHLER: keine docker-compose.yml in ${STACK_DIR}" >&2; exit 2; }

# Read COMPOSE_PROJECT_NAME from .env, fall back to the dir name (docker compose default)
PROJECT=""
if [ -f "${STACK_DIR}/.env" ]; then
    PROJECT=$(grep -m1 '^COMPOSE_PROJECT_NAME=' "${STACK_DIR}/.env" | cut -d= -f2-)
fi
PROJECT="${PROJECT:-$(basename "${STACK_DIR}")}"

# Clean up orphan hex-prefixed updater containers in Created state.
# Pattern: <12-hex>_<project>-updater-1 (Docker's rename-during-recreate format)
orphans=$(docker ps -a \
    --filter "name=^[0-9a-f]\{12\}_${PROJECT}-updater-1$" \
    --filter "status=created" \
    --format "{{.Names}}" 2>/dev/null || true)
for c in ${orphans}; do
    echo "Watchdog: räume Orphan-Container ${c} auf"
    docker rm "${c}" >/dev/null 2>&1 || true
done

# Also clean up orphan containers in "exited" state with the same hex pattern —
# leftovers from previous broken self-restart attempts.
exited_orphans=$(docker ps -a \
    --filter "name=^[0-9a-f]\{12\}_${PROJECT}-updater-1$" \
    --filter "status=exited" \
    --format "{{.Names}}" 2>/dev/null || true)
for c in ${exited_orphans}; do
    echo "Watchdog: räume gestoppten Orphan ${c} auf"
    docker rm "${c}" >/dev/null 2>&1 || true
done

# Ensure the main updater container exists and is running.
state=$(docker inspect "${PROJECT}-updater-1" --format '{{.State.Status}}' 2>/dev/null || echo "missing")
case "${state}" in
    running)
        exit 0
        ;;
    missing|created|exited|dead)
        echo "Watchdog: Updater-Container Status=${state} — starte neu"
        docker compose --project-directory "${STACK_DIR}" up -d updater
        ;;
    *)
        echo "Watchdog: unbekannter Status=${state} — keine Aktion"
        exit 0
        ;;
esac
