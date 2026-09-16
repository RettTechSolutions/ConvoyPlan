"""Der Laufzeitschalter für den MCP-Server.

Bis hierher war ``MCP_ENABLED`` ausschließlich eine Umgebungsvariable: beim
Start entschieden, danach unveränderlich. Das hatte einen handfesten Grund —
bei abgeschaltetem MCP wurde **keine einzige Route montiert**, es gab also
nichts, was versehentlich offenstehen konnte. Ein Knopf im Portal hätte
normalerweise geheißen: alles ist immer montiert und antwortet nur mit 404.

Diese Zusage bleibt trotzdem bestehen, weil der Schalter die Routen
tatsächlich **entfernt** statt sie zu verstecken (siehe ``app/mcp/mount.py``).
Abgeschaltet gibt es weder ``/mcp`` noch die Well-Known-Dokumente — nicht als
404 eines Handlers, sondern weil keine Route passt. Genau das prüft
``tests/test_mcp_toggle.py``.

Gespeichert wird wie beim Demo-Modus und beim GitHub-Token: der Wert in
``system_settings`` hat Vorrang, die Umgebungsvariable ist der Rückfall. Wer
``MCP_ENABLED=true`` gesetzt hat, behält sein Verhalten, bis im Portal etwas
anderes eingestellt wird.
"""
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.settings import SystemSetting

MCP_ENABLED_KEY = "mcp.enabled"


async def get_mcp_enabled_setting(db: AsyncSession) -> str | None:
    """Der rohe Wert aus der Datenbank ("true"/"false"), oder None."""
    result = await db.execute(
        select(SystemSetting).where(SystemSetting.key == MCP_ENABLED_KEY)
    )
    setting = result.scalar_one_or_none()
    value = setting.value if setting else None
    return value if value in ("true", "false") else None


async def is_mcp_enabled(db: AsyncSession) -> bool:
    """Der geltende Zustand: Datenbank schlägt Umgebungsvariable."""
    db_value = await get_mcp_enabled_setting(db)
    if db_value is not None:
        return db_value == "true"
    return settings.mcp_enabled


async def set_mcp_enabled(db: AsyncSession, enabled: bool) -> None:
    """Den Schalter dauerhaft umlegen."""
    result = await db.execute(
        select(SystemSetting).where(SystemSetting.key == MCP_ENABLED_KEY)
    )
    setting = result.scalar_one_or_none()
    if setting:
        setting.value = "true" if enabled else "false"
    else:
        db.add(SystemSetting(key=MCP_ENABLED_KEY, value="true" if enabled else "false"))
    await db.commit()
