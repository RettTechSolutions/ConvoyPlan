import uuid
import pytest

from types import SimpleNamespace
from shapely.geometry import LineString


def test_kanalwechsel_entry_schema():
    from app.schemas.route import KanalwechselEntry
    entry = KanalwechselEntry(
        km=34.2, lat=47.856, lon=12.103,
        leitstelle_id=str(uuid.uuid4()),
        leitstelle_name="ILS Rosenheim",
        anrufgruppe="438",
        typ="abmelden",
    )
    assert entry.km == 34.2
    assert entry.leitstelle_name == "ILS Rosenheim"
    assert entry.typ == "abmelden"


def test_kanalwechsel_entry_accepts_convoy_anmeldung():
    from app.schemas.route import KanalwechselEntry
    entry = KanalwechselEntry(
        km=0.0, lat=48.0, lon=11.0,
        leitstelle_id=str(uuid.uuid4()),
        leitstelle_name="ILS München",
        anrufgruppe="25",
        typ="convoy_anmeldung",
    )
    assert entry.typ == "convoy_anmeldung"


def test_kanalwechsel_entry_typ_defaults_to_anmelden():
    """Vor Einführung des typ-Feldes gespeicherte Routen müssen weiterhin
    validieren — der Default ist "anmelden"."""
    from app.schemas.route import KanalwechselEntry
    entry = KanalwechselEntry(
        km=10.0, lat=48.0, lon=11.0,
        leitstelle_id=str(uuid.uuid4()),
        leitstelle_name="ILS München",
        anrufgruppe="25",
    )
    assert entry.typ == "anmelden"


def test_route_response_includes_kanalwechsel():
    from app.schemas.route import RouteResponse, KanalwechselEntry
    r = RouteResponse(
        id=uuid.uuid4(),
        convoy_id=uuid.uuid4(),
        distance_m=50000,
        duration_s=3600,
        routing_params=None,
        geojson=None,
        kanalwechsel=[
            KanalwechselEntry(
                km=25.0, lat=48.0, lon=11.0,
                leitstelle_id=str(uuid.uuid4()),
                leitstelle_name="ILS München",
                anrufgruppe="468",
            )
        ],
    )
    assert len(r.kanalwechsel) == 1
    assert r.kanalwechsel[0].anrufgruppe == "468"


class FakeResult:
    def __init__(self, rows=None):
        self._rows = rows or []

    def all(self):
        return self._rows


class FakeDB:
    def __init__(self, rows):
        self._rows = rows

    async def execute(self, *_a, **_k):
        return FakeResult(rows=self._rows)


def _row(name, anrufgruppe, geojson):
    return SimpleNamespace(
        id=uuid.uuid4(), name=name, anrufgruppe=anrufgruppe, covered_geojson=geojson
    )


# Gerade Route von lon 11.0 → 12.0 bei lat 48.0, 100 km lang:
# km entlang der Route == (lon − 11.0) · 100.
LINE = LineString([(11.0, 48.0), (12.0, 48.0)])


@pytest.mark.asyncio
async def test_compute_kanalwechsel_simple_transition():
    """Sauberer Gebietswechsel: Convoy-Anmeldung am Start, dann erst
    Abmelden bei der alten, danach Anmelden bei der neuen Leitstelle —
    kein Abmelden am Ziel."""
    from app.api.routes.routing import _compute_kanalwechsel

    rows = [
        _row("ILS München", "25", '{"type":"LineString","coordinates":[[11.0,48.0],[11.4,48.0]]}'),
        _row("ILS FFB", "20", '{"type":"LineString","coordinates":[[11.4,48.0],[12.0,48.0]]}'),
    ]
    entries = await _compute_kanalwechsel(FakeDB(rows), LINE, distance_m=100_000)

    assert [(e["km"], e["typ"], e["leitstelle_name"]) for e in entries] == [
        (0.0, "convoy_anmeldung", "ILS München"),
        (40.0, "abmelden", "ILS München"),
        (40.0, "anmelden", "ILS FFB"),
    ]
    assert entries[1]["lat"] == 48.0
    assert entries[1]["lon"] == 11.4


@pytest.mark.asyncio
async def test_compute_kanalwechsel_abmelden_vor_anmelden_bei_ueberlappung():
    """Pendelt die Route an einer Gebietsgrenze hin und her (überlappende
    Abdeckung), liegt die Übergabe in der Mitte des gemeinsamen Korridors —
    erst Abmelden bei der alten, dann Anmelden bei der neuen Leitstelle."""
    from app.api.routes.routing import _compute_kanalwechsel

    rows = [
        # München: km 0–13,6 und 16,5–19,0 (Lücke 2,9 km < KW_MERGE_GAP_KM)
        _row("ILS München", "25",
             '{"type":"MultiLineString","coordinates":'
             '[[[11.0,48.0],[11.136,48.0]],[[11.165,48.0],[11.19,48.0]]]}'),
        # FFB: km 13,6–16,5 und 19,0–100
        _row("ILS FFB", "20",
             '{"type":"MultiLineString","coordinates":'
             '[[[11.136,48.0],[11.165,48.0]],[[11.19,48.0],[12.0,48.0]]]}'),
    ]
    entries = await _compute_kanalwechsel(FakeDB(rows), LINE, distance_m=100_000)

    # Überlappung München/FFB: km 13,6–19,0 → Übergabe bei km 16,3
    assert [(e["km"], e["typ"], e["leitstelle_name"]) for e in entries] == [
        (0.0, "convoy_anmeldung", "ILS München"),
        (16.3, "abmelden", "ILS München"),
        (16.3, "anmelden", "ILS FFB"),
    ]


@pytest.mark.asyncio
async def test_compute_kanalwechsel_luecke_ohne_abdeckung():
    """Liegt zwischen zwei Gebieten ein unabgedeckter Abschnitt, wird am
    Gebietsende abgemeldet und erst am nächsten Gebietsanfang angemeldet."""
    from app.api.routes.routing import _compute_kanalwechsel

    rows = [
        _row("ILS A", "10", '{"type":"LineString","coordinates":[[11.0,48.0],[11.3,48.0]]}'),
        _row("ILS B", "20", '{"type":"LineString","coordinates":[[11.6,48.0],[12.0,48.0]]}'),
    ]
    entries = await _compute_kanalwechsel(FakeDB(rows), LINE, distance_m=100_000)

    assert [(e["km"], e["typ"], e["leitstelle_name"]) for e in entries] == [
        (0.0, "convoy_anmeldung", "ILS A"),
        (30.0, "abmelden", "ILS A"),
        (60.0, "anmelden", "ILS B"),
    ]


@pytest.mark.asyncio
async def test_compute_kanalwechsel_enklave():
    """Durchquert die Route eine Enklave, wird dort an- und wieder
    zurückgewechselt — die Kette bleibt sequenziell."""
    from app.api.routes.routing import _compute_kanalwechsel

    rows = [
        _row("ILS Umland", "10", '{"type":"LineString","coordinates":[[11.0,48.0],[12.0,48.0]]}'),
        _row("ILS Enklave", "20", '{"type":"LineString","coordinates":[[11.42,48.0],[11.44,48.0]]}'),
    ]
    entries = await _compute_kanalwechsel(FakeDB(rows), LINE, distance_m=100_000)

    assert [(e["km"], e["typ"], e["leitstelle_name"]) for e in entries] == [
        (0.0, "convoy_anmeldung", "ILS Umland"),
        (43.0, "abmelden", "ILS Umland"),
        (43.0, "anmelden", "ILS Enklave"),
        (44.0, "abmelden", "ILS Enklave"),
        (44.0, "anmelden", "ILS Umland"),
    ]


@pytest.mark.asyncio
async def test_compute_kanalwechsel_drops_noise_presence():
    """Mini-Abschnitte mitten auf der Route (< KW_MIN_PRESENCE_KM) sind
    Geometrie-Rauschen und erzeugen keine An-/Abmeldepunkte."""
    from app.api.routes.routing import _compute_kanalwechsel

    rows = [
        _row("ILS München", "25", '{"type":"LineString","coordinates":[[11.0,48.0],[12.0,48.0]]}'),
        # nur 0,3 km im Gebiet, 50 km vom Rest entfernt
        _row("ILS Streif", "99", '{"type":"LineString","coordinates":[[11.5,48.0],[11.503,48.0]]}'),
    ]
    entries = await _compute_kanalwechsel(FakeDB(rows), LINE, distance_m=100_000)

    assert [(e["km"], e["typ"], e["leitstelle_name"]) for e in entries] == [
        (0.0, "convoy_anmeldung", "ILS München"),
    ]


@pytest.mark.asyncio
async def test_compute_kanalwechsel_skips_empty_geometries():
    """LINESTRING EMPTY / leere MultiLineString-Einträge von PostGIS dürfen
    keinen ValueError beim Entpacken auslösen (Produktions-500 bei
    calculate-route). Z-Koordinaten werden ignoriert."""
    from app.api.routes.routing import _compute_kanalwechsel

    rows = [
        _row("ILS Leer", "400", '{"type":"LineString","coordinates":[]}'),
        _row("ILS Punkt", "401", '{"type":"GeometryCollection","geometries":[]}'),
        _row("ILS Gültig", "438",
             '{"type":"MultiLineString","coordinates":'
             '[[], [[11.5,48.0,0],[12.0,48.0,0]]]}'),
    ]
    entries = await _compute_kanalwechsel(FakeDB(rows), LINE, distance_m=100_000)

    assert [(e["km"], e["typ"], e["leitstelle_name"]) for e in entries] == [
        (50.0, "convoy_anmeldung", "ILS Gültig"),
    ]
    assert entries[0]["lat"] == 48.0
    assert entries[0]["lon"] == 11.5
