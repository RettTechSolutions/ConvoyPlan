"""Ein Tracker, der für einen laufenden Konvoi sendet, hält automatische Updates zurück.

Gezählt wird aus der Datenbank (``anwesenheit.aktive_tracker``): aktiv, in den letzten
fünf Minuten gemeldet, am Fahrzeug eines Konvois mit Status aktiv/läuft. Verband und
Organisation kommen aus ``test_tracker_geraete`` — dort steht der HLF in einem
laufenden und einem geplanten Konvoi, der MTW nur im laufenden.
"""

import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import update

from app.database import AsyncSessionLocal
from app.models.convoy import Convoy
from app.models.ortungsgeraet import Ortungsgeraet
from app.services import anwesenheit
from tests.test_tracker_geraete import org, reset_db_engine  # noqa: F401 — Fixtures

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
