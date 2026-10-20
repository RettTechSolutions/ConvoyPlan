"""Ein Fahrer-Link am echten Kanal (``track_ws``) hält automatische Updates zurück.

Die Regel prüft ``test_update_bei_anwesenheit.py`` ohne Datenbank; hier geht es um
die Verdrahtung: ein Fahrer-Link zählt, solange er verbunden ist und sein Konvoi
aktiv ist oder läuft, ein Lese-Link gar nicht. Verbindungen und Verband kommen
aus ``test_fahrzeug_belegung_kanal``.
"""

import pytest
from sqlalchemy import update

from app.database import AsyncSessionLocal
from app.models.convoy import Convoy
from app.models.share_link import ConvoyShareLink
from app.services import anwesenheit
from tests.test_fahrzeug_belegung_kanal import (  # noqa: F401 — Fixtures
    APP,
    _beendet,
    _verbinden,
    frische_belegungen,
    reset_db_engine,
    verband,
)


@pytest.fixture(autouse=True)
def frische_fahrer_links(monkeypatch):
    links = anwesenheit.FahrerLinks()
    monkeypatch.setattr(anwesenheit, "fahrer_links", links)
    return links


async def _status(ids, status: str) -> None:
    async with AsyncSessionLocal() as db:
        await db.execute(update(Convoy).where(Convoy.id == ids.convoy_id).values(status=status))
        await db.commit()


async def _zaehlt(links: anwesenheit.FahrerLinks) -> int:
    """Wie die Schleife: laufende Konvois aus der Datenbank, dann zählen."""
    return links.anzahl(await anwesenheit.laufende_konvois(links.konvois()))


async def test_fahrer_link_zaehlt_erst_wenn_der_konvoi_laeuft(verband, frische_fahrer_links):
    ws, task = await _verbinden(verband.slug, [], APP)
    # Ein Konvoi in Planung hält kein Update auf, auch mit offenem Fahrer-Link.
    assert await _zaehlt(frische_fahrer_links) == 0
    for status in ("active", "running"):
        await _status(verband, status)
        assert await _zaehlt(frische_fahrer_links) == 1, status
    ws.trennen()
    await _beendet(task)
    # Nach dem Abriss zählt er weiter — fünf Minuten Nachlauf.
    assert await _zaehlt(frische_fahrer_links) == 1
    await _status(verband, "completed")
    assert await _zaehlt(frische_fahrer_links) == 0


async def test_lese_link_zaehlt_nicht(verband, frische_fahrer_links):
    await _status(verband, "running")
    async with AsyncSessionLocal() as db:
        await db.execute(
            update(ConvoyShareLink)
            .where(ConvoyShareLink.slug == verband.slug)
            .values(scope="track")
        )
        await db.commit()
    ws, task = await _verbinden(verband.slug, [{"type": "status", "vehicle_id": verband.kdow}], APP)
    assert await _zaehlt(frische_fahrer_links) == 0
    ws.trennen()
    await _beendet(task)
    assert await _zaehlt(frische_fahrer_links) == 0
