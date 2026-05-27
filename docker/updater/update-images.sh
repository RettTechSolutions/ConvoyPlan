#!/bin/bash
# Image-based updater — no git repo needed.
# Used by portainer-stack.yml deployments where images are pulled from GHCR.
#
# Required: Docker socket mounted at /var/run/docker.sock
# Required: update_status volume at /update_status
# Required: host compose file at /stack/docker-compose.yml (bind-mount it via STACK_FILE_PATH)
# Env: COMPOSE_PROJECT_NAME (default: convoyplan)
#      UPDATE_INTERVAL      (default: 300)
set -euo pipefail

INTERVAL="${UPDATE_INTERVAL:-300}"
TRIGGER_POLL=10           # check trigger file every 10s regardless of INTERVAL
COMPOSE_PROJECT="${COMPOSE_PROJECT_NAME:-convoyplan}"
COMPOSE_FILE="/stack/docker-compose.yml"

LOG_FILE=/update_status/update.log
log() {
    local msg="[$(date '+%Y-%m-%d %H:%M:%S')] $*"
    echo "$msg"
    echo "$msg" >> "${LOG_FILE}"
}

mkdir -p /update_status

# --- Sanity checks -----------------------------------------------------------

# Verify docker compose is available
if ! docker compose version >/dev/null 2>&1; then
    log "FEHLER: 'docker compose' nicht verfügbar. Updater kann nicht starten."
    exit 1
fi

# Verify compose file is a file, not a missing/empty directory
if [ ! -f "${COMPOSE_FILE}" ]; then
    log "FEHLER: ${COMPOSE_FILE} nicht gefunden oder ist kein reguläres File."
    log "        Setze STACK_FILE_PATH in deiner .env auf den absoluten Pfad"
    log "        zur docker-compose.yml auf dem HOST (z.B. /home/user/convoyplan/docker-compose.yml)."
    log "        Danach: docker compose restart updater"
    # Keep retrying so the container shows up as running (not crash-looping)
    while true; do
        sleep 60
        if [ -f "${COMPOSE_FILE}" ]; then
            log "Compose-Datei gefunden — starte Updater neu…"
            exec /bin/bash /update-images.sh
        fi
    done
fi

# -----------------------------------------------------------------------------

get_sha_from_backend() {
    local cid
    cid=$(docker ps -q \
        --filter "label=com.docker.compose.project=${COMPOSE_PROJECT}" \
        --filter "label=com.docker.compose.service=backend" | head -1)
    [ -z "${cid}" ] && { echo ""; return; }
    docker inspect "${cid}" --format '{{range .Config.Env}}{{println .}}{{end}}' 2>/dev/null \
        | grep '^GIT_SHA=' | cut -d= -f2 | head -1 || echo ""
}

write_status() {
    local sha="${1:-unknown}"
    printf '{"deployed_sha":"%s","deployed_at":"%s"}\n' \
        "${sha}" "$(date -u '+%Y-%m-%dT%H:%M:%SZ')" > /update_status/status.json
}

do_update() {
    # Note: backend already wrote the initial log line and cleared the file
    # before creating the trigger — we just append here.
    log "Starte Image-Update…"

    # Discover services, excluding the updater itself (to avoid self-kill)
    SERVICES=$(docker compose -p "${COMPOSE_PROJECT}" -f "${COMPOSE_FILE}" \
        config --services 2>/dev/null | grep -v '^updater$' | tr '\n' ' ' \
        || echo "backend frontend caddy graphhopper db")

    log "Pulling: ${SERVICES}"
    if docker compose -p "${COMPOSE_PROJECT}" -f "${COMPOSE_FILE}" pull ${SERVICES} 2>&1 | tee -a "${LOG_FILE}" && \
       docker compose -p "${COMPOSE_PROJECT}" -f "${COMPOSE_FILE}" up -d --no-build ${SERVICES} 2>&1 | tee -a "${LOG_FILE}"; then
        sleep 5
        local new_sha
        new_sha=$(get_sha_from_backend)
        write_status "${new_sha}"
        log "Update complete. SHA: ${new_sha:-unknown}"
    else
        log "Update failed — will retry on next trigger"
    fi
}

# Initial status
SHA=$(get_sha_from_backend)
write_status "${SHA}"
log "Image-updater gestartet (Projekt: ${COMPOSE_PROJECT}, Compose: ${COMPOSE_FILE}). Polling alle ${INTERVAL}s, Trigger-Check alle ${TRIGGER_POLL}s."

while true; do
    # Trigger check — runs every TRIGGER_POLL seconds so the UI reacts quickly
    if [ -f /update_status/trigger ]; then
        log "Trigger erkannt — starte Update"
        rm -f /update_status/trigger
        do_update
        continue
    fi

    # Sleep in short chunks so we notice a new trigger within TRIGGER_POLL seconds
    slept=0
    while [ "${slept}" -lt "${INTERVAL}" ]; do
        sleep "${TRIGGER_POLL}"
        slept=$((slept + TRIGGER_POLL))
        if [ -f /update_status/trigger ]; then
            break
        fi
    done
done
