"""Ein Fahrer-Link am echten Kanal (``track_ws``) hält automatische Updates zurück.

Die Regel prüft ``test_update_bei_anwesenheit.py`` ohne Datenbank; hier geht es um
die Verdrahtung: ein Fahrer-Link zählt, solange er verbunden ist, ein Lese-Link
gar nicht. Verbindungen und Verband kommen aus ``test_fahrzeug_belegung_kanal``.
"""

import pytest
from sqlalchemy import update

from app.database import AsyncSessionLocal
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


async def test_verbundener_fahrer_link_zaehlt(verband, frische_fahrer_links):
    ws, task = await _verbinden(verband.slug, [], APP)
    assert frische_fahrer_links.anzahl() == 1
    ws.trennen()
    await _beendet(task)
    # Nach dem Abriss zählt er weiter — fünf Minuten Nachlauf.
    assert frische_fahrer_links.anzahl() == 1


async def test_lese_link_zaehlt_nicht(verband, frische_fahrer_links):
    async with AsyncSessionLocal() as db:
        await db.execute(
            update(ConvoyShareLink)
            .where(ConvoyShareLink.slug == verband.slug)
            .values(scope="track")
        )
        await db.commit()
    ws, task = await _verbinden(verband.slug, [{"type": "status", "vehicle_id": verband.kdow}], APP)
    assert frische_fahrer_links.anzahl() == 0
    ws.trennen()
    await _beendet(task)
    assert frische_fahrer_links.anzahl() == 0
