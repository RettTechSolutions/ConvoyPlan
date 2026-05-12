#!/usr/bin/env bash
set -euo pipefail

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
