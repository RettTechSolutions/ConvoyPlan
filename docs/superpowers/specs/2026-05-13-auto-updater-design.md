# Auto-Updater — Self-Updating Container Design

## Goal

Replace the manual rsync-based deployment with a pull-based `updater` container that polls GitHub every 5 minutes and rebuilds the stack when new commits arrive on `main`.

## Architecture

A new `updater` service joins the existing Docker Compose stack. It mounts the Docker socket so it can call `docker compose up -d --build` against the other services. It also mounts the project directory as `/workspace` so it can run `git fetch`/`git pull` in place. On first start it clones the repo if no `.git` directory exists.

Auth for the currently-private repo is via a GitHub Personal Access Token (`GITHUB_TOKEN`) stored in a `.env` file on the server (not committed). The token is embedded into the git remote URL at runtime. When the repo goes public, the token is simply removed from `.env`.

## Components

### `docker/updater/Dockerfile`

Alpine-based image (`docker:24-cli`) with `git` and `bash` added. Copies `update.sh` and sets it as entrypoint.

### `docker/updater/update.sh`

Polling loop:
1. If `/workspace/.git` does not exist: `git clone https://${GITHUB_TOKEN}@github.com/RettTechSolutions/MarschPlan.git /workspace`
2. Set remote URL with current token (supports token rotation)
3. Loop every 300 seconds:
   - `git fetch origin main --quiet`
   - Compare `git rev-parse HEAD` vs `git rev-parse origin/main`
   - If different: `git pull && docker compose -f /workspace/docker-compose.yml -f /workspace/docker-compose.override.yml up -d --build`
   - Log timestamp + short SHA on update

### `docker-compose.yml` — `updater` service

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

### `.env.example`

Documents `GITHUB_TOKEN=` so server operators know what to set.

### `.gitignore`

Ensures `.env` is excluded.

## Migration Path

1. Add updater to the stack, commit, push to GitHub
2. Run `./scripts/deploy.sh` one final time to sync the new compose config to the server
3. On the server: create `~/MarschPlan/.env` with `GITHUB_TOKEN=<pat>`
4. `docker compose up -d` starts the updater; it clones the repo and takes over
5. All future updates: `git push origin main` → picked up within 5 minutes

## Security

- `GITHUB_TOKEN` lives only in `.env` on the server — never committed
- Docker socket mount gives the updater full Docker access — acceptable for a trusted home server
- The updater runs with `restart: unless-stopped` so it survives server reboots

## Observability

```bash
docker logs -f updater   # live update log
```

Each update prints: `[2026-05-13 10:32:01] Updated to a1b2c3d`

## Not in scope

- Rollback on failed build
- Slack/email notifications
- Per-service selective rebuilds
