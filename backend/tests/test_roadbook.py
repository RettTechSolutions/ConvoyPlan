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
        # Der Meter auf der Linie, für die Verfolgung (test_route_steps.py).
        "m": 0.0,
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


# ── Hinweise zu Höhe und Gewicht ─────────────────────────────────────────────
#
# Die Besatzung soll im Roadbook an der richtigen Stelle lesen, was knapp wird —
# und was nicht: eine Brücke mit 85 cm Spielraum ist eine Auskunft.


def _route_mit_hinweisen(**extra):
    return SimpleNamespace(
        distance_m=20_000, duration_s=1800,
        instructions=[
            {"sign": 0, "text": "Losfahren", "distance_m": 5000.0},
            {"sign": 2, "text": "Rechts abbiegen", "distance_m": 15000.0},
            {"sign": 4, "text": "Ziel", "distance_m": 0.0},
        ],
        durchfahrtshoehen=[
            {"km": 3.0, "m": 3000, "hoehe_m": 3.7, "spielraum_m": 0.05, "stufe": "eng"},
            {"km": 12.0, "m": 12000, "hoehe_m": 4.5, "spielraum_m": 0.85, "stufe": "frei"},
        ],
        gewichtsgrenzen=[
            {"km": 7.5, "m": 7500, "grenze_t": 7.5, "reserve_t": -18.5, "ausnahme": "destination",
             "stufe": "ueberschritten"},
        ],
        bruecken={"geprueft_at": "2026-10-09T10:00:00Z", "eintraege": [
            {"km": 9.0, "m": 9000, "art": "Eisenbahnbrücke", "name": "Ammertalbahn", "schnellstrasse": False},
            {"km": 15.0, "m": 15000, "art": "Straßenbrücke", "name": None, "schnellstrasse": True},
        ]},
        **extra,
    )


def test_hinweise_stehen_mit_zahl_spielraum_und_stufe_da():
    zeilen = roadbook.hinweis_rows(_route_mit_hinweisen())
    assert [(z.symbol, z.text, z.detail, z.stufe) for z in zeilen] == [
        ("↕", "Durchfahrtshöhe 3,7 m", "Spielraum +5 cm · ENG – vor Ort prüfen", "warnung"),
        ("⚖", "Gewichtsgrenze 7,5 t", "Reserve −18,5 t · Anlieger frei · ÜBER DER GRENZE", "warnung"),
        ("⚠", "Eisenbahnbrücke ohne Höhenangabe (Ammertalbahn)", "Höhe unbekannt – Beschilderung beachten", ""),
        # Frei steht auch da — „du kommst gut durch" ist eine Auskunft.
        ("↕", "Durchfahrtshöhe 4,5 m", "Spielraum +85 cm", ""),
    ]
    # Die Brücke auf der Schnellstraße wird gezählt, nicht gedruckt.
    assert all("Straßenbrücke" not in z.text for z in zeilen)


def test_achslastgrenze_heisst_so():
    route = SimpleNamespace(gewichtsgrenzen=[
        {"km": 2.0, "m": 2000, "grenze_t": 10.0, "reserve_t": 0.5, "ausnahme": None, "stufe": "knapp",
         "art": "achslast"},
    ])
    [z] = roadbook.hinweis_rows(route)
    assert (z.text, z.detail) == ("Achslastgrenze 10,0 t", "Reserve +0,5 t · knapp")


def test_ohne_ermittlung_keine_hinweise():
    route = SimpleNamespace(durchfahrtshoehen=None, gewichtsgrenzen=None, bruecken=None)
    assert roadbook.hinweis_rows(route) == []
    # Routen aus der Zeit vor den Spalten haben die Attribute gar nicht.
    assert roadbook.hinweis_rows(SimpleNamespace()) == []


def test_hinweise_stehen_auf_dem_stueck_auf_dem_sie_liegen():
    route = _route_mit_hinweisen()
    zeilen = roadbook.mit_hinweisen(roadbook.build_rows(route.instructions, []), roadbook.hinweis_rows(route))
    assert [(z.nr, z.text[:14]) for z in zeilen] == [
        (1, "Losfahren"),
        (0, "Durchfahrtshöh"),   # km 3 — auf dem Stück nach „Losfahren"
        (2, "Rechts abbiege"),   # km 5
        (0, "Gewichtsgrenze"),
        (0, "Eisenbahnbrück"),
        (0, "Durchfahrtshöh"),   # km 12
        (3, "Ziel erreicht"),    # km 20, bleibt die letzte Zeile
    ]


def test_ein_hinweis_hinter_dem_letzten_meter_rutscht_vor_das_ziel():
    zeilen = roadbook.mit_hinweisen(
        roadbook.build_rows([{"sign": 0, "text": "Los", "distance_m": 100.0}, {"sign": 4, "text": "Ziel"}], []),
        [roadbook.Row(0, "↕", "Durchfahrtshöhe 4,0 m", 0.2, 0.0, "hinweis")],
    )
    assert [z.kind for z in zeilen] == ["turn", "hinweis", "finish"]


def test_pdf_mit_hinweisen_entsteht():
    assert roadbook.generate_roadbook(_konvoi(), _route_mit_hinweisen(), [], None).startswith(b"%PDF-")


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
