"""Regelbesatzung: die Stärke steht am Fahrzeug, nicht nur im einzelnen Marsch.

Die Zusage dieser Datei: wer sie einmal beim Anlegen des Fahrzeugs einträgt,
tippt sie in keinem Konvoi noch einmal — und wer sie später am Fahrzeug
ändert, schreibt damit keinen fertig geplanten Verband um. Das eine ist der
Komfort, das andere die Bedingung, unter der er unbedenklich ist.

Der Unterschied zwischen „nicht angegeben" und „niemand" gilt hier wie
überall: ein Fahrzeug ohne Angabe ist unbekannt besetzt, nicht leer.
"""

import uuid
from types import SimpleNamespace

import pytest
from sqlalchemy import delete

from app.api.routes import convoys as convoy_routes
from app.api.routes import vehicles as vehicle_routes
from app.database import AsyncSessionLocal, engine
from app.models.convoy import Convoy, ConvoyVehicle
from app.models.organization import Organization, UserOrganization
from app.models.user import User
from app.models.vehicle import Vehicle
from app.schemas.convoy import AddVehicleRequest
from app.schemas.vehicle import VehicleCreate, VehicleUpdate


@pytest.fixture(autouse=True)
async def reset_db_engine():
    """Verbindungspool nach jedem Test schließen — siehe test_mannschaftsstaerke."""
    yield
    await engine.dispose()


@pytest.fixture
async def bestand():
    """Eine Organisation mit einem leeren Konvoi, dazu ein Planer."""
    marker = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        user = User(email=f"rbs-{marker}@test.invalid", hashed_password="x", is_active=True)
        db.add(user)
        await db.flush()
        org = Organization(name=f"Org {marker}", slug=f"org-{marker}", owner_id=user.id)
        db.add(org)
        await db.flush()
        db.add(UserOrganization(user_id=user.id, organization_id=org.id, role="planer"))
        convoy = Convoy(name=f"Verband {marker}", owner_id=user.id, organization_id=org.id)
        db.add(convoy)
        await db.commit()
        ids = SimpleNamespace(
            user=SimpleNamespace(id=user.id),
            org=SimpleNamespace(id=org.id),
            ctx=(SimpleNamespace(id=user.id), SimpleNamespace(id=org.id), "planer"),
            user_id=user.id,
            org_id=org.id,
            convoy_id=convoy.id,
        )

    yield ids

    async with AsyncSessionLocal() as db:
        await db.execute(delete(ConvoyVehicle).where(ConvoyVehicle.convoy_id == ids.convoy_id))
        await db.execute(delete(Convoy).where(Convoy.id == ids.convoy_id))
        await db.execute(delete(Vehicle).where(Vehicle.org_id == ids.org_id))
        await db.execute(
            delete(UserOrganization).where(UserOrganization.organization_id == ids.org_id)
        )
        await db.execute(delete(Organization).where(Organization.id == ids.org_id))
        await db.execute(delete(User).where(User.id == ids.user_id))
        await db.commit()


async def _anlegen(bestand, **felder) -> uuid.UUID:
    """Ein Fahrzeug über den Endpunkt anlegen und seine ID zurückgeben."""
    async with AsyncSessionLocal() as db:
        fahrzeug = await vehicle_routes.create_vehicle(
            data=VehicleCreate(name=f"LF {uuid.uuid4().hex[:4]}", **felder),
            ctx=bestand.ctx,
            db=db,
        )
        return fahrzeug.id


async def _aendern(bestand, fahrzeug_id: uuid.UUID, **felder) -> Vehicle:
    """Stammdaten ändern — genannt wird nur, was im Aufruf steht."""
    async with AsyncSessionLocal() as db:
        await vehicle_routes.update_vehicle(
            vehicle_id=fahrzeug_id,
            data=VehicleUpdate(**felder),
            ctx=bestand.ctx,
            db=db,
        )
    async with AsyncSessionLocal() as db:
        return await db.get(Vehicle, fahrzeug_id)


async def _zuordnen(bestand, fahrzeug_id: uuid.UUID, **felder) -> ConvoyVehicle:
    """Das Fahrzeug in den Verband stellen und die entstandene Zeile lesen."""
    async with AsyncSessionLocal() as db:
        await convoy_routes.add_vehicle_to_convoy(
            convoy_id=bestand.convoy_id,
            data=AddVehicleRequest(vehicle_id=fahrzeug_id, **felder),
            ctx=bestand.ctx,
            db=db,
        )
    async with AsyncSessionLocal() as db:
        return await db.get(ConvoyVehicle, (bestand.convoy_id, fahrzeug_id))


# ── Stammdaten ────────────────────────────────────────────────────────────────

async def test_regelbesatzung_wird_beim_anlegen_gespeichert(bestand):
    fahrzeug_id = await _anlegen(
        bestand,
        staerke_soll_fuehrer=0,
        staerke_soll_unterfuehrer=1,
        staerke_soll_mannschaften=8,
    )

    async with AsyncSessionLocal() as db:
        fahrzeug = await db.get(Vehicle, fahrzeug_id)
    assert (
        fahrzeug.staerke_soll_fuehrer,
        fahrzeug.staerke_soll_unterfuehrer,
        fahrzeug.staerke_soll_mannschaften,
    ) == (0, 1, 8)


async def test_ohne_angabe_bleibt_die_regelbesatzung_unbekannt(bestand):
    # Nicht 0/0/0 — ein Fahrzeug ohne Eintrag fährt nicht nachweislich leer.
    fahrzeug_id = await _anlegen(bestand)

    async with AsyncSessionLocal() as db:
        fahrzeug = await db.get(Vehicle, fahrzeug_id)
    assert fahrzeug.staerke_soll_fuehrer is None
    assert fahrzeug.staerke_soll_unterfuehrer is None
    assert fahrzeug.staerke_soll_mannschaften is None


def test_unplausible_regelbesatzung_wird_abgewiesen():
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        VehicleCreate(name="LF 10", staerke_soll_mannschaften=100)


# ── Übernahme in die Planung ──────────────────────────────────────────────────

async def test_zuordnung_uebernimmt_die_regelbesatzung_als_sollstaerke(bestand):
    fahrzeug_id = await _anlegen(
        bestand,
        staerke_soll_fuehrer=0,
        staerke_soll_unterfuehrer=1,
        staerke_soll_mannschaften=8,
    )

    cv = await _zuordnen(bestand, fahrzeug_id)

    assert (
        cv.staerke_soll_fuehrer,
        cv.staerke_soll_unterfuehrer,
        cv.staerke_soll_mannschaften,
    ) == (0, 1, 8)


async def test_ohne_regelbesatzung_bleibt_die_sollstaerke_offen(bestand):
    fahrzeug_id = await _anlegen(bestand)

    cv = await _zuordnen(bestand, fahrzeug_id)

    assert cv.staerke_soll_fuehrer is None
    assert cv.staerke_soll_unterfuehrer is None
    assert cv.staerke_soll_mannschaften is None


async def test_angegebene_sollstaerke_schlaegt_die_regelbesatzung(bestand):
    # Der Marsch entscheidet über sich selbst: wer für diesen Verband eine
    # Stärke mitschickt, meint sie auch.
    fahrzeug_id = await _anlegen(
        bestand,
        staerke_soll_fuehrer=0,
        staerke_soll_unterfuehrer=1,
        staerke_soll_mannschaften=8,
    )

    cv = await _zuordnen(
        bestand,
        fahrzeug_id,
        staerke_soll_fuehrer=1,
        staerke_soll_unterfuehrer=2,
        staerke_soll_mannschaften=3,
    )

    assert (
        cv.staerke_soll_fuehrer,
        cv.staerke_soll_unterfuehrer,
        cv.staerke_soll_mannschaften,
    ) == (1, 2, 3)


async def test_teilangabe_wird_nicht_aus_den_stammdaten_aufgefuellt(bestand):
    # Sonst stünde im Marschbefehl eine Zahl, die für ihn niemand eingetragen
    # hat — und sie sähe aus wie eine Eingabe.
    fahrzeug_id = await _anlegen(
        bestand,
        staerke_soll_fuehrer=0,
        staerke_soll_unterfuehrer=1,
        staerke_soll_mannschaften=8,
    )

    cv = await _zuordnen(bestand, fahrzeug_id, staerke_soll_mannschaften=4)

    assert cv.staerke_soll_mannschaften == 4
    assert cv.staerke_soll_fuehrer is None
    assert cv.staerke_soll_unterfuehrer is None


async def test_spaetere_stammdatenpflege_laesst_den_geplanten_verband_stehen(bestand):
    """Kopiert wird einmal, beim Zuordnen.

    Ein Fahrzeug, dessen Regelbesatzung im Januar geändert wird, darf den im
    Dezember geschriebenen Marschbefehl nicht nachträglich umschreiben.
    """
    fahrzeug_id = await _anlegen(
        bestand,
        staerke_soll_fuehrer=0,
        staerke_soll_unterfuehrer=1,
        staerke_soll_mannschaften=8,
    )
    await _zuordnen(bestand, fahrzeug_id)

    async with AsyncSessionLocal() as db:
        fahrzeug = await db.get(Vehicle, fahrzeug_id)
        fahrzeug.staerke_soll_mannschaften = 5
        await db.commit()

    async with AsyncSessionLocal() as db:
        cv = await db.get(ConvoyVehicle, (bestand.convoy_id, fahrzeug_id))
    assert cv.staerke_soll_mannschaften == 8


# ── Ändern und Löschen ────────────────────────────────────────────────────────
#
# Ein Stammdatum, das sich eintragen, aber nicht mehr leeren lässt, ist eine
# Einbahnstraße: „0/0/0" (niemand) wäre dann die einzige Art, eine falsch
# eingetragene Besatzung loszuwerden — und sie sagt etwas anderes.

async def test_ausdrueckliches_null_loescht_die_regelbesatzung(bestand):
    fahrzeug_id = await _anlegen(
        bestand,
        staerke_soll_fuehrer=0,
        staerke_soll_unterfuehrer=1,
        staerke_soll_mannschaften=8,
    )

    fahrzeug = await _aendern(
        bestand,
        fahrzeug_id,
        staerke_soll_fuehrer=None,
        staerke_soll_unterfuehrer=None,
        staerke_soll_mannschaften=None,
    )

    assert fahrzeug.staerke_soll_fuehrer is None
    assert fahrzeug.staerke_soll_unterfuehrer is None
    assert fahrzeug.staerke_soll_mannschaften is None


async def test_nicht_genanntes_feld_bleibt_stehen(bestand):
    # Der Unterschied zum Löschen: was der Aufruf gar nicht erwähnt, ist keine
    # Aussage. Sonst räumte ein Umbenennen die halbe Fahrzeugkarte ab.
    fahrzeug_id = await _anlegen(
        bestand,
        staerke_soll_fuehrer=0,
        staerke_soll_unterfuehrer=1,
        staerke_soll_mannschaften=8,
    )

    fahrzeug = await _aendern(bestand, fahrzeug_id, callsign="Florian 1")

    assert fahrzeug.callsign == "Florian 1"
    assert (
        fahrzeug.staerke_soll_fuehrer,
        fahrzeug.staerke_soll_unterfuehrer,
        fahrzeug.staerke_soll_mannschaften,
    ) == (0, 1, 8)


async def test_null_ist_nicht_dasselbe_wie_geloescht(bestand):
    # 0/0/0 bleibt eine Aussage („fährt unbesetzt") und darf beim Speichern
    # nicht als „nichts angegeben" verschwinden.
    fahrzeug_id = await _anlegen(bestand)

    fahrzeug = await _aendern(
        bestand,
        fahrzeug_id,
        staerke_soll_fuehrer=0,
        staerke_soll_unterfuehrer=0,
        staerke_soll_mannschaften=0,
    )

    assert (
        fahrzeug.staerke_soll_fuehrer,
        fahrzeug.staerke_soll_unterfuehrer,
        fahrzeug.staerke_soll_mannschaften,
    ) == (0, 0, 0)


async def test_pflichtfelder_lassen_sich_nicht_leeren(bestand):
    """`name` und `propulsion` sind NOT NULL.

    Für sie heißt ein mitgeschicktes ``null`` „nicht ändern". Ohne diese
    Ausnahme endete ein geleertes Namensfeld nicht in einer Fehlermeldung,
    sondern in einem Serverfehler beim Schreiben.
    """
    fahrzeug_id = await _anlegen(bestand, callsign="Florian 1")
    async with AsyncSessionLocal() as db:
        vorher = await db.get(Vehicle, fahrzeug_id)
        name, antrieb = vorher.name, vorher.propulsion

    fahrzeug = await _aendern(bestand, fahrzeug_id, name=None, propulsion=None, callsign=None)

    assert fahrzeug.name == name
    assert fahrzeug.propulsion == antrieb
    # Das nullbare Feld daneben wird sehr wohl geleert.
    assert fahrzeug.callsign is None
