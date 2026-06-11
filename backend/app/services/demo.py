"""Runtime toggle for ephemeral demo sessions.

The superadmin can switch the demo mode on/off in the admin panel; the value is
stored in system_settings and takes priority over the DEMO_ENABLED env var
(same pattern as the GitHub token).
"""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.settings import SystemSetting

DEMO_ENABLED_KEY = "demo.enabled"


async def get_demo_enabled_setting(db: AsyncSession) -> str | None:
    """Return the raw DB value ("true"/"false") or None when unset."""
    result = await db.execute(select(SystemSetting).where(SystemSetting.key == DEMO_ENABLED_KEY))
    setting = result.scalar_one_or_none()
    if setting and setting.value in ("true", "false"):
        return setting.value
    return None


async def is_demo_enabled(db: AsyncSession) -> bool:
    """Effective demo state: DB setting wins, env var DEMO_ENABLED is the fallback."""
    db_value = await get_demo_enabled_setting(db)
    if db_value is not None:
        return db_value == "true"
    return settings.demo_enabled


async def set_demo_enabled(db: AsyncSession, enabled: bool) -> None:
    """Persist the demo toggle in system_settings (caller commits via audit/commit)."""
    result = await db.execute(select(SystemSetting).where(SystemSetting.key == DEMO_ENABLED_KEY))
    setting = result.scalar_one_or_none()
    value = "true" if enabled else "false"
    if setting:
        setting.value = value
    else:
        db.add(SystemSetting(key=DEMO_ENABLED_KEY, value=value))
    await db.commit()
