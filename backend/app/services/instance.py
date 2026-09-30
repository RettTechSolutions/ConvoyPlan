"""
Manages the installation's persistent instance ID and stored license key.

Generated once on first startup and stored in system_settings.
Used as the machine fingerprint for license binding.
"""
import uuid
from typing import TYPE_CHECKING

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.settings import SystemSetting

if TYPE_CHECKING:
    from app.services.license import LicenseInfo

_SETTING_KEY = "license.instance_id"
_LICENSE_KEY_SETTING = "license.key"


async def get_or_create_instance_id(db: AsyncSession) -> str:
    result = await db.execute(
        select(SystemSetting).where(SystemSetting.key == _SETTING_KEY)
    )
    row = result.scalar_one_or_none()
    if row:
        return row.value

    instance_id = str(uuid.uuid4())
    db.add(SystemSetting(key=_SETTING_KEY, value=instance_id))
    await db.commit()
    return instance_id


async def get_saved_license_key(db: AsyncSession) -> str:
    result = await db.execute(
        select(SystemSetting).where(SystemSetting.key == _LICENSE_KEY_SETTING)
    )
    row = result.scalar_one_or_none()
    return row.value if row else ""


async def save_license_key(db: AsyncSession, key: str) -> None:
    result = await db.execute(
        select(SystemSetting).where(SystemSetting.key == _LICENSE_KEY_SETTING)
    )
    row = result.scalar_one_or_none()
    if row:
        row.value = key
    else:
        db.add(SystemSetting(key=_LICENSE_KEY_SETTING, value=key))
    await db.commit()


async def aktuelle_lizenz(db: AsyncSession) -> "LicenseInfo":
    """Die Lizenz, die für diese Instanz gerade gilt.

    Dieselbe Reihenfolge wie im Lizenzwächter: ``LICENSE_KEY`` aus der
    Umgebung schlägt den gespeicherten Schlüssel. Ohne Cache — wer hier fragt,
    will den Stand jetzt (Anlegen einer Organisation, Anzeige im Portal), und
    das passiert selten genug."""
    from app.config import settings
    from app.services.license import validate_license

    key = settings.license_key or await get_saved_license_key(db)
    return validate_license(key, await get_or_create_instance_id(db))
