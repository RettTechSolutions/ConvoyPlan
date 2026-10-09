"""Ortungsgeräte (Tracker): die Regeln ohne Datenbank, dann der Weg durch die App.

Was hier zugesagt wird:

- Gesendet wird nur im laufenden Konvoi (``active``/``running``), sonst sagt die
  Instanz ``schweigen`` und verwirft, was trotzdem kommt.
- Fixes tragen Gerätezeit; ein nachgereichtes Bündel setzt die aktuelle
  Position nicht zurück, und in den Verlauf kommt jeder Fix mit seiner Zeit.
- Ein Fahrzeug in zwei laufenden Konvois bekommt die Position in beiden.
- Einmal-Code und Token liegen nur als Hash vor; ein neuer Code macht das alte
  Token ungültig; unbekannt, abgelaufen und verbraucht geben dieselbe 404.
- „GPS-Freigabe zurücksetzen" gilt auch für einen Tracker.
"""
import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from sqlalchemy import delete, select

from app.database import AsyncSessionLocal
from app.models.audit_log import AuditLog
from app.models.convoy import Convoy, ConvoyVehicle
from app.models.organization import Organization, UserOrganization
from app.models.ortungsgeraet import Ortungsgeraet
from app.models.public_tracker import PublicTracker, VehiclePositionTrail
from app.models.user import User
from app.models.vehicle import Vehicle
from app.models.vehicle_position import VehiclePosition
from app.services import ortungsgeraet as og
from app.services.tracking import tracking_manager
from tests.aktionsseite_fixtures import _token, client, h, reset_db_engine  # noqa: F401

JETZT = datetime(2026, 10, 9, 8, 0, tzinfo=timezone.utc)
IMEI = "352656100000001"


def _iso(t: datetime) -> str:
    return t.strftime("%Y-%m-%dT%H:%M:%SZ")


# ── Regeln ohne Datenbank ──────────────────────────────────────────────────


class TestFixe:
    def test_brauchbarer_fix(self):
        f = og.fix_lesen({"t": _iso(JETZT), "lat": 47.8, "lon": 11.0, "speed_kmh": 48.2, "heading": 359.9}, JETZT)
        assert f is not None and (f.lat, f.lon, f.speed_kmh, f.heading) == (47.8, 11.0, 48.2, 359.9)
        assert f.t == JETZT

    @pytest.mark.parametrize(
        "roh",
        [
            {"t": _iso(JETZT + timedelta(seconds=121)), "lat": 47.8, "lon": 11.0},  # Zukunft: Uhr falsch
            {"t": _iso(JETZT - timedelta(hours=25)), "lat": 47.8, "lon": 11.0},  # älter als der Puffer
            {"t": _iso(JETZT), "lat": 91, "lon": 11.0},
            {"t": _iso(JETZT), "lat": 47.8, "lon": -181},
            {"t": "2026-10-09T08:00:00", "lat": 47.8, "lon": 11.0},  # ohne Zeitzone
            {"t": "gestern", "lat": 47.8, "lon": 11.0},
            {"lat": 47.8, "lon": 11.0},
            "kein dict",
        ],
    )
    def test_unbrauchbare_fixes(self, roh):
        assert og.fix_lesen(roh, JETZT) is None

    def test_grenzen_der_toleranz(self):
        assert og.fix_lesen({"t": _iso(JETZT + timedelta(seconds=120)), "lat": 0, "lon": 0}, JETZT) is not None
        assert og.fix_lesen({"t": _iso(JETZT - timedelta(hours=24)), "lat": 0, "lon": 0}, JETZT) is not None

    def test_unsinnige_nebenwerte_fallen_einzeln_weg(self):
        f = og.fix_lesen({"t": _iso(JETZT), "lat": 1, "lon": 2, "speed_kmh": -3, "heading": 360, "accuracy_m": True}, JETZT)
        assert f is not None and f.speed_kmh is None and f.heading is None and f.accuracy_m is None

    def test_buendel_sortiert_und_zaehlt_verworfene(self):
        roh = [
            {"t": _iso(JETZT - timedelta(seconds=10)), "lat": 1, "lon": 2},
            {"t": "kaputt", "lat": 1, "lon": 2},
            {"t": _iso(JETZT - timedelta(seconds=30)), "lat": 1, "lon": 2},
        ]
        fixes, verworfen = og.fixes_lesen(roh, JETZT)
        assert verworfen == 1
        assert [f.t for f in fixes] == [JETZT - timedelta(seconds=30), JETZT - timedelta(seconds=10)]

    def test_zu_grosses_buendel_ist_eine_400(self):
        fix = {"t": _iso(JETZT), "lat": 1, "lon": 2}
        assert og.fixes_lesen([fix] * 500, JETZT)[0]
        with pytest.raises(ValueError):
            og.fixes_lesen([fix] * 501, JETZT)
        with pytest.raises(ValueError):
            og.fixes_lesen({"fixes": []}, JETZT)

    def test_nur_juengere_ueberschreiben(self):
        neu = og.Fix(JETZT, 1, 2, None, None, None)
        assert og.ueberschreibt(None, neu)
        assert og.ueberschreibt(JETZT - timedelta(seconds=1), neu)
        assert not og.ueberschreibt(JETZT, neu)
        assert not og.ueberschreibt(JETZT + timedelta(seconds=1), neu)


class TestCode:
    def test_form(self):
        code = og.code_erzeugen()
        assert og.code_normalisieren(code) == code
        assert not set(code.replace("-", "")) & set("0O1I")

    def test_tipper_darf_schlampen(self):
        assert og.code_normalisieren(" k7q2m9xd ") == "K7Q2-M9XD"
        assert og.code_normalisieren("K7Q2-M9X") is None
        assert og.code_normalisieren("K7Q2-M9X0") is None

    def test_gueltig_nur_vor_ablauf(self):
        code = "K7Q2-M9XD"
        ablauf = JETZT + og.CODE_GUELTIG
        assert og.code_gueltig(og.hash(code), ablauf, "k7q2m9xd", JETZT)
        assert not og.code_gueltig(og.hash(code), ablauf, code, ablauf)
        assert not og.code_gueltig(og.hash(code), ablauf, "K7Q2-M9XE", JETZT)
        assert not og.code_gueltig(None, None, code, JETZT)


class TestAnweisung:
    @pytest.mark.parametrize(
        "gekoppelt,laufend,gesperrt,erwartet",
        [
            (True, 1, False, "senden"),
            (True, 2, False, "senden"),
            (True, 0, False, "schweigen"),
            (False, 1, False, "schweigen"),
            (True, 1, True, "schweigen"),
        ],
    )
    def test_modus(self, gekoppelt, laufend, gesperrt, erwartet):
        assert og.modus(gekoppelt, laufend, gesperrt) == erwartet

    def test_anweisung_traegt_takt_und_serverzeit(self):
        a = og.anweisung("senden", JETZT)
        assert a["modus"] == "senden" and a["serverzeit"] == "2026-10-09T08:00:00Z"
        assert a["firmware"] is None
        assert {"intervall_s", "buendel_s", "nachfrage_s", "lebenszeichen_s"} <= set(a)

    def test_zustand_wird_bereinigt(self):
        z = og.zustand_lesen({"firmware": " 0.1.0 ", "akku_prozent": 87.4, "extern": False, "signal_dbm": -95})
        assert z == {"firmware": "0.1.0", "akku_prozent": 87, "extern": False, "signal_dbm": -95}
        assert og.zustand_lesen({"akku_prozent": 140, "extern": "ja", "signal_dbm": 5, "firmware": ""}) == {}


# ── Durch die App ──────────────────────────────────────────────────────────


@pytest.fixture
async def org():
    marker = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        admin = User(email=f"trk-ad-{marker}@test.invalid", hashed_password="x")
        fahrer = User(email=f"trk-fa-{marker}@test.invalid", hashed_password="x")
        fremd = User(email=f"trk-fr-{marker}@test.invalid", hashed_password="x")
        db.add_all([admin, fahrer, fremd])
        await db.flush()
        org = Organization(name=f"Tracker {marker}", slug=f"t{marker[:7]}", owner_id=admin.id)
        andere = Organization(name=f"Fremd {marker}", slug=f"f{marker[:7]}", owner_id=fremd.id)
        db.add_all([org, andere])
        await db.flush()
        db.add_all([
            UserOrganization(user_id=admin.id, organization_id=org.id, role="admin"),
            UserOrganization(user_id=fahrer.id, organization_id=org.id, role="fahrer"),
            UserOrganization(user_id=fremd.id, organization_id=andere.id, role="admin"),
        ])
        hlf = Vehicle(name="HLF 20", owner_id=admin.id, org_id=org.id)
        mtw = Vehicle(name="MTW", owner_id=admin.id, org_id=org.id)
        fremdes = Vehicle(name="Fremder LKW", owner_id=fremd.id, org_id=andere.id)
        konvoi = Convoy(name="Marsch A", owner_id=admin.id, organization_id=org.id, status="running")
        zweiter = Convoy(name="Marsch B", owner_id=admin.id, organization_id=org.id, status="planning")
        db.add_all([hlf, mtw, fremdes, konvoi, zweiter])
        await db.flush()
        db.add_all([
            ConvoyVehicle(convoy_id=konvoi.id, vehicle_id=hlf.id, position=0),
            ConvoyVehicle(convoy_id=konvoi.id, vehicle_id=mtw.id, position=1),
            ConvoyVehicle(convoy_id=zweiter.id, vehicle_id=hlf.id, position=0),
        ])
        await db.commit()
        ids = SimpleNamespace(
            org_id=org.id, andere_id=andere.id,
            konvoi=konvoi.id, zweiter=zweiter.id,
            hlf=hlf.id, mtw=mtw.id, fremdes=fremdes.id,
            admin=_token(admin.id, admin.token_version, org_id=str(org.id), org_slug=org.slug, role="admin"),
            fahrer=_token(fahrer.id, fahrer.token_version, org_id=str(org.id), org_slug=org.slug, role="fahrer"),
            users=[admin.id, fahrer.id, fremd.id],
        )
    yield ids
    async with AsyncSessionLocal() as db:
        for org_id in (ids.org_id, ids.andere_id):
            await db.execute(delete(AuditLog).where(AuditLog.org_id == org_id))
            await db.execute(delete(Ortungsgeraet).where(Ortungsgeraet.organization_id == org_id))
            await db.execute(delete(PublicTracker).where(PublicTracker.organization_id == org_id))
        for cid in (ids.konvoi, ids.zweiter):
            await db.execute(delete(VehiclePositionTrail).where(VehiclePositionTrail.convoy_id == cid))
            await db.execute(delete(VehiclePosition).where(VehiclePosition.convoy_id == cid))
            await db.execute(delete(ConvoyVehicle).where(ConvoyVehicle.convoy_id == cid))
            await db.execute(delete(Convoy).where(Convoy.id == cid))
        await db.execute(delete(Vehicle).where(Vehicle.id.in_([ids.hlf, ids.mtw, ids.fremdes])))
        await db.execute(delete(UserOrganization).where(UserOrganization.organization_id.in_([ids.org_id, ids.andere_id])))
        await db.execute(delete(Organization).where(Organization.id.in_([ids.org_id, ids.andere_id])))
        await db.execute(delete(User).where(User.id.in_(ids.users)))
        await db.commit()


async def _anlegen(client, org, **felder) -> dict:
    r = await client.post(
        "/api/org/geraete", json={"name": "Tracker HLF", "vehicle_id": str(org.hlf), **felder}, headers=h(org.admin)
    )
    assert r.status_code == 201, r.text
    return r.json()


async def _einloesen(client, code: str, **extra) -> dict:
    r = await client.post(
        "/api/geraete/einloesen",
        json={"code": code, "hardware_id": IMEI, "firmware": "0.1.0", "hardware": "nrf9151-v1", **extra},
    )
    assert r.status_code == 200, r.text
    return r.json()


async def _eingerichtet(client, org, **felder) -> tuple[dict, dict]:
    geraet = await _anlegen(client, org, **felder)
    return geraet, h((await _einloesen(client, geraet["code"]))["token"])


def _fix(sekunden_her: float, lon: float = 11.0, **extra) -> dict:
    t = datetime.now(timezone.utc) - timedelta(seconds=sekunden_her)
    return {"t": _iso(t), "lat": 47.8, "lon": lon, "speed_kmh": 50.0, "heading": 90.0, **extra}


async def _position(convoy_id, vehicle_id) -> VehiclePosition | None:
    async with AsyncSessionLocal() as db:
        return await db.get(VehiclePosition, (convoy_id, vehicle_id))


async def _konvoi_status(convoy_id, status: str) -> None:
    async with AsyncSessionLocal() as db:
        k = await db.get(Convoy, convoy_id)
        k.status = status
        await db.commit()


class TestEinrichten:
    async def test_code_steht_einmal_in_der_antwort_und_nie_in_der_liste(self, client, org):
        geraet = await _anlegen(client, org)
        code = geraet["code"]
        assert og.code_normalisieren(code) == code
        assert geraet["eingerichtet"] is False and geraet["code_offen"] is True
        liste = (await client.get("/api/org/geraete", headers=h(org.admin))).json()
        assert len(liste) == 1 and liste[0]["vehicle_name"] == "HLF 20"
        liste_text = (await client.get("/api/org/geraete", headers=h(org.admin))).text
        assert code not in liste_text
        async with AsyncSessionLocal() as db:
            zeile = await db.get(Ortungsgeraet, uuid.UUID(geraet["id"]))
            assert zeile.code_hash == og.hash(code) and code not in str(vars(zeile))

    async def test_einloesen_tauscht_code_gegen_token(self, client, org):
        geraet = await _anlegen(client, org)
        antwort = await _einloesen(client, geraet["code"].lower().replace("-", ""))
        assert antwort["geraet_id"] == geraet["id"] and antwort["token"].startswith("cvt_")
        zeile = (await client.get("/api/org/geraete", headers=h(org.admin))).json()[0]
        assert zeile["eingerichtet"] is True and zeile["code_offen"] is False
        assert (zeile["hardware_id"], zeile["hardware"], zeile["firmware"]) == (IMEI, "nrf9151-v1", "0.1.0")
        async with AsyncSessionLocal() as db:
            db_zeile = await db.get(Ortungsgeraet, uuid.UUID(geraet["id"]))
            assert db_zeile.token_hash == og.hash(antwort["token"]) and db_zeile.code_hash is None
            protokoll = (
                await db.execute(select(AuditLog).where(AuditLog.target_id == geraet["id"]))
            ).scalars().all()
            assert {e.action for e in protokoll} == {"org.geraet.created", "geraet.eingerichtet"}

    async def test_unbekannt_verbraucht_und_abgelaufen_sind_dieselbe_404(self, client, org):
        geraet = await _anlegen(client, org)
        unbekannt = await client.post("/api/geraete/einloesen", json={"code": "AAAA-BBBB", "hardware_id": IMEI})
        await _einloesen(client, geraet["code"])
        verbraucht = await client.post("/api/geraete/einloesen", json={"code": geraet["code"], "hardware_id": IMEI})
        zweites = await _anlegen(client, org, vehicle_id=None)
        async with AsyncSessionLocal() as db:
            z = await db.get(Ortungsgeraet, uuid.UUID(zweites["id"]))
            z.code_expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
            await db.commit()
        abgelaufen = await client.post("/api/geraete/einloesen", json={"code": zweites["code"], "hardware_id": IMEI})
        assert unbekannt.status_code == verbraucht.status_code == abgelaufen.status_code == 404
        assert unbekannt.json() == verbraucht.json() == abgelaufen.json()

    async def test_neuer_code_macht_das_alte_token_ungueltig(self, client, org):
        geraet, kopf = await _eingerichtet(client, org)
        antwort = await client.post("/api/geraete/hallo", json={}, headers=kopf)
        assert antwort.status_code == 200
        r = await client.post(f"/api/org/geraete/{geraet['id']}/code", headers=h(org.admin))
        assert r.status_code == 200 and r.json()["code"] != geraet["code"]
        antwort = await client.post("/api/geraete/hallo", json={}, headers=kopf)
        assert antwort.status_code == 401
        neu = await _einloesen(client, r.json()["code"])
        antwort = await client.post("/api/geraete/hallo", json={}, headers=h(neu["token"]))
        assert antwort.status_code == 200

    async def test_gesperrtes_geraet_bekommt_401(self, client, org):
        geraet, kopf = await _eingerichtet(client, org)
        r = await client.put(
            f"/api/org/geraete/{geraet['id']}",
            json={"name": "Tracker HLF", "vehicle_id": str(org.hlf), "kanal": "beta", "aktiv": False},
            headers=h(org.admin),
        )
        assert r.status_code == 200 and r.json()["kanal"] == "beta" and r.json()["aktiv"] is False
        antwort = await client.post("/api/geraete/hallo", json={}, headers=kopf)
        assert antwort.status_code == 401
        antwort = await client.post("/api/geraete/hallo", json={})
        assert antwort.status_code == 401
        antwort = await client.post("/api/geraete/hallo", json={}, headers=h("cvt_falsch"))
        assert antwort.status_code == 401

    async def test_nur_org_admins_verwalten(self, client, org):
        for aufruf in (
            client.get("/api/org/geraete", headers=h(org.fahrer)),
            client.post("/api/org/geraete", json={"name": "x"}, headers=h(org.fahrer)),
        ):
            antwort = await aufruf
            assert antwort.status_code == 403

    async def test_loeschen(self, client, org):
        geraet, kopf = await _eingerichtet(client, org)
        antwort = await client.delete(f"/api/org/geraete/{geraet['id']}", headers=h(org.admin))
        assert antwort.status_code == 204
        liste = await client.get("/api/org/geraete", headers=h(org.admin))
        assert liste.json() == []
        antwort = await client.post("/api/geraete/hallo", json={}, headers=kopf)
        assert antwort.status_code == 401


class TestKoppeln:
    async def test_fremdes_und_unbekanntes_fahrzeug_gleich(self, client, org):
        fremd = await client.post(
            "/api/org/geraete", json={"name": "x", "vehicle_id": str(org.fremdes)}, headers=h(org.admin)
        )
        unbekannt = await client.post(
            "/api/org/geraete", json={"name": "x", "vehicle_id": str(uuid.uuid4())}, headers=h(org.admin)
        )
        assert fremd.status_code == unbekannt.status_code == 422
        assert fremd.json() == unbekannt.json()

    async def test_ein_fahrzeug_ein_tracker(self, client, org):
        await _anlegen(client, org)
        r = await client.post("/api/org/geraete", json={"name": "zweiter", "vehicle_id": str(org.hlf)}, headers=h(org.admin))
        assert r.status_code == 409
        r = await client.post("/api/org/geraete", json={"name": "zweiter", "vehicle_id": str(org.mtw)}, headers=h(org.admin))
        assert r.status_code == 201

    async def test_unbekannter_kanal(self, client, org):
        r = await client.post("/api/org/geraete", json={"name": "x", "kanal": "alpha"}, headers=h(org.admin))
        assert r.status_code == 422


class TestSenden:
    async def test_ungekoppelt_schweigen(self, client, org):
        _, kopf = await _eingerichtet(client, org, vehicle_id=None)
        r = await client.post("/api/geraete/hallo", json={"grund": "bewegung", "akku_prozent": 87}, headers=kopf)
        assert r.status_code == 200 and r.json()["modus"] == "schweigen"
        zeile = (await client.get("/api/org/geraete", headers=h(org.admin))).json()[0]
        assert zeile["akku_prozent"] == 87 and zeile["zuletzt_gesehen"] is not None

    @pytest.mark.parametrize("status,erwartet", [("running", "senden"), ("active", "senden"),
                                                 ("planning", "schweigen"), ("completed", "schweigen")])
    async def test_nur_im_laufenden_konvoi(self, client, org, status, erwartet):
        await _konvoi_status(org.konvoi, status)
        _, kopf = await _eingerichtet(client, org)
        r = await client.post("/api/geraete/hallo", json={}, headers=kopf)
        assert r.json()["modus"] == erwartet

    async def test_fixes_landen_mit_geraetezeit_und_heben_auf_en_route(self, client, org):
        _, kopf = await _eingerichtet(client, org)
        empfangen: list[tuple[str, dict]] = []
        tracking_manager.add_broadcast_listener(lambda cid, d: empfangen.append((cid, d)))
        try:
            r = await client.post(
                "/api/geraete/positionen",
                json={"akku_prozent": 80, "fixes": [_fix(30, 11.00), _fix(20, 11.01), _fix(10, 11.02)]},
                headers=kopf,
            )
        finally:
            tracking_manager.reset_listeners()
        assert r.status_code == 200, r.text
        assert (r.json()["angenommen"], r.json()["verworfen"], r.json()["modus"]) == (3, 0, "senden")
        pos = await _position(org.konvoi, org.hlf)
        assert pos.lon == 11.02
        assert abs((datetime.now(timezone.utc) - pos.recorded_at).total_seconds() - 10) < 3
        async with AsyncSessionLocal() as db:
            cv = await db.get(ConvoyVehicle, (org.konvoi, org.hlf))
            assert cv.vehicle_status == "en_route" and cv.status_changed_at is not None
        typen = [d["type"] for cid, d in empfangen if cid == str(org.konvoi)]
        assert typen == ["position", "status_update"]
        assert next(d for _, d in empfangen if d["type"] == "position")["lon"] == 11.02

    async def test_nachgereichtes_buendel_setzt_nicht_zurueck(self, client, org):
        _, kopf = await _eingerichtet(client, org)
        await client.post("/api/geraete/positionen", json={"fixes": [_fix(10, 11.20)]}, headers=kopf)
        r = await client.post("/api/geraete/positionen", json={"fixes": [_fix(600, 11.00), _fix(500, 11.05)]}, headers=kopf)
        assert r.json()["angenommen"] == 2
        assert (await _position(org.konvoi, org.hlf)).lon == 11.20

    async def test_einzelne_fixes_verworfen_nicht_das_buendel(self, client, org):
        _, kopf = await _eingerichtet(client, org)
        zukunft = _iso(datetime.now(timezone.utc) + timedelta(minutes=10))
        r = await client.post(
            "/api/geraete/positionen",
            json={"fixes": [_fix(5, 11.3), {"t": zukunft, "lat": 47.8, "lon": 11.9}, {"lat": 1}]},
            headers=kopf,
        )
        assert (r.json()["angenommen"], r.json()["verworfen"]) == (1, 2)
        assert (await _position(org.konvoi, org.hlf)).lon == 11.3
        r = await client.post("/api/geraete/positionen", json={"fixes": [_fix(1)] * 501}, headers=kopf)
        assert r.status_code == 400
        r = await client.post("/api/geraete/positionen", json={"fixes": "x"}, headers=kopf)
        assert r.status_code == 400

    async def test_bei_schweigen_wird_nichts_geschrieben(self, client, org):
        await _konvoi_status(org.konvoi, "completed")
        _, kopf = await _eingerichtet(client, org)
        r = await client.post("/api/geraete/positionen", json={"fixes": [_fix(5), _fix(1)]}, headers=kopf)
        assert r.status_code == 200
        assert (r.json()["angenommen"], r.json()["verworfen"], r.json()["modus"]) == (0, 2, "schweigen")
        assert await _position(org.konvoi, org.hlf) is None

    async def test_zwei_laufende_konvois_bekommen_beide_die_position(self, client, org):
        """O7 im Tracker-Plan: Haupt- und Unterkonvoi zeigen beide das Fahrzeug."""
        await _konvoi_status(org.zweiter, "active")
        _, kopf = await _eingerichtet(client, org)
        r = await client.post("/api/geraete/positionen", json={"fixes": [_fix(5, 11.5)]}, headers=kopf)
        assert r.json()["angenommen"] == 1
        assert (await _position(org.konvoi, org.hlf)).lon == 11.5
        assert (await _position(org.zweiter, org.hlf)).lon == 11.5

    async def test_gps_freigabe_zuruecksetzen_gilt_auch_fuer_den_tracker(self, client, org):
        _, kopf = await _eingerichtet(client, org)
        tracking_manager.mark_cleared(str(org.konvoi), str(org.hlf))
        try:
            r = await client.post("/api/geraete/positionen", json={"fixes": [_fix(5)]}, headers=kopf)
        finally:
            tracking_manager._cleared.pop((str(org.konvoi), str(org.hlf)), None)
        assert r.status_code == 200
        assert await _position(org.konvoi, org.hlf) is None

    async def test_fahrzeug_anderer_organisation_bleibt_unberuehrt(self, client, org):
        """Ein Konvoi einer anderen Organisation, der dasselbe Fahrzeug führte, zählt nicht."""
        _, kopf = await _eingerichtet(client, org)
        async with AsyncSessionLocal() as db:
            fremd = Convoy(name="Fremd", owner_id=org.users[2], organization_id=org.andere_id, status="running")
            db.add(fremd)
            await db.flush()
            db.add(ConvoyVehicle(convoy_id=fremd.id, vehicle_id=org.hlf, position=0))
            await db.commit()
            fremd_id = fremd.id
        try:
            await client.post("/api/geraete/positionen", json={"fixes": [_fix(5)]}, headers=kopf)
            assert await _position(fremd_id, org.hlf) is None
            assert await _position(org.konvoi, org.hlf) is not None
        finally:
            async with AsyncSessionLocal() as db:
                await db.execute(delete(VehiclePosition).where(VehiclePosition.convoy_id == fremd_id))
                await db.execute(delete(ConvoyVehicle).where(ConvoyVehicle.convoy_id == fremd_id))
                await db.execute(delete(Convoy).where(Convoy.id == fremd_id))
                await db.commit()


class TestFirmware:
    async def test_ergebnis_steht_am_geraet(self, client, org):
        geraet, kopf = await _eingerichtet(client, org)
        r = await client.post(
            "/api/geraete/firmware/ergebnis",
            json={"version": "0.2.0", "ergebnis": "zurueckgerollt", "meldung": "kein Kontakt", "firmware": "0.1.0"},
            headers=kopf,
        )
        assert r.status_code == 200 and r.json()["modus"] == "senden"
        zeile = (await client.get("/api/org/geraete", headers=h(org.admin))).json()[0]
        assert (zeile["update_version"], zeile["update_ergebnis"], zeile["update_meldung"]) == (
            "0.2.0", "zurueckgerollt", "kein Kontakt",
        )
        assert zeile["firmware"] == "0.1.0"
        r = await client.post("/api/geraete/firmware/ergebnis", json={"version": "0.2.0", "ergebnis": "egal"}, headers=kopf)
        assert r.status_code == 400
