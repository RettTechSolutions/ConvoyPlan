#!/bin/bash
# Image-based updater — no git repo needed.
# Used by stack.yml deployments where images are pulled from GHCR.
#
# Required: Docker socket mounted at /var/run/docker.sock
# Required: update_status volume at /update_status
# Optional: host compose file at /stack/docker-compose.yml (bind-mount via STACK_FILE_PATH)
#           If not mounted, the updater self-discovers the path from Docker project labels.
# Env: COMPOSE_PROJECT_NAME (default: convoyplan)
#      STACK_FILE_PATH       (host path to docker-compose.yml — auto-detected if missing)
#      UPDATE_INTERVAL      (default: 300)
set -euo pipefail

INTERVAL="${UPDATE_INTERVAL:-300}"
TRIGGER_POLL=10           # check trigger file every 10s regardless of INTERVAL
COMPOSE_PROJECT="${COMPOSE_PROJECT_NAME:-convoyplan}"
COMPOSE_FILE="/stack/docker-compose.yml"

REPO_RAW="https://raw.githubusercontent.com/RettTechSolutions/ConvoyPlan/main"

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

# ── Self-healing: discover STACK_FILE_PATH from Docker project labels ────────
# This handles installations where STACK_FILE_PATH was never set in .env,
# or where /stack/docker-compose.yml is empty/a-directory (old install bug).

_resolve_compose_file() {
    # Step 1: Always ensure STACK_FILE_PATH is exported — docker compose needs it
    # for variable interpolation when reading the compose file during pull/up,
    # even if the file is already properly mounted.
    if [ -z "${STACK_FILE_PATH:-}" ]; then
        local container_id discovered
        container_id=$(docker ps -q \
            --filter "label=com.docker.compose.project=${COMPOSE_PROJECT}" 2>/dev/null | head -1)
        if [ -n "${container_id}" ]; then
            discovered=$(docker inspect "${container_id}" \
                --format '{{index .Config.Labels "com.docker.compose.project.config_files"}}' \
                2>/dev/null | cut -d',' -f1 | tr -d ' ')
            if [ -n "${discovered}" ]; then
                export STACK_FILE_PATH="${discovered}"
                log "INFO: STACK_FILE_PATH auto-ermittelt: ${STACK_FILE_PATH}"
            fi
        fi
    fi

    # Step 2: If mounted file is a valid, non-empty file → done
    if [ -f "${COMPOSE_FILE}" ] && [ -s "${COMPOSE_FILE}" ]; then
        return 0
    fi

    log "INFO: ${COMPOSE_FILE} fehlt oder ist leer — lade Compose-Datei vom Host…"

    # Step 3: Copy compose file from HOST into this container via docker cp
    if [ -n "${STACK_FILE_PATH:-}" ]; then
        local self_id
        self_id=$(hostname)  # container ID = hostname inside container
        if docker cp "${STACK_FILE_PATH}" "${self_id}:/stack/docker-compose.yml" 2>/dev/null; then
            log "INFO: Compose-Datei von ${STACK_FILE_PATH} in Container kopiert."
            return 0
        else
            log "WARNUNG: docker cp fehlgeschlagen — versuche Alternativmethode…"
            # Fallback: spawn a tiny container to read the file
            if docker run --rm -v "${STACK_FILE_PATH}:/src:ro" alpine cat /src \
                    > /tmp/docker-compose.yml 2>/dev/null && [ -s /tmp/docker-compose.yml ]; then
                COMPOSE_FILE=/tmp/docker-compose.yml
                log "INFO: Compose-Datei nach /tmp geladen."
                return 0
            fi
        fi
    fi

    log "FEHLER: Compose-Datei nicht verfügbar und STACK_FILE_PATH nicht ermittelbar."
    return 1
}

if ! _resolve_compose_file; then
    log "FEHLER: Compose-Datei nicht verfügbar."
    log "        Abhilfe: install.sh/install.ps1 erneut ausführen."
    log "        Warte auf Selbstheilung (retry alle 60 s)…"
    while true; do
        sleep 60
        if _resolve_compose_file 2>/dev/null; then
            log "Compose-Datei jetzt verfügbar — starte Updater neu…"
            exec /bin/bash /update-images.sh
        fi
    done
fi

# Ensure STACK_FILE_PATH is exported for docker compose variable interpolation
# (needed so ${STACK_FILE_PATH} in stack.yml can be resolved)
if [ -z "${STACK_FILE_PATH:-}" ]; then
    export STACK_FILE_PATH="${STACK_FILE_PATH:-}"  # may still be empty for /dev/null mounts
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

# ── Update the host compose file from the repo ───────────────────────────────
# Uses docker cp to write from this container's /tmp back to the host path.
# This ensures the stack definition stays current even without manual re-installs,
# and that the next updater container starts with up-to-date env vars.
_update_stack_file() {
    [ -z "${STACK_FILE_PATH:-}" ] && return 0

    local tmp=/tmp/dc-new.yml
    if curl -sf --max-time 15 "${REPO_RAW}/docker-compose.yml" -o "${tmp}" && [ -s "${tmp}" ]; then
        local self_id
        self_id=$(hostname)
        if docker cp "${self_id}:${tmp}" "${STACK_FILE_PATH}" 2>/dev/null; then
            log "Stack-Datei aktualisiert: ${STACK_FILE_PATH}"
        else
            log "WARNUNG: Stack-Datei konnte nicht auf den Host geschrieben werden (STACK_FILE_PATH=${STACK_FILE_PATH})"
        fi
    else
        log "WARNUNG: Neue Stack-Datei konnte nicht heruntergeladen werden — übersprungen"
    fi
    rm -f /tmp/dc-new.yml
}

do_update() {
    log "Starte Image-Update…"

    # Discover services, excluding the updater itself (to avoid self-kill mid-update)
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

        # Update the host compose file so future runs use the latest stack definition
        _update_stack_file

        # Self-restart the updater so it picks up any new env vars or image from the
        # updated compose file. docker compose up -d will start a new container and
        # stop this one gracefully.
        log "Starte Updater-Container neu (neue Konfiguration übernehmen)…"
        docker compose -p "${COMPOSE_PROJECT}" -f "${COMPOSE_FILE}" up -d --no-build updater \
            2>&1 | tee -a "${LOG_FILE}" || log "WARNUNG: Updater-Neustart fehlgeschlagen — läuft weiter"
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
