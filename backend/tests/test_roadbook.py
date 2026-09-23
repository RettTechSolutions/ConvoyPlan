"""Roadbook: Karte und Navigationsanweisungen zum Ausdrucken.

Geprüft wird, was man dem fertigen Blatt nicht ansieht: dass jeder
„Wegpunkt erreicht" den richtigen Wegpunkt nennt, dass die Kilometrierung
aufläuft, dass GraphHoppers Pkw-Fahrzeit nicht mitgespeichert wird — und dass
es ein Roadbook auch dann gibt, wenn der Kachelserver nicht antwortet.
Nichts hier braucht Netz, Datenbank oder GraphHopper.
"""
import re
import uuid
from datetime import datetime
from io import BytesIO
from types import SimpleNamespace

import httpx
import pytest
from fastapi import HTTPException
from geoalchemy2.shape import from_shape
from PIL import Image
from shapely.geometry import LineString

from app.config import settings
from app.services import roadbook, static_map
from app.services import routing as routing_svc


def _wp(name, typ="waypoint", **kw):
    return SimpleNamespace(
        id=uuid.uuid4(),
        name=name,
        type=typ,
        planned_arrival=kw.get("arrival"),
        planned_departure=kw.get("departure"),
        hold_duration_min=kw.get("hold", 0),
        halt_purpose=kw.get("purpose"),
        notes=kw.get("notes"),
    )


# ── Anfrage und Speicherform ─────────────────────────────────────────────────


async def test_graphhopper_wird_nach_deutschen_anweisungen_gefragt(monkeypatch):
    gesendet = {}

    class _Resp:
        status_code = 200
        is_success = True

        def json(self):
            return {"paths": [{
                "distance": 1500.0,
                "time": 90_000,
                "points": {"type": "LineString", "coordinates": [[9.0, 48.0], [9.01, 48.01]]},
                "instructions": [
                    {"sign": 2, "text": "Rechts abbiegen auf B 27", "distance": 1500.4,
                     "time": 90_000, "interval": [0, 1], "street_name": "Hauptstraße",
                     "street_ref": "B 27"},
                    {"sign": 4, "text": "Ziel erreicht!", "distance": 0, "time": 0, "interval": [1, 1]},
                ],
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

    monkeypatch.setattr(httpx, "AsyncClient", _Client)
    daten = await routing_svc.calculate_route([{"lat": 48.0, "lon": 9.0}, {"lat": 48.01, "lon": 9.01}])

    assert gesendet["instructions"] is True
    assert gesendet["locale"] == "de"
    erste = daten["instructions"][0]
    assert erste == {
        "sign": 2, "text": "Rechts abbiegen auf B 27", "distance_m": 1500.4,
        "street_name": "Hauptstraße", "street_ref": "B 27",
    }
    # GraphHoppers Pkw-Zeit widerspräche auf dem Ausdruck den Planzeiten.
    assert all("time" not in i for i in daten["instructions"])


def test_jeder_zwischenpunkt_bekommt_seinen_wegpunkt_in_reihenfolge():
    anweisungen = [
        {"sign": 0, "text": "a"},
        {"sign": 5, "text": "Wegpunkt 1 erreicht"},
        {"sign": 2, "text": "b"},
        {"sign": 5, "text": "Wegpunkt 2 erreicht"},
        {"sign": 4, "text": "Ziel"},
    ]
    verknuepft = roadbook.link_waypoints(anweisungen, ["erster", "zweiter"])
    assert [i.get("waypoint_id") for i in verknuepft] == [None, "erster", None, "zweiter", None]
    # Das Original bleibt unberührt.
    assert "waypoint_id" not in anweisungen[1]


# ── Zeilen ───────────────────────────────────────────────────────────────────


def test_zeilen_nennen_wegpunkt_mit_nummer_planzeiten_und_halt():
    tank = _wp("Rastplatz Gruibingen", "technical_stop",
               arrival=datetime(2026, 9, 24, 9, 42), departure=datetime(2026, 9, 24, 10, 12),
               hold=30, purpose="fuel")
    kontrolle = _wp("Merklingen", "checkpoint", notes="Meldung an Leitstelle")
    anweisungen = roadbook.link_waypoints([
        {"sign": 0, "text": "Weiter auf Pragstraße", "distance_m": 850.0},
        {"sign": 5, "text": "Wegpunkt 1 erreicht", "distance_m": 0.0},
        {"sign": 2, "text": "Rechts abbiegen", "distance_m": 1200.0},
        {"sign": 5, "text": "Wegpunkt 2 erreicht", "distance_m": 0.0},
        {"sign": 4, "text": "Ziel erreicht!", "distance_m": 0.0},
    ], [str(tank.id), str(kontrolle.id)])

    zeilen = roadbook.build_rows(anweisungen, [tank, kontrolle], datetime(2026, 9, 24, 11, 55))

    assert [z.kind for z in zeilen] == ["turn", "waypoint", "turn", "waypoint", "finish"]
    assert zeilen[1].text == "Wegpunkt 1: Rastplatz Gruibingen"
    assert "an 09:42" in zeilen[1].detail and "ab 10:12" in zeilen[1].detail
    assert "30 min Halt (Betriebsstoff)" in zeilen[1].detail
    assert zeilen[3].text == "Wegpunkt 2: Merklingen"
    assert "Meldung an Leitstelle" in zeilen[3].detail
    assert zeilen[4].detail == "an 11:55"
    # Kilometrierung: wo das Manöver stattfindet, nicht wo es endet.
    assert [round(z.km_at, 2) for z in zeilen] == [0.0, 0.85, 0.85, 2.05, 2.05]


def test_geloeschter_wegpunkt_laesst_graphhoppers_text_stehen():
    zeilen = roadbook.build_rows(
        [{"sign": 5, "text": "Wegpunkt 1 erreicht", "distance_m": 0, "waypoint_id": "weg"}], []
    )
    assert zeilen[0].text == "Wegpunkt 1 erreicht"
    assert zeilen[0].kind == "waypoint"


def test_strassennummer_steht_dabei_aber_nicht_doppelt():
    zeilen = roadbook.build_rows([
        {"sign": 2, "text": "Rechts abbiegen auf Pragstraße", "street_ref": "B 10", "distance_m": 1},
        {"sign": 1, "text": "Leicht rechts auf A 8", "street_ref": "A 8", "distance_m": 1,
         "street_destination": "München"},
    ], [])
    assert zeilen[0].text == "Rechts abbiegen auf Pragstraße (B 10)"
    assert zeilen[1].text == "Leicht rechts auf A 8"
    assert zeilen[1].detail == "Richtung München"


def test_kreisverkehr_zeigt_gegen_den_uhrzeigersinn():
    # Rechtsverkehr: ↻ wäre die falsche Fahrtrichtung.
    assert roadbook.symbol(6) == "↺"
    assert roadbook.symbol(12345) == "•"


@pytest.mark.parametrize(("meter", "text"), [
    (0, ""), (4, "10 m"), (847, "850 m"), (1000, "1,0 km"), (18_049, "18,0 km"),
])
def test_entfernungen_wie_auf_dem_tacho(meter, text):
    assert roadbook.fmt_distance(meter) == text


# ── Karte ────────────────────────────────────────────────────────────────────


def test_ausschnitt_enthaelt_alle_punkte_und_bleibt_unter_der_kacheldecke():
    punkte = [(9.18, 48.78), (9.99, 48.40), (9.55, 48.62)]
    ansicht = static_map.fit_view(punkte, 1600, 1050)
    for lon, lat in punkte:
        x, y = ansicht.project(lon, lat)
        assert 0 < x < 1600 and 0 < y < 1050
    assert 0 < len(ansicht.tiles()) <= static_map.MAX_TILES
    # Kürzere Strecke → größere Zoomstufe.
    nah = static_map.fit_view([(9.18, 48.78), (9.19, 48.79)], 1600, 1050)
    assert nah.zoom > ansicht.zoom


async def test_karte_entsteht_auch_ohne_kachelserver():
    async def nichts(z, x, y):
        return None

    marker = roadbook.map_markers((48.78, 9.18), (48.40, 9.99), [])
    jpeg = await static_map.render_route_map([[9.18, 48.78], [9.99, 48.40]], marker, 400, 260, fetch=nichts)
    bild = Image.open(BytesIO(jpeg))
    assert bild.format == "JPEG" and bild.size == (400, 260)


async def test_kacheln_landen_im_bild():
    kachel = BytesIO()
    Image.new("RGB", (256, 256), (200, 10, 10)).save(kachel, format="PNG")
    abgerufen = []

    async def rot(z, x, y):
        abgerufen.append((z, x, y))
        return kachel.getvalue()

    jpeg = await static_map.render_route_map([[9.18, 48.78], [9.99, 48.40]], [], 400, 260, fetch=rot)
    ecke = Image.open(BytesIO(jpeg)).convert("RGB").getpixel((200, 5))
    assert ecke[0] > 150 and ecke[1] < 80
    assert abgerufen and all(0 <= y < 2 ** z for z, _, y in abgerufen)


async def test_ohne_kachel_url_wird_nichts_abgerufen(monkeypatch):
    def verboten(*a, **k):
        raise AssertionError("kein Netzzugriff erwartet")

    monkeypatch.setattr(settings, "roadbook_tile_url", "")
    monkeypatch.setattr(httpx, "AsyncClient", verboten)
    jpeg = await static_map.render_route_map([[9.18, 48.78], [9.99, 48.40]], [], 400, 260)
    assert jpeg[:2] == b"\xff\xd8"


def test_marker_tragen_dieselbe_nummer_wie_die_tabelle():
    halt, dlp = _wp("Halt", "technical_stop"), _wp("DLP", "checkpoint")
    marker = roadbook.map_markers((48.0, 9.0), (49.0, 10.0), [(halt, (48.3, 9.3)), (dlp, (48.6, 9.6))])
    assert [(m.label, m.lat, m.lon) for m in marker] == [
        ("1", 48.3, 9.3), ("2", 48.6, 9.6), ("S", 48.0, 9.0), ("Z", 49.0, 10.0),
    ]
    assert marker[0].color == static_map.STOP_COLOR
    assert marker[1].color == static_map.WAYPOINT_COLOR


# ── PDF und Endpunkt ─────────────────────────────────────────────────────────


def _konvoi():
    return SimpleNamespace(name="Kontingent BW 3", organization="KatS Musterstadt", start_time=None,
                           waypoints=[], start_point=None, end_point=None)


def test_pdf_mit_langer_liste_bricht_auf_folgeseiten_um():
    anweisungen = [{"sign": 2, "text": f"Rechts abbiegen {i}", "distance_m": 500.0} for i in range(120)]
    route = SimpleNamespace(distance_m=60_000, duration_s=5400, instructions=anweisungen)
    pdf = roadbook.generate_roadbook(_konvoi(), route, [], None)
    assert pdf.startswith(b"%PDF-")
    seiten = len(re.findall(rb"/Type /Page(?!s)", pdf))
    assert seiten >= 3


def test_pdf_ohne_anweisungen_entsteht_trotzdem():
    route = SimpleNamespace(distance_m=None, duration_s=None, instructions=None)
    assert roadbook.generate_roadbook(_konvoi(), route, [], None).startswith(b"%PDF-")


class _Ergebnis:
    def __init__(self, wert):
        self._wert = wert

    def scalar_one_or_none(self):
        return self._wert


class _Db:
    def __init__(self, route):
        self.route = route

    async def execute(self, *a, **k):
        return _Ergebnis(self.route)


async def test_endpunkt_liefert_pdf_auch_wenn_die_karte_scheitert(monkeypatch):
    from app.api.routes import routing as routen

    async def konvoi(*a, **k):
        return _konvoi()

    async def kaputt(*a, **k):
        raise RuntimeError("Kachelserver weg")

    route = SimpleNamespace(
        geometry=from_shape(LineString([(9.18, 48.78), (9.99, 48.40)]), srid=4326),
        distance_m=80_000, duration_s=4000,
        instructions=[{"sign": 4, "text": "Ziel erreicht!", "distance_m": 0}],
    )
    monkeypatch.setattr(routen, "_load_convoy", konvoi)
    monkeypatch.setattr(routen.static_map_svc, "render_route_map", kaputt)

    antwort = await routen.export_roadbook(uuid.uuid4(), db=_Db(route), current_user=None)
    assert antwort.media_type == "application/pdf"
    assert antwort.body.startswith(b"%PDF-")
    assert 'filename="Roadbook_Kontingent_BW_3.pdf"' in antwort.headers["content-disposition"]


async def test_endpunkt_ohne_route_meldet_404(monkeypatch):
    from app.api.routes import routing as routen

    async def konvoi(*a, **k):
        return _konvoi()

    monkeypatch.setattr(routen, "_load_convoy", konvoi)
    with pytest.raises(HTTPException) as fehler:
        await routen.export_roadbook(uuid.uuid4(), db=_Db(None), current_user=None)
    assert fehler.value.status_code == 404
