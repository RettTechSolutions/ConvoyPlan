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
# Writes the new compose file back to the host so the stack definition stays
# current and the next updater container starts with up-to-date env vars.
#
# Path 1 (preferred): /stack/docker-compose.yml is a RW bind-mount of the host
# file — just write to it. Path 2 (fallback): spawn a sidecar container that
# bind-mounts STACK_FILE_PATH from the host RW and pipes the new content in.
#
# Note: `docker cp $self:/tmp/foo $HOST_PATH` does NOT work here, because the
# docker CLI interprets the destination in the CLIENT filesystem (= inside this
# container), and the host path doesn't exist there.
_update_stack_file() {
    [ -z "${STACK_FILE_PATH:-}" ] && return 0

    local tmp=/tmp/dc-new.yml
    if ! curl -sf --max-time 15 "${REPO_RAW}/docker-compose.yml" -o "${tmp}" || [ ! -s "${tmp}" ]; then
        log "WARNUNG: Neue Stack-Datei konnte nicht heruntergeladen werden — übersprungen"
        rm -f "${tmp}"
        return 0
    fi

    if [ -w /stack/docker-compose.yml ] && cp "${tmp}" /stack/docker-compose.yml 2>/dev/null; then
        log "Stack-Datei aktualisiert: ${STACK_FILE_PATH}"
    elif docker run --rm -i -v "${STACK_FILE_PATH}:/dst" alpine sh -c 'cat > /dst' < "${tmp}" >/dev/null 2>&1; then
        log "Stack-Datei aktualisiert (via Sidecar): ${STACK_FILE_PATH}"
    else
        log "WARNUNG: Stack-Datei konnte nicht auf den Host geschrieben werden (STACK_FILE_PATH=${STACK_FILE_PATH})"
    fi
    rm -f "${tmp}"
}

# ── Spawn detached helper to recreate the updater container ──────────────────
# Runs a short-lived sidecar that waits briefly (so this container has time to
# exit cleanly), then runs `docker compose up -d --force-recreate updater`.
# Because the helper has its own lifecycle independent of this dying container,
# the recreate completes successfully even though the orchestrating CLI's
# original parent is gone.
_spawn_restart_helper() {
    [ -z "${STACK_FILE_PATH:-}" ] && {
        log "WARNUNG: STACK_FILE_PATH leer — Restart-Helper benötigt Host-Pfad zur Compose-Datei"
        return 1
    }

    # Forward the current environment so `docker compose` can interpolate all
    # ${VAR} references in the compose file (same vars this updater has).
    local env_file=/tmp/updater-restart-env
    env | grep -Ev '^(_|PATH|PWD|SHLVL|HOSTNAME|HOME|OLDPWD)=' > "${env_file}"

    docker run -d --rm \
        --name "${COMPOSE_PROJECT}-updater-restart-$(date +%s)" \
        -v /var/run/docker.sock:/var/run/docker.sock \
        -v "${STACK_FILE_PATH}:/compose.yml:ro" \
        --env-file "${env_file}" \
        docker:24-cli sh -c "
            sleep 3
            docker compose -p '${COMPOSE_PROJECT}' -f /compose.yml up -d --no-build --force-recreate updater
        " >/dev/null 2>&1
}

do_update() {
    log "Starte Image-Update…"

    # Pull ALL services including the updater itself, so future updater-image
    # fixes are picked up automatically. (A pull only downloads the image into
    # the local cache — it does NOT touch any running container, so pulling the
    # updater here is safe and won't kill us mid-update.)
    local all_services non_updater
    all_services=$(docker compose -p "${COMPOSE_PROJECT}" -f "${COMPOSE_FILE}" \
        config --services 2>/dev/null | tr '\n' ' ' \
        || echo "backend frontend caddy graphhopper db updater")
    # The recreate step still excludes the updater — that's done by the
    # detached restart helper at the end, to avoid self-kill mid-orchestration.
    non_updater=$(echo "${all_services}" | tr ' ' '\n' | grep -v '^updater$' | tr '\n' ' ')

    log "Pulling: ${all_services}"
    if docker compose -p "${COMPOSE_PROJECT}" -f "${COMPOSE_FILE}" pull ${all_services} 2>&1 | tee -a "${LOG_FILE}" && \
       docker compose -p "${COMPOSE_PROJECT}" -f "${COMPOSE_FILE}" up -d --no-build ${non_updater} 2>&1 | tee -a "${LOG_FILE}"; then
        sleep 5
        local new_sha
        new_sha=$(get_sha_from_backend)
        write_status "${new_sha}"
        log "Update complete. SHA: ${new_sha:-unknown}"

        # Update the host compose file so future runs use the latest stack definition
        _update_stack_file

        # Self-restart the updater so it picks up any new env vars or image from
        # the updated compose file. We CANNOT run `docker compose up -d updater`
        # directly from this container — the orchestrating CLI is killed when
        # `compose` stops the old (=this) container mid-sequence, leaving the new
        # container stuck in "Created" state. Spawn a detached helper container
        # instead; it survives this updater dying and finishes the recreate.
        log "Starte Updater-Container neu (neue Konfiguration übernehmen)…"
        _spawn_restart_helper || log "WARNUNG: Restart-Helper konnte nicht gestartet werden — Updater läuft weiter"
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
