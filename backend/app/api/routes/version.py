"""
Public endpoint exposing the running build's git SHA and version.

GET /api/version  — no auth required
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter(prefix="/version", tags=["version"])

_STATUS_JSON = Path("/update_status/status.json")


class VersionResponse(BaseModel):
    sha: str | None
    version: str | None


def _read_version() -> str | None:
    """Try to read the deployed version from the update-status JSON file."""
    try:
        if _STATUS_JSON.exists():
            data = json.loads(_STATUS_JSON.read_text())
            sha = data.get("deployed_sha") or ""
            if sha and sha != "unknown":
                return sha[:7]
    except Exception:
        pass
    return None


@router.get("", response_model=VersionResponse)
async def get_version() -> VersionResponse:
    raw_sha = os.environ.get("GIT_SHA", "unknown")
    sha = raw_sha[:7] if raw_sha and raw_sha != "unknown" else raw_sha

    version = _read_version()
    return VersionResponse(sha=sha, version=version)
