"""Collector für die Systemkennzahlen.

Läuft als Hintergrund-Task im Backend-Prozess (siehe ``app.main``): nur dort
liegt die In-Memory-Aktivitätsliste, aus der die Portalnutzung stammt — ein
separater Cron-Container könnte sie gar nicht sehen.

Der Loop macht drei Dinge:

1. jede ``SYSTEM_METRICS_INTERVAL`` Sekunden eine Stichprobe schreiben,
2. abgeschlossene Tage zu Tagesaggregaten verdichten (verpasste Tage werden
   nachgeholt, falls die Instanz zwischenzeitlich aus war),
3. Rohdaten und Aggregate außerhalb der Aufbewahrungsfristen löschen.

Fehler beenden den Loop nie: ein Ausfall der Überwachung darf die Anwendung
nicht mit in den Abgrund ziehen.

Zusätzlich als Einmal-Lauf aufrufbar: ``python -m app.jobs.metrics``.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

from app.config import settings
from app.database import get_db_session
from app.services import system_metrics

logger = logging.getLogger(__name__)

# Verdichtung und Aufräumen brauchen keinen eigenen Timer — beides läuft
# mitgeschleift, aber höchstens einmal pro Stunde.
_MAINTENANCE_INTERVAL_SECONDS = 3600


async def run_once(*, maintenance: bool = True) -> None:
    """Eine Stichprobe erheben und optional Verdichtung/Aufräumen ausführen."""
    async with get_db_session() as db:
        await system_metrics.collect_sample(db)
        if maintenance:
            await system_metrics.rollup_pending(db)
            await system_metrics.purge_old(db)


async def metrics_collector_loop() -> None:
    """Endlosschleife für den Lifespan des Backends."""
    if not settings.system_metrics_enabled:
        logger.info("Systemmetriken deaktiviert (SYSTEM_METRICS_ENABLED=false).")
        return

    interval = max(30, settings.system_metrics_interval)
    last_maintenance = 0.0

    # Erste Stichprobe direkt nach dem Start, damit die Übersicht nicht ein
    # Intervall lang leer bleibt. Kurzer Vorlauf, damit die Datenbank-
    # Migrationen des Entrypoints sicher durch sind.
    await asyncio.sleep(15)

    while True:
        try:
            now = asyncio.get_running_loop().time()
            do_maintenance = now - last_maintenance >= _MAINTENANCE_INTERVAL_SECONDS
            async with get_db_session() as db:
                await system_metrics.collect_sample(db)
                if do_maintenance:
                    written = await system_metrics.rollup_pending(db)
                    await system_metrics.purge_old(db)
                    last_maintenance = now
                    if written:
                        logger.info("Systemmetriken: %d Tagesaggregate verdichtet.", written)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.warning("Erfassung der Systemmetriken fehlgeschlagen", exc_info=True)
        await asyncio.sleep(interval)


async def _main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    if not settings.system_metrics_enabled:
        logger.info("Systemmetriken deaktiviert (SYSTEM_METRICS_ENABLED=false) — übersprungen.")
        return
    await run_once()
    logger.info("Stichprobe erfasst (%s).", datetime.now(timezone.utc).isoformat())


if __name__ == "__main__":
    asyncio.run(_main())
