"""Ein Fahrer-Link am echten Kanal (``track_ws``) hält automatische Updates zurück.

Die Regel prüft ``test_update_bei_anwesenheit.py`` ohne Datenbank; hier geht es um
die Verdrahtung: ein Fahrer-Link zählt, solange er verbunden ist und sein Konvoi
aktiv ist oder läuft und seine Organisation nicht gesperrt ist, ein Lese-Link gar nicht. Verbindungen und Verband kommen
aus ``test_fahrzeug_belegung_kanal``.
"""

import uuid
from datetime import date, timedelta

import pytest
from sqlalchemy import delete, update

from app.database import AsyncSessionLocal
from app.models.convoy import Convoy
from app.models.org_plan import OrganizationPlan
from app.models.organization import Organization
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


async def test_fahrer_link_einer_gesperrten_organisation_zaehlt_nicht(verband, frische_fahrer_links):
    # Plan abgelaufen, Kulanz vorbei: die Organisation ist nur noch lesbar
    # (org_plan.ist_gesperrt) — ein offener Fahrer-Link hält dann kein Update auf.
    marker = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        org = Organization(name=f"Gesperrt {marker}", slug=f"g{marker[:7]}", owner_id=verband.user_id)
        db.add(org)
        await db.flush()
        org_id = org.id
        await db.execute(
            update(Convoy).where(Convoy.id == verband.convoy_id).values(
                organization_id=org_id, status="running",
            )
        )
        await db.commit()
    try:
        ws, task = await _verbinden(verband.slug, [], APP)
        assert await _zaehlt(frische_fahrer_links) == 1
        async with AsyncSessionLocal() as db:
            db.add(OrganizationPlan(
                organization_id=org_id, plan="basis",
                valid_until=date.today() - timedelta(days=60),
            ))
            await db.commit()
        assert await _zaehlt(frische_fahrer_links) == 0
        ws.trennen()
        await _beendet(task)
    finally:
        async with AsyncSessionLocal() as db:
            await db.execute(delete(OrganizationPlan).where(OrganizationPlan.organization_id == org_id))
            await db.execute(
                update(Convoy).where(Convoy.id == verband.convoy_id).values(organization_id=None)
            )
            await db.execute(delete(Organization).where(Organization.id == org_id))
            await db.commit()
