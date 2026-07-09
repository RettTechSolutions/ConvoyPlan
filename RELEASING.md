# Release Process

This document describes how to cut a new release of ConvoyPlan.

---

## Versioning

ConvoyPlan uses a calendar-based scheme **`YYYY.MASTER.FIX`** (e.g. `2026.1.1`):

- **`YYYY`** – the calendar year of the release (e.g. `2026`).
- **`MASTER`** – the master release: incremented for each significant feature
  release within the year. Resets to `1` when the year rolls over.
- **`FIX`** – the fix/beta release: incremented for bug fixes, security patches
  and Dependabot waves on top of a master release.

> **History:** ConvoyPlan previously used Semantic Versioning (`MAJOR.MINOR.PATCH`).
> The scheme switched after `1.0.2`; the first release under the new scheme is
> `2026.1.1`. Tags are still prefixed with `v` (`v2026.1.1`), and the version
> comparison used for the "update available" hint is a plain component-wise
> numeric compare, so ordering across the switch is preserved (`2026.1.1` sorts
> above `1.0.2`).

---

## Pre-release Checklist

Before tagging a release, verify:

- [ ] All CI checks pass on `main` (`ci.yml`: backend tests, frontend type check, Docker build).
- [ ] `CHANGELOG.md` — the `[Unreleased]` block has been moved to a new `[X.Y.Z]` section and the comparison links at the bottom are updated.
- [ ] `backend` version — injected automatically at build time from the git tag via `APP_VERSION` (`backend/app/config.py: app_version`); no manual edit needed.
- [ ] `frontend/package.json` — `"version"` field matches the new version (also update `frontend/package-lock.json`).
- [ ] Any new environment variables are documented in `.env.example`.
- [ ] Any new Alembic migrations are committed and tested with `alembic upgrade head`.
- [ ] The `stack.yml` image tags are updated if you use fixed tags there.

---

## Cutting a Release

### 1. Update CHANGELOG

Move everything under `[Unreleased]` to a new version section:

```markdown
## [2026.1.1] – 2026-07-09

### Added
- ...

## [Unreleased]
```

Update the comparison links at the bottom of `CHANGELOG.md`.

### 2. Commit the release prep

```bash
git add CHANGELOG.md backend/app/main.py frontend/package.json
git commit -m "chore: release v2026.1.1"
```

### 3. Tag and push

```bash
git tag v2026.1.1
git push origin main --tags
```

> **Note:** Releases are strictly tag-driven. Merging to `main` does **not**
> build `:latest` or deploy anything — only pushing a `v*.*.*` tag (or a manual
> `workflow_dispatch`) does. This keeps changes from flowing straight onto
> production instances unreviewed.
>
> **Exception — Dependabot waves:** once the merge queue has drained a batch of
> auto-merged Dependabot PRs (patch/minor only, all CI checks green),
> `auto-release.yml` automatically tags the next **fix** version (bumps the
> `FIX` component, e.g. `v2026.1.1 → v2026.1.2`) and dispatches the release
> workflow. Human merges never trigger this — but any unreleased commits
> already sitting on `main` ship with that fix release.
>
> **Beta channel:** every push to `main` additionally builds `:beta` images
> (`beta-images.yml`). These are only pulled by instances whose admin
> explicitly switched the update channel to "Beta" — `:latest` and the stable
> channel remain strictly release-tag-driven.

### What happens automatically

The `release.yml` workflow triggers on the `v*.*.*` tag and:

1. Builds the `backend` and `frontend` Docker images.
2. Pushes them to GitHub Container Registry (GHCR) as:
   ```
   ghcr.io/retttechsolutions/convoyplan/backend:2026.1.1
   ghcr.io/retttechsolutions/convoyplan/backend:2026.1
   ghcr.io/retttechsolutions/convoyplan/backend:latest
   ghcr.io/retttechsolutions/convoyplan/frontend:2026.1.1
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
2. Update the image tags to the new version (`backend:2026.1.1`, `frontend:2026.1.1`).
3. Click **Update the stack** → **Pull and redeploy**.

---

## Rolling Back

```bash
# Roll back to the previous image tag
docker compose up -d --no-deps -e BACKEND_IMAGE=ghcr.io/retttechsolutions/convoyplan/backend:1.0.2 backend
```

If the new release introduced a database migration, run `alembic downgrade -1` inside the backend container before rolling back the image:

```bash
docker compose exec backend alembic downgrade -1
```

---

## Hotfix Releases

For urgent bug fixes on a released version, bump the `FIX` component:

```bash
git checkout -b hotfix/v2026.1.2 v2026.1.1
# apply fix, commit
git tag v2026.1.2
git push origin hotfix/v2026.1.2 --tags
# cherry-pick or PR back to main
```
