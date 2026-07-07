#!/bin/bash
set -euo pipefail

REPO_DIR=/workspace
REPO_URL="https://github.com/RettTechSolutions/ConvoyPlan.git"
GITHUB_REPO="${GITHUB_REPO:-RettTechSolutions/ConvoyPlan}"
INTERVAL="${UPDATE_INTERVAL:-300}"
TRIGGER_POLL=10   # check trigger file every 10s so the UI reacts quickly
CHANNEL_FILE=/update_status/channel   # written by the backend: "stable" | "beta"
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

# Read the release channel chosen in the admin panel (default: stable).
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

# Helper: sleep in short chunks, break early if trigger appears
wait_or_trigger() {
    local slept=0
    while [ "${slept}" -lt "${INTERVAL}" ]; do
        sleep "${TRIGGER_POLL}"
        slept=$((slept + TRIGGER_POLL))
        if [ -f /update_status/trigger ]; then
            return 0  # trigger detected
        fi
    done
    return 1  # no trigger, interval elapsed
}

while true; do
  # Check trigger first (may have been set while we were working)
  if [ -f /update_status/trigger ]; then
    log "Trigger erkannt — erzwinge Update"
    rm -f /update_status/trigger
    DEPLOYED=""
  fi

  CHANNEL="$(read_channel)"

  if [ "${CHANNEL}" = "beta" ]; then
    # Beta: track every commit on main (the historical behaviour).
    if ! git -C "${REPO_DIR}" fetch origin main --quiet 2>&1; then
      log "fetch failed, retrying in ${INTERVAL}s"
      wait_or_trigger && { DEPLOYED=""; continue; }
      continue
    fi
    REMOTE=$(git -C "${REPO_DIR}" rev-parse origin/main)
    TARGET_DESC="main"
  else
    # Stable: only deploy the latest published release, so a normal push to
    # main does not trigger an update.
    TAG="$(latest_release_tag)"
    if [ -z "${TAG}" ]; then
      log "Channel 'stable': kein Release gefunden — überspringe (warte auf erstes Release)."
      wait_or_trigger && { DEPLOYED=""; continue; }
      continue
    fi
    if ! git -C "${REPO_DIR}" fetch origin --tags --force --quiet 2>&1; then
      log "tag fetch failed, retrying in ${INTERVAL}s"
      wait_or_trigger && { DEPLOYED=""; continue; }
      continue
    fi
    REMOTE=$(git -C "${REPO_DIR}" rev-parse "refs/tags/${TAG}^{commit}" 2>/dev/null || echo "")
    if [ -z "${REMOTE}" ]; then
      log "Release-Tag ${TAG} nach fetch nicht auflösbar — überspringe."
      wait_or_trigger && { DEPLOYED=""; continue; }
      continue
    fi
    TARGET_DESC="Release ${TAG}"
  fi

  # Kein automatisches DOWNGRADE im Stable-Kanal: Lief die Instanz vorher im
  # Beta-Kanal, ist der deployte Stand neuer als das letzte Release — dann
  # erst wieder aktualisieren, wenn ein Release den Stand überholt (bereits
  # angewendete DB-Migrationen!). Der manuelle Trigger leert DEPLOYED und
  # erzwingt das Downgrade weiterhin bewusst.
  if [ "${CHANNEL}" = "stable" ] && [ -n "${DEPLOYED}" ] && [ "${DEPLOYED}" != "${REMOTE}" ] && \
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
    # Get all services except the updater itself (to avoid killing this container)
    SERVICES=$(docker compose "${COMPOSE_FILES[@]}" config --services 2>/dev/null | grep -v '^updater$' | tr '\n' ' ')
    if git -C "${REPO_DIR}" reset --hard "${REMOTE}" 2>&1 | tee -a "${LOG_FILE}" && \
       git -C "${REPO_DIR}" clean -fd 2>&1 | tee -a "${LOG_FILE}" && \
       GIT_SHA="${REMOTE}" docker compose "${COMPOSE_FILES[@]}" up -d --build ${SERVICES} 2>&1 | tee -a "${LOG_FILE}"; then
      DEPLOYED=$(git -C "${REPO_DIR}" rev-parse HEAD)
      log "Updated to ${DEPLOYED:0:7}"
      mkdir -p /update_status
      printf '{"deployed_sha":"%s","deployed_at":"%s"}\n' \
        "${DEPLOYED}" \
        "$(date -u '+%Y-%m-%dT%H:%M:%SZ')" \
        > /update_status/status.json
    else
      log "Deploy failed — will retry in ${INTERVAL}s"
    fi
  fi

  # Sleep in short chunks; restart immediately if a manual trigger arrives
  wait_or_trigger && { DEPLOYED=""; continue; }
done
