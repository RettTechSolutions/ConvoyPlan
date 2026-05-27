# Auto-Updater Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a dedicated `updater` container to the Docker Compose stack that polls GitHub every 5 minutes and rebuilds the stack automatically when new commits land on `main`.

**Architecture:** A new Alpine-based `updater` service mounts the Docker socket and the project directory. On first start it clones the repo; every 5 minutes it compares local HEAD to `origin/main` and runs `docker compose up -d --build` if they differ. Auth uses a `GITHUB_TOKEN` env var embedded into the git remote URL.

**Tech Stack:** Docker (docker:24-cli image), Alpine Linux, bash, git, docker-compose v2

---

## File Map

**Create:**
- `docker/updater/Dockerfile` — image definition (docker:24-cli + git + bash)
- `docker/updater/update.sh` — polling loop script

**Modify:**
- `docker-compose.yml` — add `updater` service
- `.gitignore` — ensure `.env` is excluded
- `.env.example` — document `GITHUB_TOKEN`
- `scripts/deploy.sh` — add migration note in header comment

---

## Task 1: Updater Image — Dockerfile + update.sh

**Files:**
- Create: `docker/updater/Dockerfile`
- Create: `docker/updater/update.sh`

- [ ] **Step 1: Create `docker/updater/Dockerfile`**

```dockerfile
FROM docker:24-cli
RUN apk add --no-cache git bash
COPY update.sh /update.sh
RUN chmod +x /update.sh
ENTRYPOINT ["/bin/bash", "/update.sh"]
```

- [ ] **Step 2: Create `docker/updater/update.sh`**

```bash
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
```

- [ ] **Step 3: Build the image locally to verify it compiles**

```bash
docker build ./docker/updater -t marschplan-updater-test
```

Expected: `Successfully built ...` — no errors.

- [ ] **Step 4: Verify the script syntax**

```bash
docker run --rm marschplan-updater-test bash -n /update.sh && echo "syntax OK"
```

Expected: `syntax OK`

- [ ] **Step 5: Commit**

```bash
git add docker/updater/Dockerfile docker/updater/update.sh
git commit -m "feat: add updater container image (git-poll auto-deploy)"
```

---

## Task 2: Wire into Docker Compose + env files

**Files:**
- Modify: `docker-compose.yml`
- Modify: `.gitignore`
- Create: `.env.example`
- Modify: `scripts/deploy.sh`

- [ ] **Step 1: Add `updater` service to `docker-compose.yml`**

Open `docker-compose.yml`. After the `caddy:` service block and before the `volumes:` section, add:

```yaml
  updater:
    build: ./docker/updater
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock
      - .:/workspace
    environment:
      - GITHUB_TOKEN=${GITHUB_TOKEN:-}
    restart: unless-stopped
```

- [ ] **Step 2: Ensure `.env` is in `.gitignore`**

Check if `.env` is already excluded:

```bash
grep "^\.env$" .gitignore && echo "already present" || echo ".env" >> .gitignore
```

- [ ] **Step 3: Create `.env.example`**

```bash
cat > .env.example << 'EOF'
# GitHub Personal Access Token — required while the repo is private.
# Scope needed: repo (read)
# Generate at: https://github.com/settings/tokens
# Remove this line once the repo is public.
GITHUB_TOKEN=

# Optional: override deploy port bindings
# HTTP_PORT=80
# HTTPS_PORT=443
# DOMAIN=localhost
# ACME_EMAIL=admin@example.com
EOF
```

- [ ] **Step 4: Add migration note to `scripts/deploy.sh`**

At the top of `scripts/deploy.sh`, after the `set -euo pipefail` line, add:

```bash
# NOTE: This script is only needed for the initial server migration or emergency
# manual deploys. Once the `updater` container is running on the server, all
# future deployments happen automatically via git push to origin/main.
#
# ONE-TIME SERVER MIGRATION (run after this deploy lands):
#   1. On the server: echo "GITHUB_TOKEN=<pat>" > ~/MarschPlan/.env
#   2. docker compose up -d   (starts the updater)
#   3. Verify: docker logs -f updater
```

- [ ] **Step 5: Verify compose config is valid**

```bash
docker compose config --quiet && echo "compose OK"
```

Expected: `compose OK` — no syntax errors.

- [ ] **Step 6: Commit**

```bash
git add docker-compose.yml .gitignore .env.example scripts/deploy.sh
git commit -m "feat: wire updater into compose stack, add .env.example"
```

---

## Task 3: Integration test + push

**Files:** none new — validation only

- [ ] **Step 1: Push to GitHub**

```bash
git push origin main
```

Expected: both commits pushed, no errors.

- [ ] **Step 2: Verify the updater service appears in compose**

```bash
docker compose config | grep -A 10 "updater:"
```

Expected: service definition with `volumes`, `environment`, `restart: unless-stopped`.

- [ ] **Step 3: Smoke-test the updater locally (optional but recommended)**

Build the image fresh and verify git access works inside the container:

```bash
docker build ./docker/updater -t marschplan-updater-test

docker run --rm \
  -e GITHUB_TOKEN=fake \
  -v "$(git rev-parse --show-toplevel):/workspace" \
  -v /var/run/docker.sock:/var/run/docker.sock \
  --entrypoint bash \
  marschplan-updater-test \
  -c "git -C /workspace rev-parse HEAD && echo 'git access OK'"
```

Expected: prints a git SHA followed by `git access OK`.

- [ ] **Step 4: Document the server migration**

When the server is reachable, run these steps once:

```bash
# 1. Final rsync deploy (gets the new compose + updater image)
./scripts/deploy.sh

# 2. On the server (ssh s-lx04-docker):
echo "GITHUB_TOKEN=<your_pat>" > ~/MarschPlan/.env

# 3. Start updater (other containers already running)
ssh s-lx04-docker "cd ~/MarschPlan && docker compose up -d updater"

# 4. Watch it clone and start polling
ssh s-lx04-docker "docker logs -f updater"
# Expected output:
# [2026-05-13 10:00:01] No repo found, cloning...
# [2026-05-13 10:00:15] Cloned to /workspace
# [2026-05-13 10:00:15] Updater started. Polling every 300s.
```

- [ ] **Step 5: Verify update detection works end-to-end**

```bash
# Make a trivial commit and push
git commit --allow-empty -m "test: trigger updater"
git push origin main

# Within 5 minutes on the server:
ssh s-lx04-docker "docker logs --since=5m updater"
# Expected:
# [2026-05-13 10:05:01] Update detected: abc1234 → def5678
# [2026-05-13 10:05:30] Updated to def5678
```

After verifying, clean up:
```bash
git revert HEAD --no-edit
git push origin main
```
