"""Jahresdeckel für HERE-SmartMaps-Kachelanfragen (Raster Tile API v3).

Kartenkacheln entstehen in Bürsten (20–50 Anfragen pro Kartenschwenk), im
Gegensatz zur Adresssuche (`geocoding.py`), die pro Anfrage synchron in
``system_settings`` schreibt. Ein Sync-Commit pro Tile wäre unnötige DB-Last,
deshalb zählt dieser Service in einem In-Memory-Zähler und flusht periodisch
(``smartmaps_flush_loop``, gestartet in ``app.main._lifespan``).

Limitierung: der Zähler ist pro Prozess und überlebt keinen Neustart ohne
vorherigen Flush. Das Backend läuft laut docker-compose.yml als Single-Process
(kein ``--workers``, keine ``deploy.replicas``) — für einen künftigen
Multi-Replica-Betrieb bräuchte es einen shared Store (Redis o.ä.), analog zur
in ``rate_limit.py`` dokumentierten Einschränkung.
"""
import asyncio
import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.settings import SystemSetting

logger = logging.getLogger(__name__)

_USAGE_KEY_PREFIX = "smartmaps.tile_usage"

# Jahr ("YYYY") -> zuletzt aus der DB gelesener Stand.
_flushed: dict[str, int] = {}
# Jahr -> seit dem letzten Flush reservierte, noch nicht geschriebene Anfragen.
_pending: dict[str, int] = {}
_lock = asyncio.Lock()


def usage_key(year: str) -> str:
    """system_settings-Schlüssel für den HERE-Tile-Zähler eines Jahres ("YYYY")."""
    return f"{_USAGE_KEY_PREFIX}.{year}"


async def _load_flushed(db: AsyncSession, year: str) -> int:
    row = (
        await db.execute(select(SystemSetting).where(SystemSetting.key == usage_key(year)))
    ).scalar_one_or_none()
    if row is None:
        return 0
    try:
        return int(row.value)
    except (TypeError, ValueError):
        return 0


async def reserve_tile_quota(db: AsyncSession, year: str, limit: int) -> bool:
    """Eine HERE-Tile-Anfrage im Jahresbudget verbuchen.

    Gibt ``True`` zurück und zählt hoch, wenn noch Budget frei ist; ``False``,
    wenn der Deckel erreicht ist (Aufrufer fällt dann auf OSM zurück).
    ``limit <= 0`` deaktiviert den Deckel (immer ``True``, kein Zähler).
    """
    if limit <= 0:
        return True

    async with _lock:
        if year not in _flushed:
            _flushed[year] = await _load_flushed(db, year)
        used = _flushed[year] + _pending.get(year, 0)
        if used >= limit:
            return False
        _pending[year] = _pending.get(year, 0) + 1
        return True


async def flush_pending(db: AsyncSession) -> None:
    """Alle seit dem letzten Aufruf reservierten Anfragen in die DB schreiben."""
    async with _lock:
        to_flush = {year: count for year, count in _pending.items() if count > 0}
        if not to_flush:
            return
        for year, count in to_flush.items():
            key = usage_key(year)
            row = (
                await db.execute(select(SystemSetting).where(SystemSetting.key == key))
            ).scalar_one_or_none()
            new_total = _flushed.get(year, 0) + count
            if row is not None:
                row.value = str(new_total)
            else:
                db.add(SystemSetting(key=key, value=str(new_total)))
            _flushed[year] = new_total
            _pending[year] = 0
        await db.commit()


async def smartmaps_flush_loop() -> None:
    """Background-Loop: schreibt alle 30s den In-Memory-Zähler in die DB.

    Gestartet in ``app.main._lifespan`` neben ``update_notify_loop`` (gleiches
    Muster: sleep-Loop, CancelledError durchreichen, sonst weiterlaufen).
    """
    from app.database import AsyncSessionLocal

    interval = 30
    while True:
        await asyncio.sleep(interval)
        try:
            async with AsyncSessionLocal() as db:
                await flush_pending(db)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("SmartMaps-Tile-Zähler-Flush fehlgeschlagen")


def reset() -> None:
    """Zähler zurücksetzen (nur für Tests)."""
    _flushed.clear()
    _pending.clear()
