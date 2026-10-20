"""Ein Tracker, der für einen laufenden Konvoi sendet, hält automatische Updates zurück.

Gezählt wird aus der Datenbank (``anwesenheit.aktive_tracker``): aktiv, in den letzten
fünf Minuten gemeldet, am Fahrzeug eines Konvois mit Status aktiv/läuft, nicht in einer
gesperrten Organisation (``tracker_sperre``). Verband und Organisation kommen aus ``test_tracker_geraete`` — dort steht der HLF in einem
laufenden und einem geplanten Konvoi, der MTW nur im laufenden.
"""

import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, update

from app.database import AsyncSessionLocal
from app.models.convoy import Convoy
from app.models.org_module import OrganizationModule
from app.models.ortungsgeraet import Ortungsgeraet
from app.services import anwesenheit
from tests.test_tracker_geraete import ohne_lizenz, org, reset_db_engine  # noqa: F401 — Fixtures

JETZT = datetime.now(timezone.utc)


async def _tracker(org, vehicle_id, *, gesehen, aktiv=True) -> uuid.UUID:
    async with AsyncSessionLocal() as db:
        geraet = Ortungsgeraet(
            organization_id=org.org_id, vehicle_id=vehicle_id, name="Tracker",
            aktiv=aktiv, zuletzt_gesehen=gesehen,
        )
        db.add(geraet)
        await db.commit()
        return geraet.id


async def _zaehlt(**kw) -> int:
    return await anwesenheit.aktive_tracker(JETZT, **kw)


async def test_ein_sendender_tracker_im_laufenden_konvoi_zaehlt(org):
    vorher = await _zaehlt()
    await _tracker(org, org.hlf, gesehen=JETZT - timedelta(seconds=60))
    # Der HLF steht in zwei Konvois, gezählt wird das Gerät einmal.
    assert await _zaehlt() == vorher + 1


async def test_ohne_kontakt_seit_fuenf_minuten_zaehlt_er_nicht(org):
    vorher = await _zaehlt()
    await _tracker(org, org.mtw, gesehen=JETZT - timedelta(seconds=anwesenheit.TRACKER_FRIST_S + 1))
    await _tracker(org, org.hlf, gesehen=None)
    assert await _zaehlt() == vorher


async def test_ein_gesperrter_tracker_zaehlt_nicht(org):
    vorher = await _zaehlt()
    await _tracker(org, org.mtw, gesehen=JETZT, aktiv=False)
    assert await _zaehlt() == vorher


async def test_nur_bei_laufendem_konvoi(org):
    await _tracker(org, org.mtw, gesehen=JETZT)
    mit = await _zaehlt()
    async with AsyncSessionLocal() as db:
        await db.execute(update(Convoy).where(Convoy.id == org.konvoi).values(status="completed"))
        await db.commit()
    # Der MTW steht nur im jetzt abgeschlossenen Konvoi.
    assert await _zaehlt() == mit - 1


async def test_tracker_einer_gesperrten_organisation_zaehlt_nicht(org):
    # Modul Tracker entzogen: das Gerät bekommt `schweigen`, also hält es auch nichts auf.
    from app.services import org_module

    await _tracker(org, org.mtw, gesehen=JETZT)
    mit = await _zaehlt()
    async with AsyncSessionLocal() as db:
        await org_module.setzen(db, org.org_id, {org_module.TRACKER: False})
        await db.commit()
    try:
        assert await _zaehlt() == mit - 1
    finally:
        async with AsyncSessionLocal() as db:
            await db.execute(
                delete(OrganizationModule).where(OrganizationModule.organization_id == org.org_id)
            )
            await db.commit()


async def test_ohne_lizenz_zaehlt_kein_tracker(org, ohne_lizenz):
    await _tracker(org, org.mtw, gesehen=JETZT)
    assert await _zaehlt() == 0
