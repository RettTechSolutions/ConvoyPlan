"""
Public endpoint exposing the running build's version and an "update available"
hint. The hint honours the active release channel (stable / beta / nightly) by
reusing the same update-state logic as the admin panel, so a nightly or beta
instance is never falsely compared against the latest *stable* release.

GET /api/version  — no auth required
"""

from __future__ import annotations

import logging
import os
import time

import httpx
from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import TokenData, get_optional_token_data
from app.config import settings
from app.database import get_db
from app.services.update_check import fetch_update_state, resolve_channel

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/version", tags=["version"])

# Cache the changelog lookup TTL, shared with the update-state cache below, so
# the public endpoint never hammers the GitHub API regardless of request volume.
_LATEST_TTL = 3600  # seconds

# The "update available" hint reuses the same channel-aware update-state logic
# as the admin panel (stable → latest release, beta → latest pre-release,
# nightly → last successful nightly build). Because that logic performs several
# GitHub calls, cache the computed state per channel with a short TTL so the
# public, high-traffic footer request does not trigger a GitHub call every time.
_STATE_TTL = 600  # seconds
_state_cache: dict[str, tuple[float, dict]] = {}


class VersionResponse(BaseModel):
    version: str | None          # running build version, e.g. "2026.1.1"
    sha: str | None              # git SHA the build was cut from
    latest: str | None           # latest release tag on GitHub, e.g. "2026.1.2"
    update_available: bool       # True when latest is newer than version


class ChangelogResponse(BaseModel):
    version: str | None          # release version the notes belong to, e.g. "2026.1.1"
    name: str | None             # release title on GitHub
    body: str | None             # release notes (markdown)
    html_url: str | None         # link to the release on GitHub
    published_at: str | None     # ISO timestamp of the release


# Cache the changelog lookup per version so repeated page loads after a version
# bump don't hammer the GitHub API.
_changelog_cache: dict[str, tuple[float, ChangelogResponse]] = {}


def _core_str(v: str | None) -> str | None:
    """Return the bare "x.y.z" core of a version, dropping a leading 'v', build
    metadata ("+sha") and pre-release/describe suffixes ("-3-gabc")."""
    if not v:
        return None
    core = v.lstrip("vV").split("+")[0].split("-")[0].strip()
    parts = core.split(".")
    if not parts or not parts[0].isdigit():
        return None
    return core


async def _cached_update_state(db: AsyncSession, channel: str) -> dict | None:
    """The channel-aware update state (see app.services.update_check), cached
    per channel for _STATE_TTL. Fails open (returns None) so offline / air-
    gapped deployments and GitHub outages behave gracefully."""
    now = time.monotonic()
    cached = _state_cache.get(channel)
    if cached and now - cached[0] < _STATE_TTL:
        return cached[1]

    try:
        state = await fetch_update_state(db)
    except Exception:
        # fetch_update_state already fails open internally; this only guards the
        # surrounding DB/resolve calls so the public endpoint never errors.
        logger.debug("Update-Status-Abfrage (öffentlich) fehlgeschlagen", exc_info=True)
        return None

    _state_cache[channel] = (now, state)
    return state


async def _resolve_update_hint(db: AsyncSession) -> tuple[str | None, bool]:
    """Return (latest, update_available) for the footer hint, honouring the
    active release channel so a nightly/beta instance is never falsely told a
    newer *stable* release is available. Fails open (no hint) when the update
    check is disabled or GitHub is unreachable.

    Unlike a plain version-string comparison, this reuses the admin panel's
    SHA-ancestry logic: stable → latest release, beta → latest pre-release,
    nightly → last successful nightly build, and it suppresses the hint when the
    running build is actually *ahead* of the channel target."""
    if not settings.update_check_enabled:
        return None, False

    channel, _ = await resolve_channel(db)
    state = await _cached_update_state(db, channel)
    if not state:
        return None, False

    update_available = bool(state.get("update_available"))
    # stable/beta expose a release tag; nightly has none, so fall back to the
    # target commit SHA as the human-readable "latest" marker.
    latest = state.get("latest_release") or state.get("remote_sha")
    return latest, update_available


@router.get("", response_model=VersionResponse)
async def get_version(
    db: AsyncSession = Depends(get_db),
    viewer: TokenData | None = Depends(get_optional_token_data),
) -> VersionResponse:
    """The endpoint stays public (the login page and the update hint need it),
    but anonymous callers only see the release version — not the exact build.

    `settings.app_version` is a `git describe` string, so for a build between
    tags it reads e.g. "2026.1.1-4-g37b9dad": that tells an unauthenticated
    visitor the instance runs unreleased code and which commit it is, which
    narrows a search for applicable fixes. Signed-in users keep the precise
    build — support and the admin panel need it."""
    authenticated = viewer is not None

    raw_sha = os.environ.get("GIT_SHA", "unknown")
    sha = raw_sha[:7] if authenticated and raw_sha and raw_sha != "unknown" else None

    version = settings.app_version or None
    if not authenticated:
        version = _core_str(version)
    latest, update_available = await _resolve_update_hint(db)

    return VersionResponse(
        version=version,
        sha=sha,
        latest=latest,
        update_available=update_available,
    )


async def _fetch_release(core: str) -> ChangelogResponse | None:
    """Fetch the GitHub release matching version core "x.y.z". Tries the
    'v'-prefixed tag first, then the bare tag. Fails open (None) so offline
    deployments behave gracefully."""
    if not settings.update_check_enabled:
        return None

    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if settings.github_token:
        headers["Authorization"] = f"Bearer {settings.github_token}"

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            for tag in (f"v{core}", core):
                resp = await client.get(
                    f"https://api.github.com/repos/{settings.github_repo}/releases/tags/{tag}",
                    headers=headers,
                )
                if resp.is_success:
                    data = resp.json()
                    return ChangelogResponse(
                        version=core,
                        name=data.get("name") or data.get("tag_name"),
                        body=data.get("body"),
                        html_url=data.get("html_url"),
                        published_at=data.get("published_at"),
                    )
    except Exception:
        # Fail open: the changelog is a nice-to-have, so a GitHub outage or
        # network error must never surface to the client. Log at debug for
        # troubleshooting and fall through to None.
        logger.debug("Changelog lookup for %s failed", core, exc_info=True)
    return None


@router.get("/changelog", response_model=ChangelogResponse)
async def get_changelog() -> ChangelogResponse:
    """Release notes for the currently running version, sourced live from the
    GitHub releases API. Used by the client to show a one-time "what's new"
    dialog after a version upgrade. Cached per version."""
    version = settings.app_version or None
    core = _core_str(version)
    empty = ChangelogResponse(
        version=core, name=None, body=None, html_url=None, published_at=None
    )
    if not core:
        return empty

    now = time.monotonic()
    cached = _changelog_cache.get(core)
    if cached and now - cached[0] < _LATEST_TTL:
        return cached[1]

    result = await _fetch_release(core) or empty
    # Cache successful lookups; on failure keep a short-lived empty so a flaky
    # network doesn't trigger a request storm but we still retry within the hour.
    _changelog_cache[core] = (now, result)
    return result
