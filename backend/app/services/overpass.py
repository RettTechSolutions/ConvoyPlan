import asyncio
import httpx
import math
import time
from datetime import datetime, timezone

from app.config import settings

# In dieser Reihenfolge versucht (OVERPASS_URLS). overpass.kumi.systems und
# overpass.private.coffee standen hier als Ersatz und antworteten im Oktober
# 2026 nur noch mit 500 — ein toter Spiegel kostet bei jedem Ausfall des
# ersten Servers Zeit und bringt nichts.
OVERPASS_MIRRORS = [u.strip() for u in settings.overpass_urls.split(",") if u.strip()] or [
    "https://overpass-api.de/api/interpreter"
]
OVERPASS_URL = OVERPASS_MIRRORS[0]
_HEADERS = {"Accept": "*/*", "User-Agent": "ConvoyPlan/1.0"}

_last_check: dict = {"status": "unknown", "latency_ms": None, "checked_at": None}


def last_check() -> dict:
    return dict(_last_check)


async def probe() -> dict:
    """Lightweight reachability check, cached for 60 s to avoid hammering Overpass."""
    global _last_check
    if _last_check["checked_at"] is not None:
        last = datetime.fromisoformat(_last_check["checked_at"])
        if (datetime.now(timezone.utc) - last).total_seconds() < 60:
            return dict(_last_check)

    query = "[out:json][timeout:5];node(51.505,-0.09,51.51,-0.08);out 1;"
    t0 = time.monotonic()
    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            resp = await client.post(OVERPASS_URL, data={"data": query}, headers=_HEADERS)
            resp.raise_for_status()
        _last_check = {
            "status": "ok",
            "latency_ms": round((time.monotonic() - t0) * 1000),
            "checked_at": datetime.now(timezone.utc).isoformat(),
        }
    except Exception:
        _last_check = {
            "status": "error",
            "latency_ms": None,
            "checked_at": datetime.now(timezone.utc).isoformat(),
        }
    return dict(_last_check)


# overpass-api.de gibt je IP zwei Slots, und die ganze Instanz teilt sich eine.
# Nach einer Routenberechnung starten Sperrungen, Tankstellen und Brücken
# gleichzeitig — die dritte Abfrage bekam 429, die Spiegel dahinter waren
# ebenfalls nicht zu haben, und die Brückensuche meldete „nicht erreichbar".
# Deshalb höchstens zwei gleichzeitig, und ein besetzter Server wird nach einer
# Pause noch einmal gefragt, bevor es zum nächsten Spiegel geht.
_SLOTS = asyncio.Semaphore(2)
_BESETZT = {429, 503, 504}
_WARTEN_S = (5.0, 15.0)
_WARTEN_MAX_S = 30.0


class OverpassUnvollstaendig(Exception):
    """Overpass hat abgebrochen (Zeit, Speicher) und nur einen Teil geliefert."""


def _wartezeit(resp: httpx.Response, standard: float) -> float:
    try:
        return min(float(resp.headers.get("Retry-After", "")), _WARTEN_MAX_S)
    except ValueError:
        return standard


async def _post_overpass(query: str, timeout: float = 40.0) -> dict:
    """POST a query to Overpass, falling back through the mirror list.

    Eine Antwort mit ``remark: runtime error …`` ist ein Abbruch mit
    Teilergebnis (HTTP 200). Sie gilt als Fehler: eine halbe Brückenliste
    sähe aus wie „keine Brücke gefunden".
    """
    last_exc: Exception | None = None
    async with _SLOTS, httpx.AsyncClient(timeout=timeout) as client:
        for url in OVERPASS_MIRRORS:
            for versuch in range(len(_WARTEN_S) + 1):
                try:
                    resp = await client.post(url, data={"data": query}, headers=_HEADERS)
                    if resp.status_code in _BESETZT and versuch < len(_WARTEN_S):
                        await asyncio.sleep(_wartezeit(resp, _WARTEN_S[versuch]))
                        continue
                    resp.raise_for_status()
                    data = resp.json()
                    remark = str(data.get("remark") or "")
                    if remark.startswith("runtime error"):
                        raise OverpassUnvollstaendig(remark)
                    return data
                except Exception as exc:
                    last_exc = exc
                break
    raise last_exc  # type: ignore[misc]


def _closures_query(around_filter: str) -> str:
    # Focused only on actual construction/road-works — access=no is far too broad
    return f"""
[out:json][timeout:25];
(
  way["highway"="construction"]({around_filter});
  way["highway"]["construction"~"."]({around_filter});
  node["highway"="road_works"]({around_filter});
  node["highway"="construction"]({around_filter});
  node["hazard"="construction"]({around_filter});
);
out geom;
"""


def _build_query(lat: float, lon: float, radius_m: int = 15000) -> str:
    return _closures_query(f"around:{radius_m},{lat},{lon}")


def _haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat / 2) ** 2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon / 2) ** 2
    return 6_371_000 * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def _sample_route(coords: list[tuple[float, float]], max_points: int = 150) -> list[tuple[float, float]]:
    """Thin out a [(lat, lon), ...] polyline so the Overpass query stays small.

    Keeps the first and last point and drops intermediate points closer than a
    distance threshold derived from the route length and ``max_points``.
    """
    if len(coords) <= 2:
        return coords

    total_m = sum(
        _haversine_m(coords[i][0], coords[i][1], coords[i + 1][0], coords[i + 1][1])
        for i in range(len(coords) - 1)
    )
    min_gap_m = max(300.0, total_m / max_points)

    sampled = [coords[0]]
    acc = 0.0
    for i in range(1, len(coords) - 1):
        acc += _haversine_m(coords[i - 1][0], coords[i - 1][1], coords[i][0], coords[i][1])
        if acc >= min_gap_m:
            sampled.append(coords[i])
            acc = 0.0
    sampled.append(coords[-1])
    return sampled


def _to_geojson(elements: list) -> dict:
    features = []
    for el in elements:
        props = {k: v for k, v in el.get("tags", {}).items()}
        props["osm_type"] = el.get("type")
        props["osm_id"] = el.get("id")

        if el["type"] == "node":
            geometry = {"type": "Point", "coordinates": [el["lon"], el["lat"]]}
        elif el["type"] == "way" and "geometry" in el:
            coords = [[g["lon"], g["lat"]] for g in el["geometry"]]
            geometry = {"type": "LineString", "coordinates": coords}
        else:
            continue

        features.append({"type": "Feature", "geometry": geometry, "properties": props})

    return {"type": "FeatureCollection", "features": features}


async def find_fuel_stations(lat: float, lon: float, radius_m: int = 3000) -> list[dict]:
    """Return nearby fuel stations sorted by distance from (lat, lon)."""
    query = f"""
[out:json][timeout:15];
node["amenity"="fuel"](around:{radius_m},{lat},{lon});
out body;
"""
    data = await _post_overpass(query, timeout=20.0)

    import math

    def _dist(a_lat, a_lon):
        dlat = math.radians(a_lat - lat)
        dlon = math.radians(a_lon - lon)
        a = math.sin(dlat / 2) ** 2 + math.cos(math.radians(lat)) * math.cos(math.radians(a_lat)) * math.sin(dlon / 2) ** 2
        return 6_371_000 * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))

    stations = []
    for el in data.get("elements", []):
        if el.get("type") != "node":
            continue
        tags = el.get("tags", {})
        stations.append({
            "osm_id": el["id"],
            "lat": el["lat"],
            "lon": el["lon"],
            "name": tags.get("name") or tags.get("brand") or "Tankstelle",
            "brand": tags.get("brand"),
            "operator": tags.get("operator"),
            "opening_hours": tags.get("opening_hours"),
            "distance_m": round(_dist(el["lat"], el["lon"])),
        })

    stations.sort(key=lambda s: s["distance_m"])
    return stations[:10]


async def _run_closures_query(query: str) -> dict:
    global _last_check
    t0 = time.monotonic()
    try:
        data = await _post_overpass(query)
        _last_check = {
            "status": "ok",
            "latency_ms": round((time.monotonic() - t0) * 1000),
            "checked_at": datetime.now(timezone.utc).isoformat(),
        }
    except Exception:
        _last_check = {
            "status": "error",
            "latency_ms": None,
            "checked_at": datetime.now(timezone.utc).isoformat(),
        }
        raise

    return _to_geojson(data.get("elements", []))


async def get_closures(lat: float, lon: float, radius_m: int = 15000) -> dict:
    return await _run_closures_query(_build_query(lat, lon, radius_m))


async def get_closures_along_route(
    coordinates: list[tuple[float, float]], corridor_m: int = 2000
) -> dict:
    """Closures within ``corridor_m`` of a route given as [(lon, lat), ...] (GeoJSON order)."""
    latlon = [(lat, lon) for lon, lat in coordinates]
    sampled = _sample_route(latlon)
    coord_str = ",".join(f"{lat:.5f},{lon:.5f}" for lat, lon in sampled)
    return await _run_closures_query(_closures_query(f"around:{corridor_m},{coord_str}"))


async def bruecken_entlang(coordinates: list) -> list[dict]:
    """Brückenwege im schmalen Korridor um die Route ``[[lon, lat], …]``.

    Die Abfrage baut ``services/bruecken.py``; hier wird nur geholt, über
    dieselben Spiegel und mit demselben Statusvermerk wie die Sperrungen.
    """
    from app.services import bruecken as bruecken_svc

    global _last_check
    t0 = time.monotonic()
    try:
        data = await _post_overpass(bruecken_svc.abfrage(coordinates), timeout=100.0)
    except Exception:
        _last_check = {
            "status": "error",
            "latency_ms": None,
            "checked_at": datetime.now(timezone.utc).isoformat(),
        }
        raise
    _last_check = {
        "status": "ok",
        "latency_ms": round((time.monotonic() - t0) * 1000),
        "checked_at": datetime.now(timezone.utc).isoformat(),
    }
    return data.get("elements", [])
