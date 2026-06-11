"""Runtime configuration for ephemeral demo sessions.

The superadmin can toggle the demo mode and adjust the session lifetime in the
admin panel; the values are stored in system_settings and take priority over
the DEMO_ENABLED / DEMO_SESSION_HOURS env vars (same pattern as the GitHub
token).
"""

from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.organization import Organization
from app.models.settings import SystemSetting

DEMO_ENABLED_KEY = "demo.enabled"
DEMO_SESSION_HOURS_KEY = "demo.session_hours"

# Bounds for the admin-configurable session lifetime (1 hour … 30 days).
MIN_SESSION_HOURS = 1
MAX_SESSION_HOURS = 720


async def _get_setting(db: AsyncSession, key: str) -> str | None:
    result = await db.execute(select(SystemSetting).where(SystemSetting.key == key))
    setting = result.scalar_one_or_none()
    return setting.value if setting else None


async def _upsert_setting(db: AsyncSession, key: str, value: str) -> None:
    result = await db.execute(select(SystemSetting).where(SystemSetting.key == key))
    setting = result.scalar_one_or_none()
    if setting:
        setting.value = value
    else:
        db.add(SystemSetting(key=key, value=value))


async def get_demo_enabled_setting(db: AsyncSession) -> str | None:
    """Return the raw DB value ("true"/"false") or None when unset."""
    value = await _get_setting(db, DEMO_ENABLED_KEY)
    return value if value in ("true", "false") else None


async def is_demo_enabled(db: AsyncSession) -> bool:
    """Effective demo state: DB setting wins, env var DEMO_ENABLED is the fallback."""
    db_value = await get_demo_enabled_setting(db)
    if db_value is not None:
        return db_value == "true"
    return settings.demo_enabled


async def set_demo_enabled(db: AsyncSession, enabled: bool) -> None:
    """Persist the demo toggle in system_settings."""
    await _upsert_setting(db, DEMO_ENABLED_KEY, "true" if enabled else "false")
    await db.commit()


async def get_demo_session_hours_setting(db: AsyncSession) -> int | None:
    """Return the DB-configured session lifetime, or None when unset/invalid."""
    value = await _get_setting(db, DEMO_SESSION_HOURS_KEY)
    if value is None:
        return None
    try:
        hours = int(value)
    except ValueError:
        return None
    return hours if MIN_SESSION_HOURS <= hours <= MAX_SESSION_HOURS else None


async def get_demo_session_hours(db: AsyncSession) -> int:
    """Effective session lifetime: DB setting wins, DEMO_SESSION_HOURS is the fallback."""
    db_value = await get_demo_session_hours_setting(db)
    return db_value if db_value is not None else settings.demo_session_hours


async def set_demo_session_hours(db: AsyncSession, hours: int) -> None:
    """Persist the session lifetime in system_settings (caller validates bounds)."""
    await _upsert_setting(db, DEMO_SESSION_HOURS_KEY, str(hours))
    await db.commit()


def effective_expiry(org: Organization, fallback_hours: int) -> datetime:
    """Expiry of a demo org: explicit demo_expires_at, or the legacy implicit TTL."""
    return org.demo_expires_at or (org.created_at + timedelta(hours=fallback_hours))
