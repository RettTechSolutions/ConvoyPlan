#!/bin/bash
set -euo pipefail

REPO_DIR=/workspace
REPO_URL="https://github.com/RettTechSolutions/ConvoyPlan.git"
GITHUB_REPO="${GITHUB_REPO:-RettTechSolutions/ConvoyPlan}"
INTERVAL="${UPDATE_INTERVAL:-300}"
TRIGGER_POLL=10   # check trigger file every 10s so the UI reacts quickly
# Trigger-Datei des manuellen Updates. Ueberschreibbar fuer Tests, der
# Betriebs-Default bleibt unveraendert — dasselbe Muster wie
# SWITCH_REGION_SCRIPT in region-hook.sh und REGION_SOURCE_SCRIPT im
# GraphHopper-Entrypoint.
TRIGGER_FILE="${TRIGGER_FILE:-/update_status/trigger}"
CHANNEL_FILE=/update_status/channel   # written by the backend: "stable" | "beta" | "nightly"
MODE_FILE=/update_status/mode         # written by the backend: "auto" | "notify"
LAST_NOTIFIED_FILE=/update_status/last_notified

# Fail fast if token not provided
: "${GITHUB_TOKEN:?GITHUB_TOKEN must be set}"

# Store credentials securely in netrc — never exposed in URL or process list
printf 'machine github.com\nlogin x-access-token\npassword %s\n' "${GITHUB_TOKEN}" > ~/.netrc
chmod 600 ~/.netrc

# Allow git to operate on the mounted workspace (owned by host user, not container root)
git config --global --add safe.directory "${REPO_DIR}"

COMPOSE_PROJECT="${COMPOSE_PROJECT_NAME:-convoyplan}"
COMPOSE_FILES=(-p "${COMPOSE_PROJECT}" -f "${REPO_DIR}/docker-compose.yml")
[ -f "${REPO_DIR}/docker-compose.override.yml" ] && COMPOSE_FILES+=(-f "${REPO_DIR}/docker-compose.override.yml")

LOG_FILE=/update_status/update.log
log() {
    local msg="[$(date '+%Y-%m-%d %H:%M:%S')] $*"
    echo "$msg"
    echo "$msg" >> "${LOG_FILE}"
}

# Regionswechsel-Einhängung: gemeinsame Logik mit update-images.sh, siehe
# region-hook.sh (Begründung für die gemeinsame Datei dort).
# shellcheck source=./region-hook.sh
source /region-hook.sh

# ── Self-repair: health gate + rollback (source/build path) ──────────────────
# A deploy counts as good only once the backend actually reports HEALTHY, not
# merely "started". If the freshly built backend never turns healthy (e.g. it
# crash-loops on `alembic upgrade` because the checkout is older than the DB
# schema), we rebuild the previous commit and alert the superadmins.
DEPLOY_HEALTH_TIMEOUT="${DEPLOY_HEALTH_TIMEOUT:-180}"
ROLLBACK_HEALTH_TIMEOUT="${ROLLBACK_HEALTH_TIMEOUT:-150}"

_backend_cid() {
    docker ps -aq \
        --filter "label=com.docker.compose.project=${COMPOSE_PROJECT}" \
        --filter "label=com.docker.compose.service=backend" | head -1
}

# Wait until the backend healthcheck reports healthy, or give up. Fails fast on
# a clear crash-loop. An image without a healthcheck counts as good once running.
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

# Read the release channel chosen in the admin panel (default: stable).
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

# Read the update mode chosen in the admin panel (default: auto).
#   auto   → install available updates automatically
#   notify → no automatic install; the backend emails the superadmins and the
#            update only runs via the manual trigger ("Jetzt updaten").
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

# Resolve the tag of the latest *published* GitHub release (e.g. v1.2.3).
# Empty output means no release exists (or GitHub was unreachable).
# `|| true`: under `set -euo pipefail` a curl failure or a grep without match
# would otherwise kill the whole updater (container restart loop).
latest_release_tag() {
    {
        if [ -n "${GITHUB_TOKEN:-}" ]; then
            curl -sf --max-time 15 -H "Authorization: Bearer ${GITHUB_TOKEN}" \
                "https://api.github.com/repos/${GITHUB_REPO}/releases/latest" 2>/dev/null
        else
            curl -sf --max-time 15 \
                "https://api.github.com/repos/${GITHUB_REPO}/releases/latest" 2>/dev/null
        fi
    } | grep -m1 '"tag_name"' | cut -d'"' -f4 || true
}

# Resolve the tag of the latest GitHub *pre-release* (release candidate, e.g.
# v2026.2.1-beta.1). GitHub returns /releases newest-first, so the first tag
# matching the "-beta." naming convention is the most recent pre-release.
# Convention: pre-release ⟺ tag contains "-beta." (release.yml marks exactly
# those tags as a GitHub pre-release). Empty output = no pre-release yet or
# GitHub unreachable. `|| true` guards against SIGPIPE under `set -euo pipefail`.
latest_prerelease_tag() {
    {
        if [ -n "${GITHUB_TOKEN:-}" ]; then
            curl -sf --max-time 15 -H "Authorization: Bearer ${GITHUB_TOKEN}" \
                "https://api.github.com/repos/${GITHUB_REPO}/releases?per_page=30" 2>/dev/null
        else
            curl -sf --max-time 15 \
                "https://api.github.com/repos/${GITHUB_REPO}/releases?per_page=30" 2>/dev/null
        fi
    } | grep -oE '"tag_name": *"[^"]*"' | cut -d'"' -f4 | grep -m1 -- '-beta\.' || true
}

# First start: clone if no git repo present
if [ ! -d "${REPO_DIR}/.git" ]; then
  log "No repo found, cloning..."
  git clone "${REPO_URL}" "${REPO_DIR}"
  log "Cloned to ${REPO_DIR}"
fi

# Keep remote URL current (no token in URL — auth is via ~/.netrc)
git -C "${REPO_DIR}" remote set-url origin "${REPO_URL}"

# Track last successfully deployed SHA separately from HEAD
# so a failed build is retried next iteration
DEPLOYED=$(git -C "${REPO_DIR}" rev-parse HEAD)

# Write initial status so the UI shows something on first load
mkdir -p /update_status
# The backend runs as non-root (appuser, uid 1001 — see backend/Dockerfile) and
# must be able to create the trigger file in this shared volume. The updater
# runs as root, so it owns the volume by default; hand it to the backend user.
# `-R` also repairs pre-existing root-owned volumes from before the backend was
# switched to non-root, so manual updates keep working after the upgrade.
chown -R 1001:1001 /update_status 2>/dev/null || true
printf '{"deployed_sha":"%s","deployed_at":"%s"}\n' \
  "${DEPLOYED}" \
  "$(date -u '+%Y-%m-%dT%H:%M:%SZ')" \
  > /update_status/status.json

log "Updater started. Polling every ${INTERVAL}s, trigger check every ${TRIGGER_POLL}s."

# Helper: sleep in short chunks, break early if trigger or region request appears
wait_or_trigger() {
    local slept=0
    while [ "${slept}" -lt "${INTERVAL}" ]; do
        sleep "${TRIGGER_POLL}"
        slept=$((slept + TRIGGER_POLL))
        if [ -f "${TRIGGER_FILE}" ]; then
            return 0  # trigger detected
        fi
        # Auch auf eine Regionsanforderung frueh aufwachen, nicht nur auf den
        # Update-Trigger: Sonst schlaefe der Updater nach einem Ziel-Check bis
        # zu INTERVAL (Standard 300 s) weiter, waehrend im Panel ein gerade
        # angestossener Wechsel minutenlang unbearbeitet daliegt.
        #
        # ABER mit eigenem Rueckgabewert, NICHT mit 0: Die Aufrufer behandeln 0
        # als "manueller Update-Trigger" und leeren daraufhin DEPLOYED, was ein
        # erneutes Deployment erzwingt — bei tag-basierten Kanaelen sogar ein
        # bewusstes Downgrade (siehe Kommentar beim Downgrade-Guard). Ein
        # Regionswechsel darf das nicht ausloesen. 2 faellt bei allen Aufrufern
        # durch `&&` hindurch auf das direkt folgende `continue`, die Schleife
        # dreht sich also sofort weiter und greift die Anforderung auf.
        if [ -f "${REGION_REQUEST_FILE}" ]; then
            return 2  # region switch requested
        fi
    done
    return 1  # no trigger, interval elapsed
}

while true; do
  # Check trigger first (may have been set while we were working)
  if [ -f "${TRIGGER_FILE}" ]; then
    log "Trigger erkannt — erzwinge Update"
    rm -f "${TRIGGER_FILE}"
    DEPLOYED=""
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

  CHANNEL="$(read_channel)"

  if [ "${CHANNEL}" = "nightly" ]; then
    # Nightly: track every commit on main (the historical "beta" behaviour).
    if ! git -C "${REPO_DIR}" fetch origin main --quiet 2>&1; then
      log "fetch failed, retrying in ${INTERVAL}s"
      wait_or_trigger && { DEPLOYED=""; continue; }
      continue
    fi
    REMOTE=$(git -C "${REPO_DIR}" rev-parse origin/main)
    TARGET_DESC="main"
  else
    # Tag-basierte Kanäle: stable → neuestes veröffentlichtes Release, beta →
    # neuestes Prerelease (Release-Kandidat). Ein normaler Push auf main löst
    # hier kein Update aus.
    if [ "${CHANNEL}" = "beta" ]; then
      TAG="$(latest_prerelease_tag)"
      if [ -z "${TAG}" ]; then
        log "Channel 'beta': kein Prerelease gefunden — überspringe (warte auf ersten Release-Kandidaten)."
        wait_or_trigger && { DEPLOYED=""; continue; }
        continue
      fi
      TARGET_DESC="Prerelease ${TAG}"
    else
      TAG="$(latest_release_tag)"
      if [ -z "${TAG}" ]; then
        log "Channel 'stable': kein Release gefunden — überspringe (warte auf erstes Release)."
        wait_or_trigger && { DEPLOYED=""; continue; }
        continue
      fi
      TARGET_DESC="Release ${TAG}"
    fi
    if ! git -C "${REPO_DIR}" fetch origin --tags --force --quiet 2>&1; then
      log "tag fetch failed, retrying in ${INTERVAL}s"
      wait_or_trigger && { DEPLOYED=""; continue; }
      continue
    fi
    REMOTE=$(git -C "${REPO_DIR}" rev-parse "refs/tags/${TAG}^{commit}" 2>/dev/null || echo "")
    if [ -z "${REMOTE}" ]; then
      log "Tag ${TAG} nach fetch nicht auflösbar — überspringe."
      wait_or_trigger && { DEPLOYED=""; continue; }
      continue
    fi
  fi

  # Kein automatisches DOWNGRADE bei tag-basierten Kanälen (stable/beta): Lief
  # die Instanz vorher auf einem neueren Stand (z. B. Nightly), ist der
  # deployte Stand neuer als das Ziel-Tag — dann erst wieder aktualisieren,
  # wenn ein neueres Ziel den Stand überholt (bereits angewendete
  # DB-Migrationen!). Nightly folgt bewusst immer main (kein Guard). Der
  # manuelle Trigger leert DEPLOYED und erzwingt das Downgrade weiterhin bewusst.
  if [ "${CHANNEL}" != "nightly" ] && [ -n "${DEPLOYED}" ] && [ "${DEPLOYED}" != "${REMOTE}" ] && \
     git -C "${REPO_DIR}" merge-base --is-ancestor "${REMOTE}" "${DEPLOYED}" 2>/dev/null; then
    log "Deployter Stand ${DEPLOYED:0:7} ist bereits ${TARGET_DESC} oder neuer — kein automatisches Downgrade."
  elif [ "$(read_mode)" = "notify" ] && [ -n "${DEPLOYED}" ] && [ "${DEPLOYED}" != "${REMOTE}" ]; then
    # Modus "notify": nicht installieren — nur einmal pro Ziel loggen. Die
    # E-Mail an die Superadmins verschickt das Backend; der manuelle Trigger
    # (leert DEPLOYED) installiert weiterhin.
    NOTIFIED="$(cat "${LAST_NOTIFIED_FILE}" 2>/dev/null || true)"
    if [ "${CHANNEL} ${REMOTE}" != "${NOTIFIED}" ]; then
      log "Update verfügbar (${TARGET_DESC} ${REMOTE:0:7}) — Modus 'notify': keine automatische Installation (manuell über das Admin-Panel updaten)."
      echo "${CHANNEL} ${REMOTE}" > "${LAST_NOTIFIED_FILE}"
    fi
  elif [ "${DEPLOYED}" != "${REMOTE}" ]; then
    log "Update detected (${CHANNEL}): ${DEPLOYED:0:7} → ${TARGET_DESC} ${REMOTE:0:7}"
    # Remember the commit running before this deploy so we can rebuild it if the
    # new one fails to become healthy (self-repair against bad deploys).
    PREV_DEPLOYED="${DEPLOYED}"
    # Get all services except the updater itself (to avoid killing this container)
    SERVICES=$(docker compose "${COMPOSE_FILES[@]}" config --services 2>/dev/null | grep -v '^updater$' | tr '\n' ' ')
    if git -C "${REPO_DIR}" reset --hard "${REMOTE}" 2>&1 | tee -a "${LOG_FILE}" && \
       git -C "${REPO_DIR}" clean -fd 2>&1 | tee -a "${LOG_FILE}" && \
       GIT_SHA="${REMOTE}" docker compose "${COMPOSE_FILES[@]}" up -d --build ${SERVICES} 2>&1 | tee -a "${LOG_FILE}"; then

      # Self-repair health gate: the API must actually come up, not just start.
      if _wait_backend_healthy "${DEPLOY_HEALTH_TIMEOUT}"; then
        DEPLOYED=$(git -C "${REPO_DIR}" rev-parse HEAD)
        log "Updated to ${DEPLOYED:0:7}"
        mkdir -p /update_status
        printf '{"deployed_sha":"%s","deployed_at":"%s"}\n' \
          "${DEPLOYED}" \
          "$(date -u '+%Y-%m-%dT%H:%M:%SZ')" \
          > /update_status/status.json
      else
        log "FEHLER: neues Backend wurde nach dem Deploy nicht gesund — Rollback auf ${PREV_DEPLOYED:0:7}."
        if [ -n "${PREV_DEPLOYED}" ] && \
           git -C "${REPO_DIR}" reset --hard "${PREV_DEPLOYED}" 2>&1 | tee -a "${LOG_FILE}" && \
           git -C "${REPO_DIR}" clean -fd 2>&1 | tee -a "${LOG_FILE}" && \
           GIT_SHA="${PREV_DEPLOYED}" docker compose "${COMPOSE_FILES[@]}" up -d --build backend 2>&1 | tee -a "${LOG_FILE}" && \
           _wait_backend_healthy "${ROLLBACK_HEALTH_TIMEOUT}"; then
          DEPLOYED="${PREV_DEPLOYED}"
          log "ROLLBACK erfolgreich auf ${PREV_DEPLOYED:0:7}."
          _write_deploy_alert "deploy_rolled_back" \
            "Neues Backend wurde nicht gesund; automatischer Rollback auf ${PREV_DEPLOYED:0:7} durchgefuehrt." \
            "${REMOTE:0:12}" "${PREV_DEPLOYED:0:12}"
        else
          log "ROLLBACK fehlgeschlagen — manueller Eingriff noetig."
          _write_deploy_alert "deploy_failed" \
            "Neues Backend wurde nicht gesund UND der automatische Rollback ist fehlgeschlagen — manueller Eingriff noetig." \
            "${REMOTE:0:12}" "${PREV_DEPLOYED:0:12}"
        fi
      fi
    else
      log "Deploy failed — will retry in ${INTERVAL}s"
    fi
  fi

  # Sleep in short chunks; restart immediately if a manual trigger arrives
  wait_or_trigger && { DEPLOYED=""; continue; }
done
