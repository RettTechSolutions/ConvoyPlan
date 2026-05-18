#!/bin/bash
set -euo pipefail

REPO_DIR=/workspace
REPO_URL="https://github.com/RettTechSolutions/MarschPlan.git"
INTERVAL="${UPDATE_INTERVAL:-300}"

# Fail fast if token not provided
: "${GITHUB_TOKEN:?GITHUB_TOKEN must be set}"

# Store credentials securely in netrc — never exposed in URL or process list
printf 'machine github.com\nlogin x-access-token\npassword %s\n' "${GITHUB_TOKEN}" > ~/.netrc
chmod 600 ~/.netrc

# Allow git to operate on the mounted workspace (owned by host user, not container root)
git config --global --add safe.directory "${REPO_DIR}"

COMPOSE_FILES=(-f "${REPO_DIR}/docker-compose.yml" -f "${REPO_DIR}/docker-compose.override.yml")

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*"; }

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

log "Updater started. Polling every ${INTERVAL}s."

while true; do
  if ! git -C "${REPO_DIR}" fetch origin main --quiet 2>&1; then
    log "fetch failed, retrying in ${INTERVAL}s"
    sleep "${INTERVAL}"
    continue
  fi

  REMOTE=$(git -C "${REPO_DIR}" rev-parse origin/main)

  if [ "${DEPLOYED}" != "${REMOTE}" ]; then
    log "Update detected: ${DEPLOYED:0:7} → ${REMOTE:0:7}"
    if git -C "${REPO_DIR}" pull --ff-only origin main && \
       docker compose "${COMPOSE_FILES[@]}" up -d --build; then
      DEPLOYED=$(git -C "${REPO_DIR}" rev-parse HEAD)
      log "Updated to ${DEPLOYED:0:7}"
    else
      log "Deploy failed — will retry in ${INTERVAL}s"
    fi
  fi

  sleep "${INTERVAL}"
done
