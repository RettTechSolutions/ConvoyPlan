"""
Public endpoint exposing the running build's version and an "update available"
hint derived live from the GitHub releases API.

GET /api/version  — no auth required
"""

from __future__ import annotations

import os
import time

import httpx
from fastapi import APIRouter
from pydantic import BaseModel

from app.config import settings

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


def _normalize(v: str | None) -> tuple[int, ...] | None:
    """Parse a version string into a comparable tuple, ignoring a leading 'v',
    build metadata ("+sha") and pre-release suffixes ("-3-gabc")."""
    if not v:
        return None
    core = v.lstrip("vV").split("+")[0].split("-")[0]
    parts = core.split(".")
    if not parts or not parts[0].isdigit():
        return None
    try:
        return tuple(int(p) for p in parts)
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
