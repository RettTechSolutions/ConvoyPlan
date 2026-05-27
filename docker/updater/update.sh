#!/bin/bash
set -euo pipefail

REPO_DIR=/workspace
REPO_URL="https://github.com/RettTechSolutions/ConvoyPlan.git"
INTERVAL="${UPDATE_INTERVAL:-300}"
TRIGGER_POLL=10   # check trigger file every 10s so the UI reacts quickly

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

  if ! git -C "${REPO_DIR}" fetch origin main --quiet 2>&1; then
    log "fetch failed, retrying in ${INTERVAL}s"
    wait_or_trigger && { DEPLOYED=""; continue; }
    continue
  fi

  REMOTE=$(git -C "${REPO_DIR}" rev-parse origin/main)

  if [ "${DEPLOYED}" != "${REMOTE}" ]; then
    log "Update detected: ${DEPLOYED:0:7} → ${REMOTE:0:7}"
    # Get all services except the updater itself (to avoid killing this container)
    SERVICES=$(docker compose "${COMPOSE_FILES[@]}" config --services 2>/dev/null | grep -v '^updater$' | tr '\n' ' ')
    if git -C "${REPO_DIR}" reset --hard origin/main 2>&1 | tee -a "${LOG_FILE}" && \
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
