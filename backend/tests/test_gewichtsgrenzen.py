"""Gewichtsgrenzen: gesperrt beim Routing, gezeigt danach — und der Verband zählt mit seinem Größten.

Die Zusagen:

- gesperrt wird mit dem **höchsten** und dem **schwersten** Fahrzeug im Verband.
  Bis 2026-10 nahm die Höhe das niedrigste — ein Wechsellader neben einem MTW
  fuhr unter Brücken durch, die nur der MTW passiert;
- jede Gewichtsgrenze an der Route steht in der Liste, mit Reserve und Ausnahme;
- „Anlieger frei" sperrt nicht, sondern wird gemieden — und wer trotzdem
  hindurch muss, sieht ``ueberschritten``;
- kennt der Graph ``max_weight`` noch nicht, wird ohne Gewicht geroutet statt
  gar nicht, und die Liste bleibt „nicht ermittelt";
- findet GraphHopper keine Verbindung, sagt die Meldung, mit welchen Grenzen.
"""

import uuid
from types import SimpleNamespace

import pytest
from geoalchemy2.shape import from_shape
from httpx import ASGITransport, AsyncClient
from shapely.geometry import Point
from sqlalchemy import delete

from app.api.deps import get_current_user, get_token_data
from app.database import AsyncSessionLocal, engine
from app.main import app
from app.models.convoy import Convoy, ConvoyVehicle
from app.models.organization import Organization, UserOrganization
from app.models.route import Route
from app.models.user import User
from app.models.vehicle import Vehicle
from app.services import gewichtsgrenzen as gg
from app.services import pdf as pdf_svc
from app.services import route_steps
from app.services import routing as routing_svc

COORDS = [[11.0, 47.80], [11.0, 47.81], [11.0, 47.82], [11.0, 47.83]]
KM = [round(m / 1000, 1) for m in route_steps.cumulative_m(COORDS)]


# ── Der Verband ──────────────────────────────────────────────────────────────


def _fz(height_cm=None, weight_kg=None):
    return SimpleNamespace(height_cm=height_cm, weight_kg=weight_kg)


def test_gesperrt_wird_mit_dem_hoechsten_und_dem_schwersten():
    grenzen = routing_svc.verbandsgrenzen(
        [_fz(390, 18000), _fz(250, 3500), _fz(None, 26000), _fz(320, None)]
    )
    assert grenzen == {"max_height_m": 3.9, "max_weight_t": 26.0}


def test_ohne_angaben_wird_nach_nichts_gesperrt():
    assert routing_svc.verbandsgrenzen([_fz(), _fz(0, 0)]) == {}
    assert routing_svc.verbandsgrenzen(iter([_fz(300)])) == {"max_height_m": 3.0}


# ── Liste ohne Datenbank ─────────────────────────────────────────────────────


def test_eine_grenze_steht_mit_reserve_in_der_liste():
    [e] = gg.grenzen([[0, 1, None], [1, 2, 0.1 * 75], [2, 3, None]], [], COORDS, 6.2)
    assert (e["km"], e["lon"], e["lat"]) == (KM[1], COORDS[1][0], COORDS[1][1])
    assert e["m"] == pytest.approx(1112, abs=2)
    assert e["grenze_t"] == 7.5
    assert e["reserve_t"] == 1.3
    assert e["stufe"] == "knapp"
    assert e["ausnahme"] is None


@pytest.mark.parametrize(
    "reserve, stufe",
    [(-0.1, "ueberschritten"), (0.0, "knapp"), (1.9, "knapp"), (gg.KNAPP_T, "frei"), (None, "unbekannt")],
)
def test_stufen(reserve, stufe):
    assert gg.stufe(reserve) == stufe


def test_anlieger_frei_steht_als_ausnahme_dabei():
    [e] = gg.grenzen([[1, 2, 3.5]], [[0, 1, None], [1, 2, "destination"]], COORDS, 12.0)
    assert e["ausnahme"] == "destination"
    assert e["stufe"] == "ueberschritten"


def test_ohne_fahrzeuggewicht_gezeigt_aber_nicht_beurteilt():
    [e] = gg.grenzen([[1, 2, 12.0]], [], COORDS, None)
    assert (e["reserve_t"], e["stufe"]) == (None, "unbekannt")


@pytest.mark.parametrize("wert", [None, "Infinity", float("inf"), float("nan"), 0, -3, 51.1, True, "x"])
def test_was_keine_grenze_ist_steht_nicht_drin(wert):
    assert gg.grenzen([[0, 1, wert]], [], COORDS, 10.0) == []


def test_kaputte_eintraege_werden_uebergangen():
    eintraege = gg.grenzen([None, [0], ["a", 1, 3], [1, 2, 7.5]], [[0, "x"], None], COORDS, 3.0)
    assert [e["grenze_t"] for e in eintraege] == [7.5]


def test_hinweispflichtig_ist_alles_ausser_frei():
    eintraege = gg.grenzen([[0, 1, 7.5], [1, 2, 30.0]], [], COORDS, 7.0)
    assert [e["stufe"] for e in gg.hinweispflichtig(eintraege)] == ["knapp"]


# ── Anfrage an GraphHopper ───────────────────────────────────────────────────


class _Antwort:
    def __init__(self, status, body):
        self.status_code = status
        self.is_success = status < 400
        self._body = body
        self.text = str(body)

    def json(self):
        return self._body


def _pfad(details):
    return {"paths": [{
        "distance": 3300.0, "time": 240_000,
        "points": {"type": "LineString", "coordinates": COORDS},
        "details": details, "instructions": [],
    }]}


def _graphhopper(antworten: list, gesendet: list):
    """Gibt die Antworten der Reihe nach zurück und merkt sich die Anfragen."""

    class _Client:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, url, json):
            gesendet.append(json)
            return antworten[min(len(gesendet), len(antworten)) - 1]

    return SimpleNamespace(AsyncClient=_Client)


PUNKTE = [{"lat": 47.80, "lon": 11.0}, {"lat": 47.83, "lon": 11.0}]


async def test_anfrage_sperrt_nach_gewicht_ausser_anlieger_frei(monkeypatch):
    gesendet: list = []
    monkeypatch.setattr(routing_svc, "httpx", _graphhopper(
        [_Antwort(200, _pfad({"max_weight": [[1, 2, 7.5]], "max_weight_except": [[1, 2, "destination"]]}))],
        gesendet,
    ))
    daten = await routing_svc.calculate_route(PUNKTE, {"max_height_m": 3.5, "max_weight_t": 12.0})

    [anfrage] = gesendet
    assert {"max_weight", "max_weight_except"} <= set(anfrage["details"])
    regeln = anfrage["custom_model"]["priority"]
    assert {"if": "max_height < 3.5", "multiply_by": "0"} in regeln
    assert {"if": "max_weight < 12.0 && max_weight_except != DESTINATION", "multiply_by": "0"} in regeln
    assert {"if": "max_weight < 12.0", "multiply_by": "0.05"} in regeln
    assert daten["max_weight_details"] == [[1, 2, 7.5]]
    assert daten["max_weight_except_details"] == [[1, 2, "destination"]]


async def test_ohne_max_weight_im_graphen_wird_ohne_gewicht_geroutet(monkeypatch):
    gesendet: list = []
    monkeypatch.setattr(routing_svc, "httpx", _graphhopper(
        [
            _Antwort(400, {"message": "Cannot find the path details: [max_weight, max_weight_except]"}),
            _Antwort(200, _pfad({"max_height": [[1, 2, 3.9]]})),
        ],
        gesendet,
    ))
    daten = await routing_svc.calculate_route(PUNKTE, {"max_height_m": 3.5, "max_weight_t": 12.0})

    assert len(gesendet) == 2
    zweite = gesendet[1]
    assert "max_weight" not in zweite["details"]
    assert all("max_weight" not in r["if"] for r in zweite["custom_model"]["priority"])
    # Die Höhe sperrt weiter.
    assert {"if": "max_height < 3.5", "multiply_by": "0"} in zweite["custom_model"]["priority"]
    assert daten["max_weight_details"] is None
    assert daten["max_height_details"] == [[1, 2, 3.9]]


async def test_andere_fehler_werden_nicht_ohne_gewicht_wiederholt(monkeypatch):
    gesendet: list = []
    monkeypatch.setattr(routing_svc, "httpx", _graphhopper(
        [_Antwort(500, {"message": "irgendwas anderes"})], gesendet,
    ))
    with pytest.raises(ValueError):
        await routing_svc.calculate_route(PUNKTE, {"max_weight_t": 12.0})
    assert len(gesendet) == 1


async def test_keine_verbindung_ist_ein_eigener_fehler(monkeypatch):
    monkeypatch.setattr(routing_svc, "httpx", _graphhopper(
        [_Antwort(400, {"message": "Connection between locations not found"})], [],
    ))
    with pytest.raises(routing_svc.RoutingNoConnectionError):
        await routing_svc.calculate_route(PUNKTE, {"max_weight_t": 12.0})


# ── Marschbefehl ─────────────────────────────────────────────────────────────


@pytest.fixture
def gedruckt(monkeypatch):
    texte: list[str] = []
    cell, multi_cell = pdf_svc._PDF.cell, pdf_svc._PDF.multi_cell

    def _cell(self, w=None, h=None, text="", *a, **k):
        texte.append(str(text))
        return cell(self, w, h, text, *a, **k)

    def _multi_cell(self, w, h=None, text="", *a, **k):
        texte.append(str(text))
        return multi_cell(self, w, h, text, *a, **k)

    monkeypatch.setattr(pdf_svc._PDF, "cell", _cell)
    monkeypatch.setattr(pdf_svc._PDF, "multi_cell", _multi_cell)
    return texte


def _befehl(eintraege, gewicht_t, *gewichte_kg):
    konvoi = SimpleNamespace(
        name="Kontingent BW 3", organization="KatS Musterstadt", start_time=None,
        lage=None, auftrag=None, marschform=None, ablaufpunkt=None, ablaufzeit=None,
        ablaufführer=None, versorgung=None, funkgruppe=None, anlagen=None,
        speed_urban_kmh=40, speed_rural_kmh=65,
    )
    route = SimpleNamespace(distance_m=3300, duration_s=240,
                            routing_params={"max_weight_t": gewicht_t} if gewicht_t else {})
    fahrzeuge = [
        {"name": f"Fz {i}", "callsign": None, "license_plate": None, "height_cm": None, "weight_kg": w,
         "convoy_role": None, "position": i, "sonderfunktion": None, "mobile_phone": None}
        for i, w in enumerate(gewichte_kg)
    ]
    return pdf_svc.generate_marschbefehl(konvoi, [], fahrzeuge, route, None, None, None, eintraege)


def test_marschbefehl_druckt_knappe_und_ueberschrittene_grenzen(gedruckt):
    eintraege = gg.grenzen(
        [[0, 1, 7.5], [1, 2, 12.0], [2, 3, 40.0]],
        [[1, 2, "destination"]],
        COORDS, 12.5,
    )
    assert _befehl(eintraege, 12.5, 12500, None).startswith(b"%PDF-")
    text = "\n".join(gedruckt)
    assert "Gewichtsgrenzen" in text
    assert "Schwerstes Fahrzeug: 12,5 t (1 Fahrzeug ohne Gewichtsangabe)" in text
    assert "12,0 t" in text and "-0,5 t" in text and "Anlieger frei" in text and "ÜBER DER GRENZE" in text
    assert "7,5 t" in text and "-5,0 t" in text
    assert "40,0 t" not in text
    assert "1 weitere Gewichtsgrenze mit mindestens 2 t Reserve." in text
    assert "Achslasten sind nicht berücksichtigt." in "".join(gedruckt)


def test_marschbefehl_ohne_fahrzeuggewicht_sagt_das(gedruckt):
    _befehl(gg.grenzen([[0, 1, 7.5]], [], COORDS, None), None, None)
    text = "\n".join(gedruckt)
    assert "Kein Fahrzeuggewicht erfasst" in text
    assert "Fahrzeuggewicht fehlt" in text


def test_ohne_ermittlung_kein_abschnitt(gedruckt):
    _befehl(None, 12.0, 12000)
    assert not any("Gewichtsgrenzen" in t for t in gedruckt)


# ── Durch die App ────────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
async def reset_db_engine():
    yield
    await engine.dispose()


@pytest.fixture
async def verband():
    """Wechsellader und MTW: hoch und schwer neben niedrig und leicht."""
    marker = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        user = User(email=f"gg-{marker}@test.invalid", hashed_password="x", is_active=True)
        db.add(user)
        await db.flush()
        org = Organization(name=f"Org {marker}", slug=f"org-{marker}", owner_id=user.id)
        db.add(org)
        await db.flush()
        db.add(UserOrganization(user_id=user.id, organization_id=org.id, role="planer"))
        convoy = Convoy(
            name=f"Verband {marker}", owner_id=user.id, organization_id=org.id,
            start_point=from_shape(Point(*COORDS[0]), srid=4326),
            end_point=from_shape(Point(*COORDS[-1]), srid=4326),
        )
        wlf = Vehicle(name=f"WLF {marker}", height_cm=390, weight_kg=26000, owner_id=user.id)
        mtw = Vehicle(name=f"MTW {marker}", height_cm=250, weight_kg=3500, owner_id=user.id)
        db.add_all([convoy, wlf, mtw])
        await db.flush()
        db.add_all([
            ConvoyVehicle(convoy_id=convoy.id, vehicle_id=mtw.id, position=0),
            ConvoyVehicle(convoy_id=convoy.id, vehicle_id=wlf.id, position=1),
        ])
        await db.commit()
        ids = SimpleNamespace(user_id=user.id, org_id=org.id, convoy_id=convoy.id, vehicle_ids=[wlf.id, mtw.id])

    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(id=ids.user_id, is_superadmin=False)
    app.dependency_overrides[get_token_data] = lambda: SimpleNamespace(user_id=str(ids.user_id), is_demo=False)
    yield ids
    app.dependency_overrides.clear()

    async with AsyncSessionLocal() as db:
        await db.execute(delete(Route).where(Route.convoy_id == ids.convoy_id))
        await db.execute(delete(ConvoyVehicle).where(ConvoyVehicle.convoy_id == ids.convoy_id))
        await db.execute(delete(Convoy).where(Convoy.id == ids.convoy_id))
        await db.execute(delete(Vehicle).where(Vehicle.id.in_(ids.vehicle_ids)))
        await db.execute(delete(UserOrganization).where(UserOrganization.organization_id == ids.org_id))
        await db.execute(delete(Organization).where(Organization.id == ids.org_id))
        await db.execute(delete(User).where(User.id == ids.user_id))
        await db.commit()


def _client():
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def test_berechnung_sperrt_mit_dem_groessten_und_speichert_die_liste(verband, monkeypatch):
    gesendet: list = []
    monkeypatch.setattr(routing_svc, "httpx", _graphhopper(
        [_Antwort(200, _pfad({"max_weight": [[1, 2, 30.0], [2, 3, 7.5]],
                               "max_weight_except": [[2, 3, "destination"]]}))],
        gesendet,
    ))
    async with _client() as client:
        berechnet = await client.post(f"/api/convoys/{verband.convoy_id}/calculate-route")
        geladen = await client.get(f"/api/convoys/{verband.convoy_id}/route")

    assert berechnet.status_code == 200, berechnet.text
    regeln = gesendet[0]["custom_model"]["priority"]
    assert {"if": "max_height < 3.9", "multiply_by": "0"} in regeln
    assert {"if": "max_weight < 26.0 && max_weight_except != DESTINATION", "multiply_by": "0"} in regeln
    liste = berechnet.json()["gewichtsgrenzen"]
    assert [(e["grenze_t"], e["stufe"], e["ausnahme"]) for e in liste] == [
        (30.0, "frei", None), (7.5, "ueberschritten", "destination"),
    ]
    assert geladen.json()["gewichtsgrenzen"] == liste
    assert geladen.json()["routing_params"] == {"max_height_m": 3.9, "max_weight_t": 26.0}


async def test_ohne_verbindung_nennt_die_meldung_die_grenzen(verband, monkeypatch):
    monkeypatch.setattr(routing_svc, "httpx", _graphhopper(
        [_Antwort(400, {"message": "Connection between locations not found"})], [],
    ))
    async with _client() as client:
        antwort = await client.post(f"/api/convoys/{verband.convoy_id}/calculate-route")
    assert antwort.status_code == 422
    assert "Höhe 3,90 m, Gewicht 26,0 t" in antwort.json()["detail"]
