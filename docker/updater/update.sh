#!/bin/bash
set -euo pipefail

REPO_DIR=/workspace
REPO_URL="https://${GITHUB_TOKEN:-}@github.com/RettTechSolutions/MarschPlan.git"
COMPOSE_FILES="-f ${REPO_DIR}/docker-compose.yml -f ${REPO_DIR}/docker-compose.override.yml"
INTERVAL=300

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*"; }

# First start: clone if no git repo present
if [ ! -d "${REPO_DIR}/.git" ]; then
  log "No repo found, cloning..."
  git clone "${REPO_URL}" "${REPO_DIR}"
  log "Cloned to ${REPO_DIR}"
fi

# Keep remote URL current (supports token rotation)
git -C "${REPO_DIR}" remote set-url origin "${REPO_URL}"

log "Updater started. Polling every ${INTERVAL}s."

while true; do
  git -C "${REPO_DIR}" fetch origin main --quiet 2>/dev/null || {
    log "fetch failed (network issue?), retrying in ${INTERVAL}s"
    sleep "${INTERVAL}"
    continue
  }

  LOCAL=$(git -C "${REPO_DIR}" rev-parse HEAD)
  REMOTE=$(git -C "${REPO_DIR}" rev-parse origin/main)

  if [ "${LOCAL}" != "${REMOTE}" ]; then
    log "Update detected: ${LOCAL:0:7} → ${REMOTE:0:7}"
    git -C "${REPO_DIR}" pull --ff-only origin main
    docker compose ${COMPOSE_FILES} up -d --build
    log "Updated to $(git -C "${REPO_DIR}" rev-parse --short HEAD)"
  fi

  sleep "${INTERVAL}"
done
