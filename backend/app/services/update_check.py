"""
Shared update-state logic: which build is deployed, what the active release
channel's target is, and whether an update is available.

Used by two consumers:
  - the admin endpoint ``GET /api/admin/update-status`` (UI display), and
  - the update-notification background task (``app.services.update_notify``).

Also owns the settings that are mirrored to the shared ``update_status``
volume so the (DB-less) updater container can read them:
  - ``update.channel``  → /update_status/channel  ("stable" | "beta")
  - ``update.mode``     → /update_status/mode     ("auto" | "notify")
"""

from __future__ import annotations

import json
import logging
import os

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.settings import SystemSetting

logger = logging.getLogger(__name__)

STATUS_FILE = "/update_status/status.json"
CHANNEL_FILE = "/update_status/channel"
MODE_FILE = "/update_status/mode"

VALID_CHANNELS = ("stable", "beta")
# auto   → der Updater installiert verfügbare Updates selbstständig
# notify → keine automatische Installation; Superadmins werden per E-Mail
#          benachrichtigt und aktualisieren manuell über das Admin-Panel
VALID_MODES = ("auto", "notify")


# ── Release channel (stable / beta) ──────────────────────────────────────────

def env_channel() -> str:
    """The fallback channel from configuration, sanitised to a valid value."""
    return settings.update_channel if settings.update_channel in VALID_CHANNELS else "stable"


async def resolve_channel(db: AsyncSession) -> tuple[str, str]:
    """Return (channel, source) — the DB setting wins over the env fallback."""
    result = await db.execute(select(SystemSetting).where(SystemSetting.key == "update.channel"))
    setting = result.scalar_one_or_none()
    if setting and setting.value in VALID_CHANNELS:
        return setting.value, "db"
    return env_channel(), "env"


def write_channel_file(channel: str) -> None:
    """Persist the effective channel to the shared volume so the updater can
    read it. Best-effort: a non-writable volume must never break the request
    (the updater repairs the volume permissions on its next cycle)."""
    _write_shared_file(CHANNEL_FILE, channel)


# ── Update mode (auto / notify) ───────────────────────────────────────────────

def env_mode() -> str:
    """The fallback mode from configuration, sanitised to a valid value."""
    return settings.update_mode if settings.update_mode in VALID_MODES else "auto"


async def resolve_mode(db: AsyncSession) -> tuple[str, str]:
    """Return (mode, source) — the DB setting wins over the env fallback."""
    result = await db.execute(select(SystemSetting).where(SystemSetting.key == "update.mode"))
    setting = result.scalar_one_or_none()
    if setting and setting.value in VALID_MODES:
        return setting.value, "db"
    return env_mode(), "env"


def write_mode_file(mode: str) -> None:
    """Persist the effective mode to the shared volume so the updater knows
    whether it may install updates automatically ("auto") or must only wait
    for manual triggers ("notify")."""
    _write_shared_file(MODE_FILE, mode)


async def resolve_notify_on_auto(db: AsyncSession) -> tuple[bool, str]:
    """Optionale Erfolgs-Benachrichtigung im Modus "auto": (enabled, source).

    True → nach einer automatisch installierten Aktualisierung erhalten die
    Superadmins eine E-Mail. Das DB-Setting gewinnt über den Env-Fallback.
    """
    result = await db.execute(
        select(SystemSetting).where(SystemSetting.key == "update.notify_on_auto")
    )
    setting = result.scalar_one_or_none()
    if setting and setting.value in ("true", "false"):
        return setting.value == "true", "db"
    return settings.update_notify_on_auto, "env"


def _write_shared_file(path: str, value: str) -> None:
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            f.write(value)
    except OSError as exc:
        # Best-effort: a non-writable volume must not break the request. Log so
        # the cause is visible if the updater later ignores the setting.
        logger.warning("Cannot write shared file %s (value=%s): %s", path, value, exc)


# ── Update state ──────────────────────────────────────────────────────────────

async def resolve_github_token(db: AsyncSession) -> str:
    """GitHub token: DB setting takes priority over the env var."""
    github_token = settings.github_token
    db_token = await db.execute(select(SystemSetting).where(SystemSetting.key == "github.token"))
    db_setting = db_token.scalar_one_or_none()
    if db_setting and db_setting.value:
        github_token = db_setting.value
    return github_token


def read_deployed() -> tuple[str | None, str | None]:
    """(deployed_sha, deployed_at) from the updater's status file, falling back
    to the GIT_SHA baked into the image at build time."""
    deployed_sha = None
    deployed_at = None
    try:
        with open(STATUS_FILE) as f:
            data = json.load(f)
            deployed_sha = data.get("deployed_sha")
            deployed_at = data.get("deployed_at")
    except FileNotFoundError:
        # Normal direkt nach der Installation: der Updater hat noch keinen
        # Status geschrieben — Fallback auf den eingebauten GIT_SHA unten.
        pass
    except json.JSONDecodeError as exc:
        logger.debug("Status-Datei %s enthält kein gültiges JSON (%s) — Fallback auf GIT_SHA", STATUS_FILE, exc)

    if not deployed_sha:
        baked = os.environ.get("GIT_SHA", "")
        if baked and baked != "unknown":
            deployed_sha = baked[:7]
    return deployed_sha, deployed_at


async def fetch_update_state(db: AsyncSession) -> dict:
    """Compute the full update state for the active channel.

    Returns the dict served by GET /api/admin/update-status:
    deployed_sha, deployed_at, remote_sha, update_available, github_reachable,
    channel, latest_release, no_release, ahead_of_release.
    """
    deployed_sha, deployed_at = read_deployed()
    github_token = await resolve_github_token(db)

    # Release channel decides what "up to date" means: in "stable" we compare
    # against the latest published GitHub *release*; in "beta" against the
    # last successfully built :beta images. Keep the shared channel file in
    # sync so the updater container deploys the matching ref.
    channel, _ = await resolve_channel(db)
    write_channel_file(channel)

    remote_sha = None
    latest_release = None     # tag of the latest release (stable channel only)
    github_reachable = False
    no_release = False        # stable channel but the repo has no release yet
    ahead_of_release = False  # deployed build is NEWER than the latest release
    try:
        headers = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}
        if github_token:
            headers["Authorization"] = f"Bearer {github_token}"
        async with httpx.AsyncClient(timeout=10.0) as client:
            if channel == "beta":
                # Update-Ziel ist NICHT der main-HEAD, sondern der Commit des
                # letzten ERFOLGREICHEN :beta-Image-Builds: Der HEAD bewegt
                # sich schon beim Merge, die Images existieren aber erst,
                # wenn der beta-images-Workflow (~10-15 min) durch ist.
                # Sonst zeigt die UI minutenlang "Update verfügbar", obwohl
                # es noch nichts zu ziehen gibt.
                resp = await client.get(
                    f"https://api.github.com/repos/{settings.github_repo}"
                    "/actions/workflows/beta-images.yml/runs"
                    "?branch=main&status=success&per_page=1&exclude_pull_requests=true",
                    headers=headers,
                )
                if resp.is_success:
                    github_reachable = True
                    runs = (resp.json() or {}).get("workflow_runs") or []
                    if runs and runs[0].get("head_sha"):
                        remote_sha = runs[0]["head_sha"][:7]
            else:
                rel = await client.get(
                    f"https://api.github.com/repos/{settings.github_repo}/releases/latest",
                    headers=headers,
                )
                if rel.status_code == 404:
                    # GitHub is reachable, the repo simply has no release yet.
                    github_reachable = True
                    no_release = True
                elif rel.is_success:
                    github_reachable = True
                    latest_release = rel.json().get("tag_name")
                    if latest_release:
                        # Resolve the tag to its commit SHA so the comparison
                        # against deployed_sha is apples-to-apples.
                        commit = await client.get(
                            f"https://api.github.com/repos/{settings.github_repo}/commits/{latest_release}",
                            headers=headers,
                        )
                        if commit.is_success:
                            sha = commit.json().get("sha")
                            if sha:
                                remote_sha = sha[:7]

                        # SHA-Ungleichheit allein kennt keine Richtung: Eine
                        # Instanz, die vorher im Beta-Kanal lief, ist NEUER als
                        # das letzte Release — das ist kein verfügbares Update
                        # (und erst recht kein Grund für ein automatisches
                        # Downgrade). Die Compare-API liefert die Ancestry:
                        # "ahead" = deployed enthält das Release und mehr.
                        if (
                            remote_sha
                            and deployed_sha
                            and deployed_sha[:7] != remote_sha[:7]
                        ):
                            cmp_resp = await client.get(
                                f"https://api.github.com/repos/{settings.github_repo}"
                                f"/compare/{latest_release}...{deployed_sha[:7]}",
                                headers=headers,
                            )
                            if cmp_resp.is_success:
                                cmp_status = (cmp_resp.json() or {}).get("status")
                                if cmp_status in ("ahead", "identical"):
                                    ahead_of_release = True
    except Exception as exc:
        # Fail open: GitHub-Ausfälle oder Netzwerkfehler dürfen den Status-
        # Endpoint nie brechen — github_reachable bleibt dann False und die
        # UI zeigt "GitHub nicht erreichbar" statt eines Fehlers.
        logger.debug("Update-Status-Abfrage fehlgeschlagen: %s", exc)

    update_available = bool(
        deployed_sha
        and remote_sha
        and deployed_sha[:7] != remote_sha[:7]
        and not ahead_of_release
    )

    return {
        "deployed_sha": deployed_sha,
        "deployed_at": deployed_at,
        "remote_sha": remote_sha,
        "update_available": update_available,
        "github_reachable": github_reachable,
        "channel": channel,
        "latest_release": latest_release,
        "no_release": no_release,
        "ahead_of_release": ahead_of_release,
    }
