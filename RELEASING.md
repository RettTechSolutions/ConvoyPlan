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
> If a master release is **prepared but not tagged** — `frontend/package.json`
> names a version above the latest stable tag that has no tag of its own — the
> wave tags *that* version instead of bumping `FIX`. The prepared state would
> ship either way; this only keeps its number. (On 2026-09-30 the prepared
> `2026.7.0` went out as `v2026.6.2` because of exactly this gap.) So bumping
> `frontend/package.json` is the point of no return: the next Dependabot wave
> releases it. Bump it in the release-prep commit, not earlier.
>
> **Update channels (stable / beta / nightly):** instances pick one in the admin
> panel (Admin → Software-Update):
> - **stable** — published releases only, floating `:latest`.
> - **beta** — numbered pre-releases (release candidates, `v2026.2.1-beta.N`),
>   floating `:beta`. See "Cutting a Beta Pre-Release" below.
> - **nightly** — every push to `main` builds `:nightly` images (`nightly-images.yml`);
>   for developers/testers who want each commit. `:latest` and `:beta` are never
>   moved by a main push — they stay strictly release-tag-driven.

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

`:latest` and the GitHub "Latest" flag move **only for the highest version**
(numeric sort, so `2026.10` > `2026.9`). A fix release on an older LTS line
never pulls stable instances back to that line.

---

## Cutting a Beta Pre-Release

Beta pre-releases are numbered release candidates for the next version — for
targeted testing before a version goes stable to everyone. They are tagged with
a `-beta.N` suffix and published as a GitHub **pre-release**:

```bash
git tag v2026.2.1-beta.1
git push origin v2026.2.1-beta.1
```

`release.yml` detects the `-` suffix and:

1. Builds the versioned images (`…/backend:2026.2.1-beta.1`) plus the floating
   **`:beta`** tag.
2. Does **not** move `:latest` or `2026.2` — stable instances are untouched
   (GitHub `/releases/latest`, which the stable channel reads, ignores
   pre-releases).
3. Publishes a GitHub Release flagged `prerelease: true`.

**Invariant (contract):** a pre-release ⟺ its tag contains `-beta.` **and** it
is marked as a GitHub pre-release. The updaters detect the newest beta by the
`-beta.` tag naming; keep that convention.

Instances on the **beta** channel (Admin → Software-Update) then pull `:beta`
automatically. `auto-release.yml` never touches pre-release tags (it only bumps
the `FIX` component of the latest *stable* tag).

> **One-time transition (3-channel rollout):** the old "beta" channel (every
> commit) is renamed "nightly"; the DB migration flips existing
> `update.channel=beta` rows to `nightly`. Because instances run the *old*
> updater until they update once, they can't auto-recover after the workflow
> rename — bootstrap them: (1) dispatch `nightly-images.yml` once so `:nightly`
> exists, (2) cut a `v2026.x.y-beta.1` so `:beta` rebuilds with the new
> updater/backend, (3) on each existing beta instance hit "Jetzt updaten" once —
> it pulls the refreshed image, runs the migration (channel → nightly) and from
> then on tracks `:nightly` automatically. Instances that set the channel purely
> via `UPDATE_CHANNEL=beta` must switch that env to `UPDATE_CHANNEL=nightly`.

---

## LTS Lines

The **LTS** update channel follows one held version line for 12 months: security
and bug fixes only, no new features. It is part of the maintenance contract and
unlocked per instance by `lts_until` in the licence key (Lizenzmanager).

A line is a branch `lts/<YEAR>.<MASTER>`. The **highest** such branch is the
current line — updaters and the admin UI read it from GitHub, so starting a new
line moves every LTS instance over without any change on the instances. One
line per year; the previous line ends when the next one starts.

**Start a line** — create the branch *before* tagging its first release on it:

```bash
git branch lts/2026.8 v2026.8.0     # or from main before tagging v2026.8.0
git push origin lts/2026.8
```

If the release is already tagged, the next release on the line sets `:lts`;
to set it right away, re-run `release.yml` for that tag (workflow_dispatch).

**Ship a fix on the line** — backport to the branch and tag there:

```bash
git checkout lts/2026.8
git cherry-pick <sha-from-main>
git tag v2026.8.3 && git push origin lts/2026.8 v2026.8.3
```

`release.yml` recognises a release whose `<YEAR>.<MASTER>` matches the current
line and points the floating **`:lts`** tag of all five images at its digests
(via `imagetools`, because `build-or-reuse` sets no tags on a reused image).
If the version is not the highest overall, `:latest` and "Latest" stay put.

**Contract:** LTS releases are `v<LINE>.<FIX>` without suffix; the updaters pick
the highest `FIX` on the line. Pre-release tags never count.

---

## Image Signatures (Sigstore / cosign)

Every image pushed by `release.yml` and `nightly-images.yml` is signed
**keyless** with cosign. The signing identity is the workflow itself (an OIDC
token from GitHub Actions exchanged for a short-lived Fulcio certificate) —
there is no private key in the repo, in a secret, or on anyone's laptop, and
nothing to rotate.

Signed is the **digest**, not the tag. Tags move, digests don't, so one
signature covers every tag pointing at that manifest.

Verify a published image:

```bash
cosign verify \
  --certificate-identity-regexp '^https://github.com/RettTechSolutions/ConvoyPlan/' \
  --certificate-oidc-issuer https://token.actions.githubusercontent.com \
  ghcr.io/retttechsolutions/convoyplan/backend:latest
```

The same five images are covered: `backend`, `frontend`, `graphhopper`,
`updater`, `osmium`.

> **Note:** the `--certificate-identity-regexp` deliberately matches the whole
> repository, not one workflow file — `release.yml` and `nightly-images.yml`
> both sign, and a rename must not silently invalidate every signature. It does
> mean any workflow *in this repository* can sign, which is why changes under
> `.github/workflows/` belong under review.

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
