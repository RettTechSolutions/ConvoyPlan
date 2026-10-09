"""Brücken über der Route, für die OSM keine Durchfahrtshöhe kennt.

Die Zusagen:

- eine Brücke, die die Route kreuzt, steht in der Liste, mit Kilometer und Art;
- eine Brücke, auf der die Route selbst fährt, steht nicht drin — auch wenn die
  Koordinaten von GraphHopper und Overpass nicht bitgleich sind;
- ein Weg, der nur an die Route anschließt, ist keine Überführung;
- was Stufe 1 schon mit Höhe kennt, steht nicht doppelt da;
- zwei Fahrbahnen oder Gleise an einer Stelle sind ein Eintrag;
- Abschnitte auf Autobahn und Kraftfahrstraße sind markiert, damit Planung und
  Marschbefehl sie zählen statt auflisten;
- eine Neuberechnung verwirft das Ergebnis, und ein Ergebnis zur alten Linie wird
  nicht gespeichert.
"""

import uuid
from types import SimpleNamespace

import pytest
from geoalchemy2.shape import from_shape
from httpx import ASGITransport, AsyncClient
from shapely.geometry import LineString, Point
from sqlalchemy import delete, select

from app.api.deps import get_current_user, get_token_data
from app.api.routes import routing as routing_routes
from app.database import AsyncSessionLocal, engine
from app.main import app
from app.models.convoy import Convoy, ConvoyVehicle
from app.models.organization import Organization, UserOrganization
from app.models.route import Route
from app.models.user import User
from app.models.vehicle import Vehicle
from app.services import bruecken as br
from app.services import pdf as pdf_svc
from app.services import route_steps
from app.services import routing as routing_svc

# Nach Norden, Stützpunkte alle ~1,1 km.
COORDS = [[11.0, 47.80], [11.0, 47.81], [11.0, 47.82], [11.0, 47.83]]
M_PRO_GRAD = route_steps.cumulative_m(COORDS)[1] / 0.01


def _m(lat: float) -> float:
    return (lat - 47.80) * M_PRO_GRAD


def weg(osm_id: int, punkte: list[tuple[float, float]], **tags) -> dict:
    return {
        "type": "way", "id": osm_id, "tags": {"bridge": "yes", **tags},
        "geometry": [{"lon": lon, "lat": lat} for lon, lat in punkte],
    }


def ueberfuehrung(osm_id: int, lat: float, **tags) -> dict:
    """Ein Weg quer über die Route bei ``lat``, ohne gemeinsamen Knoten."""
    return weg(osm_id, [(10.999, lat), (11.001, lat)], **tags)


# ── Kreuzungen ───────────────────────────────────────────────────────────────


def test_eine_ueberfuehrung_steht_mit_kilometer_und_art_da():
    [b] = br.kreuzungen(COORDS, [ueberfuehrung(7, 47.815, railway="rail", name="Ammertalbahn")])

    assert b["m"] == pytest.approx(_m(47.815), abs=2)
    assert b["km"] == round(_m(47.815) / 1000, 1)
    assert (b["lon"], b["lat"]) == pytest.approx((11.0, 47.815))
    assert b["art"] == "Eisenbahnbrücke"
    assert b["name"] == "Ammertalbahn"
    assert b["osm_ids"] == [7]
    assert b["schnellstrasse"] is False


@pytest.mark.parametrize(
    "tags, art",
    [
        ({"highway": "footway"}, "Fuß-/Radwegbrücke"),
        ({"highway": "cycleway"}, "Fuß-/Radwegbrücke"),
        ({"highway": "secondary"}, "Straßenbrücke"),
        ({"waterway": "canal"}, "Kanalbrücke"),
        ({}, "Brücke"),
    ],
)
def test_die_art_kommt_aus_den_tags(tags, art):
    [b] = br.kreuzungen(COORDS, [ueberfuehrung(1, 47.815, **tags)])
    assert b["art"] == art


def test_auf_der_bruecke_faehrt_die_route_selbst():
    # Dieselben Knoten wie die Route: die Schnittmenge ist ein Linienstück.
    darauf = weg(1, [(11.0, 47.812), (11.0, 47.813)], highway="primary")
    assert br.kreuzungen(COORDS, [darauf]) == []


def test_auch_wenn_die_koordinaten_nicht_bitgleich_sind():
    # Um Zehntelmeter versetzt und dabei hin und her über die Linie — exakt
    # verglichen wären das zwei Kreuzungen.
    darauf = weg(1, [(11.0000003, 47.812), (10.9999997, 47.8125), (11.0000003, 47.813)], highway="primary")
    assert br.kreuzungen(COORDS, [darauf]) == []


def test_ein_anschluss_an_einem_knoten_ist_keine_ueberfuehrung():
    am_ende = weg(1, [(11.0, 47.82), (11.002, 47.82)], highway="service")
    mittendurch = weg(2, [(10.999, 47.825), (11.0, 47.825), (11.001, 47.825)], highway="track")
    assert br.kreuzungen(COORDS, [am_ende, mittendurch]) == []


def test_eine_bruecke_neben_der_route_kreuzt_nicht():
    daneben = weg(1, [(11.001, 47.81), (11.002, 47.81)], highway="primary")
    assert br.kreuzungen(COORDS, [daneben]) == []


def test_zwei_fahrbahnen_an_einer_stelle_sind_ein_eintrag():
    [b] = br.kreuzungen(COORDS, [
        ueberfuehrung(1, 47.8150, highway="primary", ref="B 472"),
        ueberfuehrung(2, 47.8152, railway="rail"),
    ])
    assert b["osm_ids"] == [1, 2]
    assert b["art"] == "Straßenbrücke / Eisenbahnbrücke"
    assert b["name"] == "B 472"


def test_entfernte_bruecken_bleiben_getrennt_und_in_fahrtrichtung():
    eintraege = br.kreuzungen(COORDS, [ueberfuehrung(2, 47.825), ueberfuehrung(1, 47.805)])
    assert [b["osm_ids"] for b in eintraege] == [[1], [2]]


def test_was_stufe_eins_mit_hoehe_kennt_steht_nicht_doppelt_da():
    m = _m(47.815)
    bekannt = [{"km": round(m / 1000, 1), "m": round(m) - 10, "laenge_m": 20}]
    assert br.kreuzungen(COORDS, [ueberfuehrung(1, 47.815)], bekannt) == []
    # 100 m daneben ist eine andere Brücke.
    weiter = [{"km": 0, "m": round(m) - 150, "laenge_m": 20}]
    assert len(br.kreuzungen(COORDS, [ueberfuehrung(1, 47.815)], weiter)) == 1


def test_auf_schnellstrassen_markiert():
    m = round(_m(47.815))
    [b] = br.kreuzungen(COORDS, [ueberfuehrung(1, 47.815)], [], [[m - 500, m + 500]])
    assert b["schnellstrasse"] is True


@pytest.mark.parametrize(
    "element",
    [
        {"type": "node", "id": 1, "lat": 47.815, "lon": 11.0},
        {"type": "way", "id": 1, "tags": {}},
        {"type": "way", "id": 1, "geometry": [{"lon": 11.0, "lat": 47.815}]},
    ],
)
def test_unbrauchbare_elemente_werden_uebergangen(element):
    assert br.kreuzungen(COORDS, [element, ueberfuehrung(2, 47.825)])[0]["osm_ids"] == [2]


# ── Abfrage und Straßenklassen ───────────────────────────────────────────────


def test_die_abfrage_sucht_brueckenwege_im_korridor_in_lat_lon():
    q = br.abfrage(COORDS)
    assert f'way["bridge"]["bridge"!="no"](around:{br.KORRIDOR_M},47.800000,11.000000,' in q
    assert "out tags geom;" in q
    # Eine gerade Linie wird auf Anfang und Ende vereinfacht.
    assert q.count("way[") == 1


def test_lange_routen_werden_in_stuecken_abgefragt():
    zickzack = [[11.0 + (i % 2) * 0.001, 47.0 + i * 0.001] for i in range(1000)]
    q = br.abfrage(zickzack)
    assert q.count("way[") == 3  # 999 Strecken, je 400


def test_schnellstrassen_aus_road_class():
    details = [[0, 1, "motorway"], [1, 2, "trunk"], [2, 3, "primary"]]
    [bereich] = br.schnellstrassen(details, COORDS)
    along = route_steps.cumulative_m(COORDS)
    assert bereich == [0, round(along[2])]
    assert br.schnellstrassen([[0, 3, "PRIMARY"]], COORDS) == []
    assert br.schnellstrassen([], COORDS) == []


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


def _befehl(bruecken):
    konvoi = SimpleNamespace(
        name="Kontingent BW 3", organization="KatS Musterstadt", start_time=None,
        lage=None, auftrag=None, marschform=None, ablaufpunkt=None, ablaufzeit=None,
        ablaufführer=None, versorgung=None, funkgruppe=None, anlagen=None,
        speed_urban_kmh=40, speed_rural_kmh=65,
    )
    route = SimpleNamespace(distance_m=3300, duration_s=240, routing_params={"max_height_m": 3.4})
    fahrzeug = {"name": "WLF", "callsign": None, "license_plate": None, "height_cm": 340, "weight_kg": None,
                "convoy_role": None, "position": 0, "sonderfunktion": None, "mobile_phone": None}
    return pdf_svc.generate_marschbefehl(konvoi, [], [fahrzeug], route, None, [], bruecken)


def test_marschbefehl_listet_bruecken_und_zaehlt_schnellstrassen(gedruckt):
    eintraege = br.kreuzungen(
        COORDS,
        [ueberfuehrung(1, 47.805, highway="footway", name="Steg am Sportplatz"),
         ueberfuehrung(2, 47.825, highway="primary")],
        [], [[round(_m(47.82)), round(_m(47.83))]],
    )
    assert _befehl({"geprueft_at": "2026-10-09T10:00:00+00:00", "eintraege": eintraege}).startswith(b"%PDF-")
    text = "\n".join(gedruckt)
    assert "Brücken ohne Höhenangabe" in text
    assert "Fuß-/Radwegbrücke" in text and "Steg am Sportplatz" in text
    assert "1 weitere auf Autobahn- oder Kraftfahrstraßenabschnitten, nicht einzeln aufgeführt." in text


def test_marschbefehl_sagt_wenn_nicht_gesucht_wurde(gedruckt):
    _befehl(None)
    assert any(t.startswith("Nicht gesucht") for t in gedruckt)


def test_marschbefehl_sagt_wenn_nichts_gefunden_wurde(gedruckt):
    _befehl({"geprueft_at": "2026-10-09T10:00:00+00:00", "eintraege": []})
    assert "Keine Brücke ohne Höhenangabe über der Route gefunden." in gedruckt


# ── Durch die App ────────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
async def reset_db_engine():
    yield
    await engine.dispose()


@pytest.fixture
async def verband():
    marker = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        user = User(email=f"br-{marker}@test.invalid", hashed_password="x", is_active=True)
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
        fz = Vehicle(name=f"WLF {marker}", height_cm=340, owner_id=user.id)
        db.add_all([convoy, fz])
        await db.flush()
        db.add(ConvoyVehicle(convoy_id=convoy.id, vehicle_id=fz.id, position=0))
        await db.commit()
        ids = SimpleNamespace(user_id=user.id, org_id=org.id, convoy_id=convoy.id, vehicle_id=fz.id)

    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(id=ids.user_id, is_superadmin=False)
    app.dependency_overrides[get_token_data] = lambda: SimpleNamespace(user_id=str(ids.user_id), is_demo=False)
    yield ids
    app.dependency_overrides.clear()

    async with AsyncSessionLocal() as db:
        await db.execute(delete(Route).where(Route.convoy_id == ids.convoy_id))
        await db.execute(delete(ConvoyVehicle).where(ConvoyVehicle.convoy_id == ids.convoy_id))
        await db.execute(delete(Convoy).where(Convoy.id == ids.convoy_id))
        await db.execute(delete(Vehicle).where(Vehicle.id == ids.vehicle_id))
        await db.execute(delete(UserOrganization).where(UserOrganization.organization_id == ids.org_id))
        await db.execute(delete(Organization).where(Organization.id == ids.org_id))
        await db.execute(delete(User).where(User.id == ids.user_id))
        await db.commit()


def _graphhopper(coords=COORDS):
    class _Resp:
        status_code = 200
        is_success = True

        def json(self):
            return {"paths": [{
                "distance": 3300.0, "time": 240_000,
                "points": {"type": "LineString", "coordinates": coords},
                "details": {
                    "max_height": [[0, 1, 3.6], [1, 3, None]],
                    "road_class": [[0, 2, "primary"], [2, 3, "motorway"]],
                },
                "instructions": [],
            }]}

    class _Client:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def post(self, url, json):
            return _Resp()

    return SimpleNamespace(AsyncClient=_Client)


def _client():
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def _berechnen(client, verband):
    antwort = await client.post(f"/api/convoys/{verband.convoy_id}/calculate-route")
    assert antwort.status_code == 200, antwort.text
    return antwort.json()


OVERPASS = [
    ueberfuehrung(1, 47.805, highway="secondary"),   # im Abschnitt mit 3,6 m — bekannt
    ueberfuehrung(2, 47.815, railway="rail"),        # unbekannt
    ueberfuehrung(3, 47.825, highway="primary"),     # unbekannt, Autobahn
]


async def test_suche_speichert_und_route_liefert_sie_aus(verband, monkeypatch):
    monkeypatch.setattr(routing_svc, "httpx", _graphhopper())
    gefragt: list = []

    async def _overpass(coords):
        gefragt.append(coords)
        return OVERPASS

    monkeypatch.setattr(routing_routes.overpass_svc, "bruecken_entlang", _overpass)

    async with _client() as client:
        berechnet = await _berechnen(client, verband)
        assert berechnet["bruecken"] is None
        gesucht = await client.post(f"/api/convoys/{verband.convoy_id}/route/bruecken")
        geladen = await client.get(f"/api/convoys/{verband.convoy_id}/route")

    assert gesucht.status_code == 200, gesucht.text
    assert [[list(c) for c in coords] for coords in gefragt] == [COORDS]
    eintraege = gesucht.json()["eintraege"]
    assert [(b["osm_ids"], b["schnellstrasse"]) for b in eintraege] == [([2], False), ([3], True)]
    assert geladen.json()["bruecken"] == gesucht.json()


async def test_neuberechnung_verwirft_die_suche(verband, monkeypatch):
    monkeypatch.setattr(routing_svc, "httpx", _graphhopper())

    async def _overpass(coords):
        return OVERPASS

    monkeypatch.setattr(routing_routes.overpass_svc, "bruecken_entlang", _overpass)
    async with _client() as client:
        await _berechnen(client, verband)
        await client.post(f"/api/convoys/{verband.convoy_id}/route/bruecken")
        await _berechnen(client, verband)
        geladen = await client.get(f"/api/convoys/{verband.convoy_id}/route")
    assert geladen.json()["bruecken"] is None


async def test_ohne_overpass_bleibt_es_ungesucht(verband, monkeypatch):
    monkeypatch.setattr(routing_svc, "httpx", _graphhopper())

    async def _overpass(coords):
        raise RuntimeError("alle Spiegel überlastet")

    monkeypatch.setattr(routing_routes.overpass_svc, "bruecken_entlang", _overpass)
    async with _client() as client:
        await _berechnen(client, verband)
        gesucht = await client.post(f"/api/convoys/{verband.convoy_id}/route/bruecken")
    assert gesucht.status_code == 502
    async with AsyncSessionLocal() as db:
        route = (await db.execute(select(Route).where(Route.convoy_id == verband.convoy_id))).scalar_one()
        assert route.bruecken is None


async def test_ergebnis_zur_alten_linie_wird_nicht_gespeichert(verband, monkeypatch):
    monkeypatch.setattr(routing_svc, "httpx", _graphhopper())

    async def _overpass(coords):
        # Während der Abfrage rechnet jemand anderes die Route neu.
        async with AsyncSessionLocal() as db:
            route = (await db.execute(select(Route).where(Route.convoy_id == verband.convoy_id))).scalar_one()
            route.geometry = from_shape(LineString([[11.0, 47.80], [11.01, 47.83]]), srid=4326)
            await db.commit()
        return OVERPASS

    monkeypatch.setattr(routing_routes.overpass_svc, "bruecken_entlang", _overpass)
    async with _client() as client:
        await _berechnen(client, verband)
        gesucht = await client.post(f"/api/convoys/{verband.convoy_id}/route/bruecken")
    assert gesucht.status_code == 409
    async with AsyncSessionLocal() as db:
        route = (await db.execute(select(Route).where(Route.convoy_id == verband.convoy_id))).scalar_one()
        assert route.bruecken is None


async def test_ohne_route_gibt_es_nichts_zu_suchen(verband):
    async with _client() as client:
        gesucht = await client.post(f"/api/convoys/{verband.convoy_id}/route/bruecken")
    assert gesucht.status_code == 404
