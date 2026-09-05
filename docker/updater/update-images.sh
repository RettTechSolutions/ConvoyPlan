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

# Regionswechsel-Einhängung: gemeinsame Logik mit update.sh, siehe
# region-hook.sh (Begründung für die gemeinsame Datei dort). Dies ist der
# ENTRYPOINT, den docker-compose.yml für die Standard-Installation tatsächlich
# verwendet — ohne diesen Hook würde eine Regionswechsel-Anforderung nie
# abgeholt.
# shellcheck source=./region-hook.sh
source /region-hook.sh

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
# ── Release-Kanal (stable | beta | nightly) ───────────────────────────────────
# Der Backend-Admin-Bereich schreibt den gewählten Kanal in eine geteilte Datei.
#   stable  → deployt nur veröffentlichte Releases (Images :latest)
#   beta    → deployt nummerierte Prereleases / Release-Kandidaten
#             (Images :beta, gebaut von release.yml aus einem vX.Y.Z-beta.N-Tag)
#   nightly → deployt jeden Commit auf main (Images :nightly, gebaut von
#             .github/workflows/nightly-images.yml auf jedem main-Push)
CHANNEL_FILE=/update_status/channel

read_channel() {
    local ch="stable"
    if [ -f "${CHANNEL_FILE}" ]; then
        ch="$(tr -d '[:space:]' < "${CHANNEL_FILE}" 2>/dev/null || echo stable)"
    fi
    case "${ch}" in
        beta)    echo "beta" ;;
        nightly) echo "nightly" ;;
        *)       echo "stable" ;;
    esac
}

# ── Update-Modus (auto | notify) ──────────────────────────────────────────────
# Vom Backend geschrieben (Admin → Software-Update):
#   auto   → verfügbare Updates werden automatisch installiert (Standard)
#   notify → KEINE automatische Installation; das Backend benachrichtigt die
#            Superadmins per E-Mail, installiert wird nur über den manuellen
#            Trigger ("Jetzt updaten").
MODE_FILE=/update_status/mode

read_mode() {
    local m="auto"
    if [ -f "${MODE_FILE}" ]; then
        m="$(tr -d '[:space:]' < "${MODE_FILE}" 2>/dev/null || echo auto)"
    fi
    case "${m}" in
        notify) echo "notify" ;;
        *)      echo "auto" ;;
    esac
}

# Rewrite an image ref to the given tag (…:latest ⇄ …:beta ⇄ …:nightly).
_retag() {
    echo "${1%:*}:${2}"
}

# Map the active channel to its floating image tag.
_channel_tag() {
    case "$(read_channel)" in
        beta)    echo "beta" ;;
        nightly) echo "nightly" ;;
        *)       echo "latest" ;;
    esac
}

# Export the *_IMAGE vars that docker-compose interpolates, so pull/up use the
# active channel's image tag. The exported values are also forwarded to the
# restart helper via its env-file, so a recreated updater keeps the channel.
_apply_channel_images() {
    local tag
    tag="$(_channel_tag)"
    export BACKEND_IMAGE="$(_retag "${BACKEND_IMAGE:-ghcr.io/retttechsolutions/convoyplan/backend:latest}" "${tag}")"
    export FRONTEND_IMAGE="$(_retag "${FRONTEND_IMAGE:-ghcr.io/retttechsolutions/convoyplan/frontend:latest}" "${tag}")"
    export GRAPHHOPPER_IMAGE="$(_retag "${GRAPHHOPPER_IMAGE:-ghcr.io/retttechsolutions/convoyplan/graphhopper:latest}" "${tag}")"
    export UPDATER_IMAGE="$(_retag "${UPDATER_IMAGE:-ghcr.io/retttechsolutions/convoyplan/updater:latest}" "${tag}")"
    # Muss mit umgetaggt werden, obwohl es kein Stack-Dienst ist: Sonst liefe
    # eine auf eine Version gepinnte Installation beim Regionswechsel gegen ein
    # beliebig neueres osmium:latest.
    export REGION_MERGE_IMAGE="$(_retag "${REGION_MERGE_IMAGE:-ghcr.io/retttechsolutions/convoyplan/osmium:latest}" "${tag}")"
}

# Nightly-Kanal-Ziel: Commit-SHA des letzten ERFOLGREICHEN :nightly-Image-Builds.
# Bewusst NICHT der main-HEAD — der bewegt sich schon beim Merge, die Images
# existieren aber erst, wenn der nightly-images-Workflow (~10-15 min) durch ist.
# Mit dem HEAD als Ziel würde der Updater alte :nightly-Images ziehen und den
# neuen Stand fälschlich als deployt verbuchen.
# Leer = GitHub nicht erreichbar oder noch kein erfolgreicher Build.
_nightly_built_sha() {
    local repo="${GITHUB_REPO:-RettTechSolutions/ConvoyPlan}"
    local url="https://api.github.com/repos/${repo}/actions/workflows/nightly-images.yml/runs?branch=main&status=success&per_page=1&exclude_pull_requests=true"
    {
        if [ -n "${GITHUB_TOKEN:-}" ]; then
            curl -sf --max-time 15 -H "Authorization: Bearer ${GITHUB_TOKEN}" \
                "${url}" 2>/dev/null
        else
            curl -sf --max-time 15 "${url}" 2>/dev/null
        fi
    } | grep -m1 '"head_sha"' | cut -d'"' -f4 || true
}

# Beta-Kanal-Ziel: Tag des jüngsten GitHub-Prereleases (Release-Kandidat,
# z. B. v2026.2.1-beta.1). GitHub liefert /releases created_at-absteigend, das
# erste Tag mit dem "-beta."-Namensschema ist damit das jüngste Prerelease.
# Konvention: Prerelease ⟺ Tag enthält "-beta." (release.yml markiert genau
# diese Tags als GitHub-Prerelease). Leer = GitHub nicht erreichbar oder noch
# kein Prerelease. `|| true` gegen SIGPIPE unter `set -euo pipefail`.
_latest_prerelease_tag() {
    local repo="${GITHUB_REPO:-RettTechSolutions/ConvoyPlan}"
    local url="https://api.github.com/repos/${repo}/releases?per_page=30"
    {
        if [ -n "${GITHUB_TOKEN:-}" ]; then
            curl -sf --max-time 15 -H "Authorization: Bearer ${GITHUB_TOKEN}" \
                "${url}" 2>/dev/null
        else
            curl -sf --max-time 15 "${url}" 2>/dev/null
        fi
    } | grep -oE '"tag_name": *"[^"]*"' | cut -d'"' -f4 | grep -m1 -- '-beta\.' || true
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

# Resolve the latest *published release tag* (e.g. v2026.1.1). On the stable
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
    # Compose-Datei-Quelle je Kanal: stable → Release-Tag, beta → Prerelease-Tag,
    # nightly → main (explizites Opt-in auf jeden Commit).
    local ref
    case "$(read_channel)" in
        nightly)
            ref="main"
            ;;
        beta)
            ref="$(_latest_prerelease_tag)"
            if [ -z "${ref}" ]; then
                log "WARNUNG: neuesten Prerelease-Tag nicht ermittelbar — Stack-Datei nicht aktualisiert"
                return 0
            fi
            ;;
        *)
            ref="$(_latest_release_tag)"
            if [ -z "${ref}" ]; then
                log "WARNUNG: neuesten Release-Tag nicht ermittelbar — Stack-Datei nicht aktualisiert"
                return 0
            fi
            ;;
    esac

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

# ── Self-repair: health-gated deploy with automatic rollback ─────────────────
# A deploy is only "good" once the backend actually reports HEALTHY — not just
# when the container started. If the new backend never becomes healthy (e.g. an
# image older than the DB schema that crash-loops on `alembic upgrade`), roll
# back to the image that ran before the deploy and alert the superadmins.

DEPLOY_HEALTH_TIMEOUT="${DEPLOY_HEALTH_TIMEOUT:-180}"
ROLLBACK_HEALTH_TIMEOUT="${ROLLBACK_HEALTH_TIMEOUT:-150}"

# Container ID of the backend service (running or stopped).
_backend_cid() {
    docker ps -aq \
        --filter "label=com.docker.compose.project=${COMPOSE_PROJECT}" \
        --filter "label=com.docker.compose.service=backend" | head -1
}

# The IMAGE ID (not the floating tag) the backend currently runs. Pinning the
# rollback target to the digest is essential: `docker compose pull` moves the
# :nightly/:latest/:beta tag onto the NEW image, so rolling back "by tag" would
# just redeploy the broken image. The image ID stays put.
_backend_image_id() {
    local cid
    cid="$(_backend_cid)"
    [ -z "${cid}" ] && { echo ""; return; }
    docker inspect "${cid}" --format '{{.Image}}' 2>/dev/null || echo ""
}

# Wait until the backend healthcheck reports healthy, or give up. Fails fast on
# a clear crash-loop (RestartCount climbing). An image WITHOUT a healthcheck
# (older stacks) counts as good once it is "running" — backwards compatible.
_wait_backend_healthy() {
    local timeout="$1" waited=0 cid health status restarts
    health=""; status=""
    while [ "${waited}" -lt "${timeout}" ]; do
        cid="$(_backend_cid)"
        if [ -n "${cid}" ]; then
            health="$(docker inspect "${cid}" --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}' 2>/dev/null || echo '')"
            status="$(docker inspect "${cid}" --format '{{.State.Status}}' 2>/dev/null || echo '')"
            restarts="$(docker inspect "${cid}" --format '{{.RestartCount}}' 2>/dev/null || echo 0)"
            case "${health}" in
                healthy) return 0 ;;
                none)    [ "${status}" = "running" ] && return 0 ;;
            esac
            if [ "${restarts:-0}" -ge 3 ]; then
                log "Backend im Crash-Loop (RestartCount=${restarts}, Health=${health})."
                return 1
            fi
        fi
        sleep 5
        waited=$((waited + 5))
    done
    log "Backend nicht gesund innerhalb ${timeout}s (Health=${health:-unbekannt}, Status=${status:-unbekannt})."
    return 1
}

# Drop an alert marker the backend's deploy-alert watcher emails to superadmins.
_write_deploy_alert() {
    local event="$1" detail="$2" failed="$3" restored="$4" id
    id="$(date -u '+%Y%m%dT%H%M%SZ')-$$"
    printf '{"id":"%s","event":"%s","at":"%s","failed_image":"%s","restored_image":"%s","detail":"%s"}\n' \
        "${id}" "${event}" "$(date -u '+%Y-%m-%dT%H:%M:%SZ')" "${failed}" "${restored}" "${detail}" \
        > /update_status/deploy_alert.json 2>/dev/null || true
}

# Restore a known-good backend image (by ID) and wait for it to become healthy.
_rollback_backend() {
    local good_image="$1"
    if [ -z "${good_image}" ]; then
        log "ROLLBACK nicht möglich: kein vorheriges Backend-Image bekannt."
        return 1
    fi
    log "ROLLBACK: Deploy nicht gesund — stelle vorheriges Backend-Image wieder her (${good_image})…"
    if BACKEND_IMAGE="${good_image}" docker compose -p "${COMPOSE_PROJECT}" -f "${COMPOSE_FILE}" \
            up -d --no-build --force-recreate backend 2>&1 | tee -a "${LOG_FILE}"; then
        if _wait_backend_healthy "${ROLLBACK_HEALTH_TIMEOUT}"; then
            log "ROLLBACK erfolgreich — Backend ist wieder gesund."
            return 0
        fi
    fi
    log "ROLLBACK fehlgeschlagen — manueller Eingriff nötig."
    return 1
}

do_update() {
    log "Starte Image-Update (Kanal: $(read_channel))…"

    # Image-Tags des aktiven Kanals exportieren (:latest / :beta / :nightly),
    # damit docker compose pull/up die richtigen Refs interpoliert.
    _apply_channel_images

    # Self-repair: den VOR diesem Deploy laufenden Backend-Image-Stand merken
    # (per Image-ID, damit ein verschobenes Tag den Rollback nicht aushebelt)
    # sowie das neue Ziel-Image für die Alert-Meldung.
    local good_backend_image new_backend_image
    good_backend_image="$(_backend_image_id)"
    new_backend_image="${BACKEND_IMAGE:-unbekannt}"

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

        # Self-repair health gate: the API must actually come up, not just start.
        # A backend that crash-loops (e.g. an image older than the DB schema)
        # would otherwise be reported as a successful update while every /api/*
        # route 502s. If it never turns healthy, roll back to the previous image.
        if ! _wait_backend_healthy "${DEPLOY_HEALTH_TIMEOUT}"; then
            log "FEHLER: neues Backend wurde nach dem Deploy nicht gesund — starte automatischen Rollback."
            if _rollback_backend "${good_backend_image}"; then
                _write_deploy_alert "deploy_rolled_back" \
                    "Neues Backend-Image wurde nicht gesund; automatischer Rollback auf die zuvor laufende Version durchgefuehrt." \
                    "${new_backend_image}" "${good_backend_image}"
                write_status "$(get_sha_from_backend)"
            else
                _write_deploy_alert "deploy_failed" \
                    "Neues Backend-Image wurde nicht gesund UND der automatische Rollback ist fehlgeschlagen — manueller Eingriff noetig." \
                    "${new_backend_image}" "${good_backend_image:-unbekannt}"
            fi
            return 1
        fi

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
#   stable  → neuester Release-Tag      (:latest, nur vom Release-Workflow gebaut)
#   beta    → neuester Prerelease-Tag    (:beta, aus einem vX.Y.Z-beta.N-Tag)
#   nightly → letzter Nightly-Build-SHA  (:nightly, bei jedem main-Push gebaut)
# Gespeichert wird "<kanal> <ref>" — dadurch löst auch ein Kanalwechsel im
# Admin-Panel beim nächsten Check automatisch ein Update auf das neue Ziel aus.
LAST_DEPLOYED_FILE=/update_status/last_deployed
LAST_NOTIFIED_FILE=/update_status/last_notified

# Echoes "stable <tag>", "beta <tag>" or "nightly <sha>"; empty when GitHub is
# unreachable (or the channel has no target yet).
_current_target() {
    local ch ref
    ch="$(read_channel)"
    case "${ch}" in
        nightly) ref="$(_nightly_built_sha)" ;;
        beta)    ref="$(_latest_prerelease_tag)" ;;
        *)       ref="$(_latest_release_tag)" ;;
    esac
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

    # Kein automatisches DOWNGRADE bei tag-basierten Kanälen (stable/beta): Lief
    # die Instanz vorher auf einem neueren Stand (z. B. Nightly oder ein
    # neueres Release), ist der installierte Stand NEUER als das Ziel-Tag —
    # automatisch aufs ältere Tag zurückzugehen wäre riskant (bereits
    # angewendete DB-Migrationen!). Es greift dann erst wieder, wenn ein
    # neueres Ziel den installierten Stand überholt. Der Nightly-Kanal folgt
    # bewusst immer main-HEAD (kein Guard). Der manuelle Trigger ("Jetzt
    # updaten") erzwingt das Downgrade weiterhin bewusst.
    ch="${target%% *}"
    ref="${target#* }"
    if [ "${ch}" != "nightly" ]; then
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

    # Modus "notify": nicht installieren — nur einmal pro Ziel loggen. Die
    # E-Mail an die Superadmins verschickt das Backend; installiert wird
    # ausschließlich über den manuellen Trigger.
    if [ "$(read_mode)" = "notify" ]; then
        local notified
        notified="$(cat "${LAST_NOTIFIED_FILE}" 2>/dev/null || true)"
        if [ "${target}" != "${notified}" ]; then
            log "Update verfügbar: ${target} — Modus 'notify': keine automatische Installation (manuell über das Admin-Panel updaten)."
            echo "${target}" > "${LAST_NOTIFIED_FILE}"
        fi
        return 0
    fi

    log "Neues Update-Ziel: ${target} (zuletzt deployt: ${last:-unbekannt}) — starte automatisches Update"
    if do_update; then
        echo "${target}" > "${LAST_DEPLOYED_FILE}"
    fi
}

while true; do
    # Trigger check — runs every TRIGGER_POLL seconds so the UI reacts quickly
    if [ -f /update_status/trigger ]; then
        # Regionswechsel hat Vorrang: Trigger und Regionswechsel-Lock können
        # gleichzeitig gesetzt sein. Bei aktivem Lock wird der Trigger NICHT
        # konsumiert (kein `rm -f`/`do_update`), sondern liegen gelassen —
        # der Regionswechsel-Check unten holt das Update automatisch nach,
        # sobald der Wechsel durch ist. Sonst würde ein manueller Trigger
        # ("Jetzt updaten") denselben Compose-Stack anfassen wie ein laufender
        # switch-region.sh.
        if region_switch_blocked; then
            log "Regionswechsel-Lock aktiv — Trigger wird zurückgestellt bis nach dem Wechsel."
            sleep "${TRIGGER_POLL}"
            continue
        fi
        log "Trigger erkannt — starte Update"
        rm -f /update_status/trigger
        if do_update; then
            _remember_target
        fi
        continue
    fi

    # Regionswechsel: liegt eine Anforderung vor, hat sie Vorrang vor dem
    # regulären Update-Check unten (switch-region.sh läuft synchron zu Ende).
    if run_region_switch_if_requested; then
        continue
    fi
    # Ein aktives Lock (auch ein verwaistes nach einem Absturz) blockiert die
    # reguläre Update-Ausführung — spiegelbildlich zu is_busy() im Backend.
    if region_switch_blocked; then
        log "Regionswechsel-Lock aktiv — reguläres Update wird in diesem Zyklus übersprungen."
        sleep "${TRIGGER_POLL}"
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
