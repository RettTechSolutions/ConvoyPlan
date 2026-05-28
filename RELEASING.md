# Release Process

This document describes how to cut a new release of ConvoyPlan.

---

## Versioning

ConvoyPlan follows [Semantic Versioning](https://semver.org/):

- **MAJOR** – incompatible API or database changes requiring manual migration steps.
- **MINOR** – new features, backwards-compatible.
- **PATCH** – bug fixes and security patches.

---

## Pre-release Checklist

Before tagging a release, verify:

- [ ] All CI checks pass on `main` (`ci.yml`: backend tests, frontend type check, Docker build).
- [ ] `CHANGELOG.md` is updated under `[Unreleased]` with all notable changes.
- [ ] `backend/app/main.py` — `version=` string matches the new version.
- [ ] `frontend/package.json` — `"version"` field matches (optional but recommended).
- [ ] Any new environment variables are documented in `.env.example`.
- [ ] Any new Alembic migrations are committed and tested with `alembic upgrade head`.
- [ ] The `stack.yml` image tags are updated if you use fixed tags there.

---

## Cutting a Release

### 1. Update CHANGELOG

Move everything under `[Unreleased]` to a new version section:

```markdown
## [0.5.0] – 2026-06-01

### Added
- ...

## [Unreleased]
```

Update the comparison links at the bottom of `CHANGELOG.md`.

### 2. Commit the release prep

```bash
git add CHANGELOG.md backend/app/main.py frontend/package.json
git commit -m "chore: release v0.5.0"
```

### 3. Tag and push

```bash
git tag v0.5.0
git push origin main --tags
```

### What happens automatically

The `release.yml` workflow triggers on the `v*.*.*` tag and:

1. Builds the `backend` and `frontend` Docker images.
2. Pushes them to GitHub Container Registry (GHCR) as:
   ```
   ghcr.io/retttechsolutions/convoyplan/backend:0.5.0
   ghcr.io/retttechsolutions/convoyplan/backend:0.5
   ghcr.io/retttechsolutions/convoyplan/backend:latest
   ghcr.io/retttechsolutions/convoyplan/frontend:0.5.0
   ...
   ```
3. Creates a GitHub Release with auto-generated release notes from commit messages.

---

## Deploying an Update (Production / Portainer)

### Docker Compose (direct server)

```bash
# Pull new images
docker compose pull backend frontend

# Restart with zero-downtime (one service at a time)
docker compose up -d --no-deps backend
docker compose up -d --no-deps frontend
```

Alembic migrations run automatically on backend start via the `command` in `docker-compose.yml`.

### Portainer

1. Open the stack in Portainer → **Editor**.
2. Update the image tags to the new version (`backend:0.5.0`, `frontend:0.5.0`).
3. Click **Update the stack** → **Pull and redeploy**.

---

## Rolling Back

```bash
# Roll back to the previous image tag
docker compose up -d --no-deps -e BACKEND_IMAGE=ghcr.io/retttechsolutions/convoyplan/backend:0.4.0 backend
```

If the new release introduced a database migration, run `alembic downgrade -1` inside the backend container before rolling back the image:

```bash
docker compose exec backend alembic downgrade -1
```

---

## Hotfix Releases

For urgent bug fixes on a released version:

```bash
git checkout -b hotfix/v0.4.1 v0.4.0
# apply fix, commit
git tag v0.4.1
git push origin hotfix/v0.4.1 --tags
# cherry-pick or PR back to main
```
