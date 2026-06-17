"""
Public endpoint exposing the running build's version and an "update available"
hint derived live from the GitHub releases API.

GET /api/version  — no auth required
"""

from __future__ import annotations

import logging
import os
import time

import httpx
from fastapi import APIRouter
from pydantic import BaseModel

from app.config import settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/version", tags=["version"])

# Cache the latest-release lookup process-wide so the public endpoint never
# hammers the GitHub API regardless of request volume.
_LATEST_TTL = 3600  # seconds
_latest_cache: tuple[float, str | None] = (0.0, None)


class VersionResponse(BaseModel):
    version: str | None          # running build version, e.g. "0.9.0"
    sha: str | None              # git SHA the build was cut from
    latest: str | None           # latest release tag on GitHub, e.g. "0.9.1"
    update_available: bool       # True when latest is newer than version


class ChangelogResponse(BaseModel):
    version: str | None          # release version the notes belong to, e.g. "1.0.0"
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


def _normalize(v: str | None) -> tuple[int, ...] | None:
    """Parse a version string into a comparable tuple, ignoring a leading 'v',
    build metadata ("+sha") and pre-release suffixes ("-3-gabc")."""
    core = _core_str(v)
    if not core:
        return None
    try:
        return tuple(int(p) for p in core.split("."))
    except ValueError:
        return None


async def _fetch_latest() -> str | None:
    """Return the latest release tag from GitHub, cached for _LATEST_TTL.
    Fails open (returns None) so offline deployments behave gracefully."""
    global _latest_cache
    if not settings.update_check_enabled:
        return None

    now = time.monotonic()
    cached_at, cached = _latest_cache
    if now - cached_at < _LATEST_TTL and cached_at > 0:
        return cached

    latest: str | None = None
    try:
        headers = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        if settings.github_token:
            headers["Authorization"] = f"Bearer {settings.github_token}"
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                f"https://api.github.com/repos/{settings.github_repo}/releases/latest",
                headers=headers,
            )
        if resp.is_success:
            tag = resp.json().get("tag_name")
            if tag:
                latest = str(tag).lstrip("vV")
    except Exception:
        pass

    # Cache even on failure so a flaky network doesn't trigger a request storm;
    # the short TTL means we retry within the hour.
    _latest_cache = (now, latest)
    return latest


@router.get("", response_model=VersionResponse)
async def get_version() -> VersionResponse:
    raw_sha = os.environ.get("GIT_SHA", "unknown")
    sha = raw_sha[:7] if raw_sha and raw_sha != "unknown" else None

    version = settings.app_version or None
    latest = await _fetch_latest()

    cur, new = _normalize(version), _normalize(latest)
    update_available = bool(cur and new and new > cur)

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
