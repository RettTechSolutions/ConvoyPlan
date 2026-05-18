#!/usr/bin/env bash
set -euo pipefail
# NOTE: This script is only needed for the initial server migration or emergency
# manual deploys. Once the `updater` container is running on the server, all
# future deployments happen automatically via git push to origin/main.
#
# ONE-TIME SERVER MIGRATION (run after this deploy lands):
#   1. On the server: echo "GITHUB_TOKEN=<pat>" > ~/MarschPlan/.env
#   2. docker compose up -d   (starts the updater)
#   3. Verify: docker logs -f updater

REMOTE="${DEPLOY_HOST:-s-lx04-docker}"
REMOTE_DIR="${DEPLOY_DIR:-~/MarschPlan}"

echo "→ Sync to ${REMOTE}:${REMOTE_DIR}"
rsync -az --delete \
  --exclude='.git' \
  --exclude='__pycache__' \
  --exclude='*.pyc' \
  --exclude='.venv' \
  --exclude='node_modules' \
  --exclude='.svelte-kit' \
  --exclude='build' \
  --exclude='*.egg-info' \
  "$(git rev-parse --show-toplevel)/" \
  "${REMOTE}:${REMOTE_DIR}/"

echo "→ Build & restart on ${REMOTE}"
ssh "${REMOTE}" "cd ${REMOTE_DIR} && docker compose build --no-cache && docker compose up -d"

echo "→ Done — $(ssh ${REMOTE} "docker compose -f ${REMOTE_DIR}/docker-compose.yml ps --format 'table {{.Name}}\t{{.Status}}'")"
