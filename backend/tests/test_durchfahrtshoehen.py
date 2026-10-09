"""Durchfahrtshöhen: unter welchen Höhenbeschränkungen die Route hindurchführt.

Gesperrt hat das Routing schon vorher — still. Die Zusagen hier:

- jede Beschränkung, die GraphHopper an der Route meldet, steht in der Liste,
  mit Kilometer und Spielraum zum höchsten Fahrzeug; unbegrenzte Abschnitte
  stehen nicht drin;
- unter 10 cm Spielraum heißt die Stelle ``eng``, weil GraphHopper die Höhe auf
  10 cm rundet und aus 3,85 m auf dem Schild 3,9 m macht;
- ohne Fahrzeughöhe wird nichts beurteilt, aber alles gezeigt;
- der Marschbefehl druckt, was nicht ``frei`` ist, und sagt, woher die Zahlen
  stammen;
- eine alte Route (``None``) bleibt von einer ohne Beschränkung (``[]``)
  unterscheidbar.
"""

import uuid
from types import SimpleNamespace

import pytest
from geoalchemy2.shape import from_shape
from httpx import ASGITransport, AsyncClient
from shapely.geometry import Point
from sqlalchemy import delete, select

from app.api.deps import get_current_user, get_token_data
from app.database import AsyncSessionLocal, engine
from app.main import app
from app.models.convoy import Convoy, ConvoyVehicle
from app.models.organization import Organization, UserOrganization
from app.models.route import Route
from app.models.user import User
from app.models.vehicle import Vehicle
from app.services import durchfahrtshoehe as dh
from app.services import pdf as pdf_svc
from app.services import route_steps
from app.services import routing as routing_svc

# Vier Stützpunkte nach Norden, je etwa 1,1 km.
COORDS = [[11.0, 47.80], [11.0, 47.81], [11.0, 47.82], [11.0, 47.83]]
KM = [round(m / 1000, 1) for m in route_steps.cumulative_m(COORDS)]


# ── Rechnung ohne Datenbank ──────────────────────────────────────────────────


def test_beschraenkungen_stehen_mit_kilometer_und_spielraum_in_der_liste():
    details = [[0, 1, None], [1, 2, 4.0], [2, 3, None]]

    [eintrag] = dh.engstellen(details, COORDS, 3.65)

    assert eintrag["km"] == KM[1]
    assert (eintrag["lon"], eintrag["lat"]) == tuple(COORDS[1])
    assert eintrag["hoehe_m"] == 4.0
    assert eintrag["spielraum_m"] == 0.35
    assert eintrag["stufe"] == "frei"
    assert eintrag["laenge_m"] == pytest.approx(1112, abs=2)


def test_graphhoppers_kommastellen_werden_auf_das_raster_gerundet():
    # 0.1 * 39 ist in Gleitkomma 3.9000000000000004.
    [eintrag] = dh.engstellen([[0, 1, 0.1 * 39]], COORDS, 3.8)
    assert eintrag["hoehe_m"] == 3.9
    assert eintrag["spielraum_m"] == 0.1


@pytest.mark.parametrize(
    "spielraum, stufe",
    [
        (-0.05, "eng"),  # gibt es nach der Sperre nicht, aber wenn, dann eng
        (0.0, "eng"),
        (0.09, "eng"),
        (dh.ENG_M, "knapp"),
        (0.29, "knapp"),
        (dh.KNAPP_M, "frei"),
        (None, "unbekannt"),
    ],
)
def test_stufen(spielraum, stufe):
    assert dh.stufe(spielraum) == stufe


def test_unter_zehn_zentimetern_ist_die_rundung_im_spiel():
    # Schild 3,85 m, im Graphen 3,9 m; das Fahrzeug misst 3,82 m.
    [eintrag] = dh.engstellen([[1, 2, 3.9]], COORDS, 3.82)
    assert eintrag["stufe"] == "eng"


def test_ohne_fahrzeughoehe_wird_gezeigt_aber_nicht_beurteilt():
    eintraege = dh.engstellen([[0, 1, 3.5], [2, 3, 4.5]], COORDS, None)
    assert [e["spielraum_m"] for e in eintraege] == [None, None]
    assert [e["stufe"] for e in eintraege] == ["unbekannt", "unbekannt"]
    assert dh.hinweispflichtig(eintraege) == eintraege


@pytest.mark.parametrize(
    "wert",
    [None, "Infinity", float("inf"), float("nan"), 0, -1, 12.6, True, "abc"],
)
def test_was_keine_beschraenkung_ist_steht_nicht_in_der_liste(wert):
    # 12,6 m ist das Ende des Wertebereichs im Graphen, kein Schild.
    assert dh.engstellen([[0, 1, wert]], COORDS, 3.0) == []


@pytest.mark.parametrize("eintrag", [[], [0], [0, 1], None, ["a", 1, 3.5], "x"])
def test_kaputte_eintraege_werden_uebergangen(eintrag):
    assert dh.engstellen([eintrag, [1, 2, 3.5]], COORDS, 3.0)[0]["hoehe_m"] == 3.5


def test_indizes_ausserhalb_der_geometrie_werden_begrenzt():
    [eintrag] = dh.engstellen([[2, 99, 3.5]], COORDS, 3.0)
    assert eintrag["km"] == KM[2]
    assert eintrag["laenge_m"] == pytest.approx(1112, abs=2)


def test_ohne_details_oder_geometrie_keine_liste():
    assert dh.engstellen([], COORDS, 3.0) == []
    assert dh.engstellen([[0, 1, 3.5]], COORDS[:1], 3.0) == []


def test_hinweispflichtig_ist_alles_ausser_frei():
    eintraege = dh.engstellen([[0, 1, 3.7], [1, 2, 3.8], [2, 3, 5.0]], COORDS, 3.62)
    assert [e["stufe"] for e in eintraege] == ["eng", "knapp", "frei"]
    assert [e["stufe"] for e in dh.hinweispflichtig(eintraege)] == ["eng", "knapp"]


# ── Anfrage an GraphHopper ───────────────────────────────────────────────────


def _graphhopper(gesendet: dict, details: dict):
    class _Resp:
        status_code = 200
        is_success = True

        def json(self):
            return {"paths": [{
                "distance": 3300.0,
                "time": 240_000,
                "points": {"type": "LineString", "coordinates": COORDS},
                "details": details,
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
            gesendet.update(json)
            return _Resp()

    # Nur das httpx des Routing-Dienstes — der Testclient braucht das echte.
    return SimpleNamespace(AsyncClient=_Client)


async def test_graphhopper_wird_nach_max_height_gefragt(monkeypatch):
    gesendet: dict = {}
    monkeypatch.setattr(
        routing_svc, "httpx", _graphhopper(gesendet, {"max_height": [[1, 2, 3.9]]})
    )
    daten = await routing_svc.calculate_route(
        [{"lat": 47.80, "lon": 11.0}, {"lat": 47.83, "lon": 11.0}], {"max_height_m": 3.5}
    )
    assert "max_height" in gesendet["details"]
    assert daten["max_height_details"] == [[1, 2, 3.9]]
    # Die Sperre bleibt, wie sie war.
    assert {"if": "max_height < 3.5", "multiply_by": "0"} in gesendet["custom_model"]["priority"]


# ── Marschbefehl ─────────────────────────────────────────────────────────────


@pytest.fixture
def gedruckt(monkeypatch):
    """Was in Zellen des PDFs landet — als Text, nicht als Glyphen-IDs."""
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


def _konvoi():
    return SimpleNamespace(
        name="Kontingent BW 3", organization="KatS Musterstadt", start_time=None,
        lage=None, auftrag=None, marschform=None, ablaufpunkt=None, ablaufzeit=None,
        ablaufführer=None, versorgung=None, funkgruppe=None, anlagen=None,
        speed_urban_kmh=40, speed_rural_kmh=65,
    )


def _fahrzeuge(*hoehen_cm):
    return [
        {"name": f"Fz {i}", "callsign": None, "license_plate": None, "height_cm": h,
         "weight_kg": None, "convoy_role": None, "position": i, "sonderfunktion": None,
         "mobile_phone": None}
        for i, h in enumerate(hoehen_cm)
    ]


def _befehl(eintraege, *hoehen_cm):
    berechnet = [h for h in hoehen_cm if h]
    route = SimpleNamespace(
        distance_m=3300, duration_s=240,
        routing_params={"max_height_m": max(berechnet) / 100} if berechnet else {},
    )
    return pdf_svc.generate_marschbefehl(_konvoi(), [], _fahrzeuge(*hoehen_cm), route, None, eintraege)


def test_marschbefehl_druckt_enge_und_knappe_stellen_und_zaehlt_den_rest(gedruckt):
    eintraege = dh.engstellen([[0, 1, 3.7], [1, 2, 3.8], [2, 3, 5.0]], COORDS, 3.62)
    assert _befehl(eintraege, 362, None).startswith(b"%PDF-")
    text = "\n".join(gedruckt)

    assert "Durchfahrtshöhen" in text
    assert "Höchstes Fahrzeug: 3,62 m (1 Fahrzeug ohne Höhenangabe)" in text
    assert "3,7 m" in text and "+8 cm" in text and "ENG – vor Ort prüfen" in text
    assert "3,8 m" in text and "+18 cm" in text
    assert "5,0 m" not in text
    assert "1 weitere Höhenbeschränkung mit mindestens 30 cm Spielraum." in text
    assert "Maßgeblich ist die Beschilderung vor Ort." in text


def test_marschbefehl_nennt_die_hoehe_der_berechnung_nicht_die_heutige(gedruckt):
    # Seit der Berechnung kam ein höheres Fahrzeug dazu; der Spielraum in der
    # Tabelle stammt aber aus der Berechnung — beides muss zusammenpassen.
    route = SimpleNamespace(distance_m=3300, duration_s=240, routing_params={"max_height_m": 3.2})
    eintraege = dh.engstellen([[0, 1, 3.3]], COORDS, 3.2)
    pdf_svc.generate_marschbefehl(_konvoi(), [], _fahrzeuge(320, 400), route, None, eintraege)
    text = "\n".join(gedruckt)
    assert "Höchstes Fahrzeug: 3,20 m" in text
    assert "+10 cm" in text


def test_marschbefehl_ohne_fahrzeughoehe_sagt_das(gedruckt):
    _befehl(dh.engstellen([[0, 1, 3.5]], COORDS, None), None)
    text = "\n".join(gedruckt)
    assert "Keine Fahrzeughöhe erfasst" in text
    assert "Fahrzeughöhe fehlt" in text


def test_marschbefehl_ohne_beschraenkung_sagt_das(gedruckt):
    _befehl([], 320)
    assert any("Keine Höhenbeschränkung auf der Strecke bekannt." in t for t in gedruckt)


def test_alte_route_ohne_auswertung_bekommt_keinen_abschnitt(gedruckt):
    _befehl(None, 320)
    assert not any("Durchfahrtshöhen" in t for t in gedruckt)


# ── Durch die App ────────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
async def reset_db_engine():
    """Verbindungspool nach jedem Test schließen (siehe test_betriebsstoff.py)."""
    yield
    await engine.dispose()


@pytest.fixture
async def verband():
    """Ein Verband mit Start, Ziel und zwei Fahrzeugen — eines ohne Höhe."""
    marker = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        user = User(email=f"dh-{marker}@test.invalid", hashed_password="x", is_active=True)
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
        hoch = Vehicle(name=f"WLF {marker}", height_cm=365, owner_id=user.id)
        ohne = Vehicle(name=f"MTW {marker}", owner_id=user.id)
        db.add_all([convoy, hoch, ohne])
        await db.flush()
        db.add_all([
            ConvoyVehicle(convoy_id=convoy.id, vehicle_id=hoch.id, position=0),
            ConvoyVehicle(convoy_id=convoy.id, vehicle_id=ohne.id, position=1),
        ])
        await db.commit()
        ids = SimpleNamespace(user_id=user.id, org_id=org.id, convoy_id=convoy.id,
                              vehicle_ids=[hoch.id, ohne.id])

    app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(
        id=ids.user_id, is_superadmin=False
    )
    # Das Routing-Kontingent (api/quota.py) liest das Token selbst.
    app.dependency_overrides[get_token_data] = lambda: SimpleNamespace(
        user_id=str(ids.user_id), is_demo=False
    )
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


async def test_berechnung_speichert_die_liste_und_liefert_sie_wieder_aus(verband, monkeypatch):
    gesendet: dict = {}
    monkeypatch.setattr(
        routing_svc, "httpx",
        _graphhopper(gesendet, {"max_height": [[0, 1, None], [1, 2, 3.7], [2, 3, None]]}),
    )
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        berechnet = await client.post(f"/api/convoys/{verband.convoy_id}/calculate-route")
        assert berechnet.status_code == 200, berechnet.text
        geladen = await client.get(f"/api/convoys/{verband.convoy_id}/route")

    # Gesperrt wird mit dem höchsten Fahrzeug, beurteilt mit demselben.
    assert {"if": "max_height < 3.65", "multiply_by": "0"} in gesendet["custom_model"]["priority"]
    erwartet = [{
        "km": KM[1], "lat": COORDS[1][1], "lon": COORDS[1][0],
        "laenge_m": pytest.approx(1112, abs=2), "hoehe_m": 3.7, "spielraum_m": 0.05, "stufe": "eng",
    }]
    assert berechnet.json()["durchfahrtshoehen"] == erwartet
    assert geladen.json()["durchfahrtshoehen"] == erwartet


async def test_alte_route_ist_nicht_ermittelt_statt_leer(verband):
    from shapely.geometry import LineString

    async with AsyncSessionLocal() as db:
        db.add(Route(convoy_id=verband.convoy_id, distance_m=3300, duration_s=240,
                     geometry=from_shape(LineString(COORDS), srid=4326)))
        await db.commit()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        geladen = await client.get(f"/api/convoys/{verband.convoy_id}/route")
    assert geladen.json()["durchfahrtshoehen"] is None

    async with AsyncSessionLocal() as db:
        route = (await db.execute(select(Route).where(Route.convoy_id == verband.convoy_id))).scalar_one()
        assert route.durchfahrtshoehen is None
