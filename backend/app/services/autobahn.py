"""Verkehrsdaten der Autobahn GmbH (autobahn.api.bund.dev).

Zweite Datenquelle neben Overpass/OpenStreetMap. Die offizielle Autobahn-API
liefert **live** Baustellen, Verkehrswarnungen (Unfälle, Hindernisse …) und
Vollsperrungen für alle Bundesautobahnen — genau die kurzfristigen Hindernisse,
die in OSM oft fehlen.

Die API ist pro Autobahn organisiert (``/{roadId}/services/{service}``), daher
wird der komplette bundesweite Datensatz einmalig eingesammelt, für einige
Minuten gecacht und anschließend lokal auf den Routenkorridor bzw. einen Radius
gefiltert. So wird die API nicht bei jeder Sperrungsabfrage neu befragt.
"""
import asyncio
import time
from datetime import datetime, timezone

import httpx

from app.services.overpass import _haversine_m, _sample_route

AUTOBAHN_BASE = "https://verkehr.autobahn.de/o/autobahn"
_HEADERS = {"Accept": "application/json", "User-Agent": "ConvoyPlan/1.0"}

# Für die Konvoiplanung relevante Dienste. roadworks + closure decken
# Baustellen/Sperrungen ab, warning ergänzt Unfälle und Hindernisse.
SERVICES = ("roadworks", "warning", "closure")

# Der bundesweite Datensatz ändert sich nicht sekündlich — 5 min Cache genügt
# und hält die Last auf der öffentlichen API gering.
_CACHE_TTL_S = 300
# Nebenläufige Requests gegen die API begrenzen (106 Autobahnen × 3 Dienste).
_MAX_CONCURRENCY = 16

_cache: dict = {"features": None, "fetched_at": 0.0}
_cache_lock = asyncio.Lock()
_last_check: dict = {"status": "unknown", "latency_ms": None, "checked_at": None}


def last_check() -> dict:
    return dict(_last_check)


# ── HTTP ──────────────────────────────────────────────────────────────


async def _list_roads(client: httpx.AsyncClient) -> list[str]:
    resp = await client.get(f"{AUTOBAHN_BASE}/")
    resp.raise_for_status()
    return resp.json().get("roads", []) or []


async def _fetch_service(
    client: httpx.AsyncClient, road: str, service: str, sem: asyncio.Semaphore
) -> list[dict]:
    """Rohe Items eines Dienstes für eine Autobahn holen (Fehler → leere Liste)."""
    async with sem:
        try:
            resp = await client.get(f"{AUTOBAHN_BASE}/{road.strip()}/services/{service}")
            resp.raise_for_status()
            data = resp.json()
        except Exception:
            return []
    # Antwort-Key entspricht dem Dienstnamen ({"roadworks": [...]}); zur
    # Sicherheit auf die erste Liste im Objekt zurückfallen.
    items = data.get(service)
    if not isinstance(items, list):
        items = next((v for v in data.values() if isinstance(v, list)), [])
    return [dict(it, _service=service) for it in items if isinstance(it, dict)]


# ── Item → GeoJSON ────────────────────────────────────────────────────


def _item_to_feature(item: dict) -> dict | None:
    """Ein Autobahn-Item in ein GeoJSON-Feature übersetzen.

    Nutzt bevorzugt die mitgelieferte ``geometry`` (Point/LineString), sonst
    fällt es auf ``coordinate``/``point`` zurück.
    """
    geom = item.get("geometry")
    if isinstance(geom, dict) and geom.get("type") and geom.get("coordinates"):
        geometry = {"type": geom["type"], "coordinates": geom["coordinates"]}
    else:
        lat, lon = _point_coord(item)
        if lat is None or lon is None:
            return None
        geometry = {"type": "Point", "coordinates": [lon, lat]}

    service = item.get("_service", "")
    props = {
        "source": "autobahn",
        "service": service,
        "title": item.get("title"),
        "subtitle": item.get("subtitle"),
        "description": item.get("description"),
        "display_type": item.get("display_type"),
        "isBlocked": item.get("isBlocked"),
        "future": item.get("future"),
        "identifier": item.get("identifier"),
        "icon": item.get("icon"),
    }
    return {"type": "Feature", "geometry": geometry, "properties": props}


def _point_coord(item: dict) -> tuple[float | None, float | None]:
    coord = item.get("coordinate")
    if isinstance(coord, dict):
        try:
            return float(coord["lat"]), float(coord["long"])
        except (KeyError, TypeError, ValueError):
            pass
    point = item.get("point")
    if isinstance(point, str) and "," in point:
        try:
            lat_s, lon_s = point.split(",", 1)
            return float(lat_s), float(lon_s)
        except ValueError:
            pass
    return None, None


def _feature_points(feature: dict, max_pts: int = 12) -> list[tuple[float, float]]:
    """Repräsentative (lat, lon)-Stützpunkte eines Features für die Distanzprüfung."""
    geom = feature.get("geometry", {})
    coords = geom.get("coordinates")
    if not coords:
        return []
    if geom.get("type") == "Point":
        return [(coords[1], coords[0])]
    pts = [(c[1], c[0]) for c in coords if isinstance(c, (list, tuple)) and len(c) >= 2]
    if len(pts) <= max_pts:
        return pts
    step = len(pts) / max_pts
    sampled = [pts[int(i * step)] for i in range(max_pts)]
    sampled[-1] = pts[-1]
    return sampled


# ── Cache ─────────────────────────────────────────────────────────────


async def _fetch_all_features() -> list[dict]:
    """Kompletten bundesweiten Datensatz einsammeln und zu Features wandeln."""
    sem = asyncio.Semaphore(_MAX_CONCURRENCY)
    async with httpx.AsyncClient(timeout=20.0, headers=_HEADERS) as client:
        roads = await _list_roads(client)
        tasks = [
            _fetch_service(client, road, svc, sem)
            for road in roads
            for svc in SERVICES
        ]
        results = await asyncio.gather(*tasks)

    features: list[dict] = []
    seen: set[str] = set()
    for items in results:
        for item in items:
            feature = _item_to_feature(item)
            if feature is None:
                continue
            # Dieselbe Meldung taucht an Autobahnkreuzen unter mehreren roadIds
            # auf — über den identifier deduplizieren.
            ident = feature["properties"].get("identifier")
            key = f"{feature['properties']['service']}:{ident}" if ident else None
            if key is not None:
                if key in seen:
                    continue
                seen.add(key)
            features.append(feature)
    return features


async def _get_national_features() -> list[dict]:
    """Gecachte bundesweite Features; aktualisiert nach Ablauf der TTL.

    Schlägt der Abruf fehl, bleibt ein evtl. vorhandener (veralteter) Cache
    erhalten, damit ein kurzer API-Ausfall die Anzeige nicht leert.
    """
    global _last_check
    now = time.monotonic()
    if _cache["features"] is not None and now - _cache["fetched_at"] < _CACHE_TTL_S:
        return _cache["features"]

    async with _cache_lock:
        now = time.monotonic()
        if _cache["features"] is not None and now - _cache["fetched_at"] < _CACHE_TTL_S:
            return _cache["features"]

        t0 = time.monotonic()
        try:
            features = await _fetch_all_features()
            _cache["features"] = features
            _cache["fetched_at"] = time.monotonic()
            _last_check = {
                "status": "ok",
                "latency_ms": round((time.monotonic() - t0) * 1000),
                "checked_at": datetime.now(timezone.utc).isoformat(),
            }
            return features
        except Exception:
            _last_check = {
                "status": "error",
                "latency_ms": None,
                "checked_at": datetime.now(timezone.utc).isoformat(),
            }
            if _cache["features"] is not None:
                return _cache["features"]
            raise


# ── Öffentliche Filter-API ────────────────────────────────────────────


async def features_around(lat: float, lon: float, radius_m: int) -> list[dict]:
    """Autobahn-Features innerhalb ``radius_m`` um (lat, lon)."""
    features = await _get_national_features()
    out = []
    for f in features:
        for p_lat, p_lon in _feature_points(f):
            if _haversine_m(lat, lon, p_lat, p_lon) <= radius_m:
                out.append(f)
                break
    return out


async def features_along_route(
    coordinates: list[tuple[float, float]], corridor_m: int = 2000
) -> list[dict]:
    """Autobahn-Features im Korridor entlang einer Route ([(lon, lat), ...])."""
    if len(coordinates) < 2:
        return []
    route = _sample_route([(lat, lon) for lon, lat in coordinates])

    # Bounding-Box-Vorfilter (grob, in Grad) — spart teure Haversine-Aufrufe
    # für die große Mehrzahl bundesweiter Features, die weit weg liegen.
    lats = [p[0] for p in route]
    lons = [p[1] for p in route]
    deg_pad = corridor_m / 111_000 + 0.02
    min_lat, max_lat = min(lats) - deg_pad, max(lats) + deg_pad
    min_lon, max_lon = min(lons) - deg_pad, max(lons) + deg_pad

    features = await _get_national_features()
    out = []
    for f in features:
        pts = _feature_points(f)
        if not any(min_lat <= p[0] <= max_lat and min_lon <= p[1] <= max_lon for p in pts):
            continue
        if _near_route(pts, route, corridor_m):
            out.append(f)
    return out


def _near_route(
    points: list[tuple[float, float]],
    route: list[tuple[float, float]],
    corridor_m: int,
) -> bool:
    for p_lat, p_lon in points:
        for r_lat, r_lon in route:
            if _haversine_m(p_lat, p_lon, r_lat, r_lon) <= corridor_m:
                return True
    return False


async def probe() -> dict:
    """Leichter Erreichbarkeitscheck (nur die Autobahn-Liste), 60 s gecacht.

    Bewusst *kein* Voll-Abruf des bundesweiten Datensatzes — die Status-Anzeige
    wird häufig gepollt. Ein erfolgreicher Voll-Abruf über :func:`_get_national_features`
    aktualisiert ``_last_check`` ohnehin mit der echten Latenz.
    """
    global _last_check
    if _last_check["checked_at"] is not None:
        last = datetime.fromisoformat(_last_check["checked_at"])
        if (datetime.now(timezone.utc) - last).total_seconds() < 60:
            return dict(_last_check)

    t0 = time.monotonic()
    try:
        async with httpx.AsyncClient(timeout=8.0, headers=_HEADERS) as client:
            await _list_roads(client)
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
