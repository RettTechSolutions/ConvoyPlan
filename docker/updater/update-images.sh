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

LOG_FILE=/update_status/update.log
log() {
    local msg="[$(date '+%Y-%m-%d %H:%M:%S')] $*"
    echo "$msg"
    echo "$msg" >> "${LOG_FILE}"
}

mkdir -p /update_status
# The backend runs as non-root (appuser, uid 1001 — see backend/Dockerfile) and
# must be able to create the trigger file in this shared volume. The updater
# runs as root, so it owns the volume by default; hand it to the backend user.
# `-R` also repairs pre-existing root-owned volumes from before the backend was
# switched to non-root, so manual updates keep working after the upgrade.
chown -R 1001:1001 /update_status 2>/dev/null || true

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
# ── Release-Kanal (stable | beta) ─────────────────────────────────────────────
# Der Backend-Admin-Bereich schreibt den gewählten Kanal in eine geteilte Datei.
#   stable → deployt nur veröffentlichte Releases (Images :latest)
#   beta   → deployt jeden Commit auf main (Images :beta, gebaut von
#            .github/workflows/beta-images.yml auf jedem main-Push)
CHANNEL_FILE=/update_status/channel

read_channel() {
    local ch="stable"
    if [ -f "${CHANNEL_FILE}" ]; then
        ch="$(tr -d '[:space:]' < "${CHANNEL_FILE}" 2>/dev/null || echo stable)"
    fi
    case "${ch}" in
        beta) echo "beta" ;;
        *)    echo "stable" ;;
    esac
}

# Rewrite an image ref to the given tag (…:latest ⇄ …:beta).
_retag() {
    echo "${1%:*}:${2}"
}

# Export the *_IMAGE vars that docker-compose interpolates, so pull/up use the
# active channel's image tag. The exported values are also forwarded to the
# restart helper via its env-file, so a recreated updater keeps the channel.
_apply_channel_images() {
    local tag="latest"
    [ "$(read_channel)" = "beta" ] && tag="beta"
    export BACKEND_IMAGE="$(_retag "${BACKEND_IMAGE:-ghcr.io/retttechsolutions/convoyplan/backend:latest}" "${tag}")"
    export FRONTEND_IMAGE="$(_retag "${FRONTEND_IMAGE:-ghcr.io/retttechsolutions/convoyplan/frontend:latest}" "${tag}")"
    export GRAPHHOPPER_IMAGE="$(_retag "${GRAPHHOPPER_IMAGE:-ghcr.io/retttechsolutions/convoyplan/graphhopper:latest}" "${tag}")"
    export UPDATER_IMAGE="$(_retag "${UPDATER_IMAGE:-ghcr.io/retttechsolutions/convoyplan/updater:latest}" "${tag}")"
}

# Beta-Kanal-Ziel: Commit-SHA des letzten ERFOLGREICHEN :beta-Image-Builds.
# Bewusst NICHT der main-HEAD — der bewegt sich schon beim Merge, die Images
# existieren aber erst, wenn der beta-images-Workflow (~10-15 min) durch ist.
# Mit dem HEAD als Ziel würde der Updater alte :beta-Images ziehen und den
# neuen Stand fälschlich als deployt verbuchen.
# Leer = GitHub nicht erreichbar oder noch kein erfolgreicher Build.
_beta_built_sha() {
    local repo="${GITHUB_REPO:-RettTechSolutions/ConvoyPlan}"
    local url="https://api.github.com/repos/${repo}/actions/workflows/beta-images.yml/runs?branch=main&status=success&per_page=1&exclude_pull_requests=true"
    {
        if [ -n "${GITHUB_TOKEN:-}" ]; then
            curl -sf --max-time 15 -H "Authorization: Bearer ${GITHUB_TOKEN}" \
                "${url}" 2>/dev/null
        else
            curl -sf --max-time 15 "${url}" 2>/dev/null
        fi
    } | grep -m1 '"head_sha"' | cut -d'"' -f4 || true
}

# Ancestry zweier Refs laut GitHub-Compare-API: ahead|behind|identical|diverged.
# "ahead" = head enthält base und ist weiter. Leer = nicht ermittelbar.
_compare_status() {
    local repo="${GITHUB_REPO:-RettTechSolutions/ConvoyPlan}"
    local url="https://api.github.com/repos/${repo}/compare/${1}...${2}?per_page=1"
    {
        if [ -n "${GITHUB_TOKEN:-}" ]; then
            curl -sf --max-time 15 -H "Authorization: Bearer ${GITHUB_TOKEN}" \
                "${url}" 2>/dev/null
        else
            curl -sf --max-time 15 "${url}" 2>/dev/null
        fi
    } | grep -m1 '"status"' | cut -d'"' -f4 || true
}

# Resolve the latest *published release tag* (e.g. v1.0.1). On the stable
# channel the stack file is only ever fetched from a tagged release, never
# from a moving branch — so a push to `main` cannot rewrite the compose file
# (which the updater executes with the Docker socket) on customer instances.
# Only an explicit opt-in to the beta channel tracks main instead.
_latest_release_tag() {
    local repo="${GITHUB_REPO:-RettTechSolutions/ConvoyPlan}"
    # `|| true`: Bei GitHub-Ausfall (curl-Fehler) oder fehlendem Release (grep
    # ohne Treffer) darf der Pipeline-Fehlschlag das Skript unter
    # `set -euo pipefail` nicht beenden — leere Ausgabe heißt "unbekannt".
    {
        if [ -n "${GITHUB_TOKEN:-}" ]; then
            curl -sf --max-time 15 -H "Authorization: Bearer ${GITHUB_TOKEN}" \
                "https://api.github.com/repos/${repo}/releases/latest" 2>/dev/null
        else
            curl -sf --max-time 15 \
                "https://api.github.com/repos/${repo}/releases/latest" 2>/dev/null
        fi
    } | grep -m1 '"tag_name"' | cut -d'"' -f4 || true
}

# Set to 1 by _update_stack_file when the host compose file actually changed —
# do_update uses this to decide whether the updater container must restart.
STACK_FILE_CHANGED=0

_update_stack_file() {
    STACK_FILE_CHANGED=0
    [ -z "${STACK_FILE_PATH:-}" ] && return 0

    local repo="${GITHUB_REPO:-RettTechSolutions/ConvoyPlan}"
    # Stable: Compose-Datei vom Release-Tag. Beta: von main (explizites Opt-in).
    local ref
    if [ "$(read_channel)" = "beta" ]; then
        ref="main"
    else
        ref="$(_latest_release_tag)"
        if [ -z "${ref}" ]; then
            log "WARNUNG: neuesten Release-Tag nicht ermittelbar — Stack-Datei nicht aktualisiert"
            return 0
        fi
    fi

    local tmp=/tmp/dc-new.yml
    if ! curl -sf --max-time 15 "https://raw.githubusercontent.com/${repo}/${ref}/docker-compose.yml" -o "${tmp}" || [ ! -s "${tmp}" ]; then
        log "WARNUNG: Stack-Datei (${ref}) konnte nicht heruntergeladen werden — übersprungen"
        rm -f "${tmp}"
        return 0
    fi

    # Inhaltsgleich? Dann nichts schreiben und keinen Updater-Neustart auslösen.
    if cmp -s "${tmp}" "${COMPOSE_FILE}" 2>/dev/null; then
        rm -f "${tmp}"
        return 0
    fi

    if [ -w /stack/docker-compose.yml ] && cp "${tmp}" /stack/docker-compose.yml 2>/dev/null; then
        log "Stack-Datei aktualisiert: ${STACK_FILE_PATH}"
        STACK_FILE_CHANGED=1
    elif docker run --rm -i -v "${STACK_FILE_PATH}:/dst" alpine sh -c 'cat > /dst' < "${tmp}" >/dev/null 2>&1; then
        log "Stack-Datei aktualisiert (via Sidecar): ${STACK_FILE_PATH}"
        STACK_FILE_CHANGED=1
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
    # Write with a restrictive umask and delete it right after `docker run` has
    # read it, to minimise the window in which secrets sit on disk.
    local env_file=/tmp/updater-restart-env
    ( umask 077; env | grep -Ev '^(_|PATH|PWD|SHLVL|HOSTNAME|HOME|OLDPWD)=' > "${env_file}" )

    docker run -d --rm \
        --name "${COMPOSE_PROJECT}-updater-restart-$(date +%s)" \
        -v /var/run/docker.sock:/var/run/docker.sock \
        -v "${STACK_FILE_PATH}:/compose.yml:ro" \
        --env-file "${env_file}" \
        docker:24-cli sh -c "
            sleep 3
            docker compose -p '${COMPOSE_PROJECT}' -f /compose.yml up -d --no-build --force-recreate updater
        " >/dev/null 2>&1

    # The CLI has already loaded --env-file into the container config by now.
    rm -f "${env_file}"
}

do_update() {
    log "Starte Image-Update (Kanal: $(read_channel))…"

    # Image-Tags des aktiven Kanals exportieren (:latest bzw. :beta), damit
    # docker compose pull/up die richtigen Refs interpoliert.
    _apply_channel_images

    # Updater-Image-ID vor dem Pull merken: Der Restart-Helper am Ende läuft
    # nur, wenn sich das Updater-Image oder die Stack-Datei wirklich geändert
    # hat — sonst würde sich der Updater bei jedem Durchlauf selbst neu starten.
    local updater_image updater_id_before updater_id_after
    updater_image="${UPDATER_IMAGE}"
    updater_id_before=$(docker image inspect "${updater_image}" --format '{{.Id}}' 2>/dev/null || echo "")

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
        updater_id_after=$(docker image inspect "${updater_image}" --format '{{.Id}}' 2>/dev/null || echo "")
        if [ "${STACK_FILE_CHANGED}" = "1" ] || \
           { [ -n "${updater_id_after}" ] && [ "${updater_id_before}" != "${updater_id_after}" ]; }; then
            log "Starte Updater-Container neu (neue Konfiguration übernehmen)…"
            _spawn_restart_helper || log "WARNUNG: Restart-Helper konnte nicht gestartet werden — Updater läuft weiter"
        else
            log "Updater-Image und Stack-Datei unverändert — kein Updater-Neustart nötig."
        fi
        return 0
    else
        log "Update failed — will retry on next trigger"
        return 1
    fi
}

# Initial status
SHA=$(get_sha_from_backend)
write_status "${SHA}"
log "Image-updater gestartet (Projekt: ${COMPOSE_PROJECT}, Compose: ${COMPOSE_FILE}, Kanal: $(read_channel)). Ziel-Check alle ${INTERVAL}s, Trigger-Check alle ${TRIGGER_POLL}s."

# ── Periodischer Auto-Update-Check ────────────────────────────────────────────
# Update-Signal ist der Vergleich des Kanal-Ziels mit dem zuletzt deployten
# Stand — so entfallen periodische Registry-Pulls (Docker-Hub-Rate-Limits!)
# und es wird nur bei einer echten Änderung gezogen:
#   stable → neuester Release-Tag   (:latest wird nur vom Release-Workflow gebaut)
#   beta   → HEAD-Commit von main   (:beta wird bei jedem main-Push gebaut)
# Gespeichert wird "<kanal> <ref>" — dadurch löst auch ein Kanalwechsel im
# Admin-Panel beim nächsten Check automatisch ein Update auf das neue Ziel aus.
LAST_DEPLOYED_FILE=/update_status/last_deployed

# Echoes "stable <tag>" or "beta <sha>"; empty when GitHub is unreachable.
_current_target() {
    local ch ref
    ch="$(read_channel)"
    if [ "${ch}" = "beta" ]; then
        ref="$(_beta_built_sha)"
    else
        ref="$(_latest_release_tag)"
    fi
    if [ -n "${ref}" ]; then
        echo "${ch} ${ref}"
    fi
}

_remember_target() {
    local target
    target="$(_current_target)"
    if [ -n "${target}" ]; then
        echo "${target}" > "${LAST_DEPLOYED_FILE}"
    fi
}

check_target_and_update() {
    local target last ch ref
    target="$(_current_target)"
    if [ -z "${target}" ]; then
        return 0   # GitHub nicht erreichbar oder noch kein Release — später erneut
    fi
    last="$(cat "${LAST_DEPLOYED_FILE}" 2>/dev/null || true)"
    if [ "${target}" = "${last}" ]; then
        return 0   # nichts Neues
    fi

    # Kein automatisches DOWNGRADE im Stable-Kanal: Lief die Instanz vorher im
    # Beta-Kanal, ist der installierte Stand NEUER als das letzte Release —
    # automatisch aufs ältere Release zurückzugehen wäre riskant (bereits
    # angewendete DB-Migrationen!). Stable greift dann erst wieder, wenn das
    # nächste Release den installierten Stand überholt. Der manuelle Trigger
    # ("Jetzt updaten") erzwingt das Downgrade weiterhin bewusst.
    ch="${target%% *}"
    ref="${target#* }"
    if [ "${ch}" = "stable" ]; then
        local deployed cmp
        deployed="$(get_sha_from_backend)"
        if [ -n "${deployed}" ]; then
            cmp="$(_compare_status "${ref}" "${deployed}")"
            if [ "${cmp}" = "ahead" ] || [ "${cmp}" = "identical" ]; then
                log "Installierter Stand (${deployed:0:7}) ist bereits ${ref} oder neuer (${cmp}) — kein automatisches Downgrade."
                echo "${target}" > "${LAST_DEPLOYED_FILE}"
                return 0
            fi
        fi
    fi

    log "Neues Update-Ziel: ${target} (zuletzt deployt: ${last:-unbekannt}) — starte automatisches Update"
    if do_update; then
        echo "${target}" > "${LAST_DEPLOYED_FILE}"
    fi
}

while true; do
    # Trigger check — runs every TRIGGER_POLL seconds so the UI reacts quickly
    if [ -f /update_status/trigger ]; then
        log "Trigger erkannt — starte Update"
        rm -f /update_status/trigger
        if do_update; then
            _remember_target
        fi
        continue
    fi

    # Automatic update when the channel's target (release tag / main HEAD) moved
    check_target_and_update

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
