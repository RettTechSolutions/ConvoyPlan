"""Offene, lizenzfreie Verkehrsdaten-Feeds (Baustellen/Sperrungen).

Dritte Datenquelle neben Overpass und der Autobahn-API. Verschiedene Länder und
Regionen veröffentlichen Baustellen/Sperrungen als **offenes GeoJSON** (ohne
API-Key, ohne Registrierung) im MobiData-BW-/CIFS-Stil — z. B.
``https://api.mobidata-bw.de/datasets/traffic/roadworks/roadworks_geojson.json``
(Baden-Württemberg, bis hinunter zu Kreisstraßen).

Die Feed-Liste ist konfigurierbar (``settings.opendata_traffic_feeds``), damit
weitere Regionen ohne Code-Änderung ergänzt werden können. Jeder Feed wird
gebündelt geholt, kurz gecacht, auf aktuell gültige Ereignisse und den
Routenkorridor bzw. Radius gefiltert.
"""
import asyncio
import time
from datetime import datetime, timezone

import httpx

from app.config import settings
from app.services.autobahn import _feature_points, _near_route
from app.services.overpass import _haversine_m, _sample_route

_HEADERS = {"Accept": "application/json", "User-Agent": "ConvoyPlan/1.0"}

# Offene Feeds ändern sich nicht sekündlich — 5 min Cache.
_CACHE_TTL_S = 300

_cache: dict = {"features": None, "fetched_at": 0.0}
_cache_lock = asyncio.Lock()
_last_check: dict = {"status": "unknown", "latency_ms": None, "checked_at": None}

# Typen, die auf eine echte Sperrung (statt „nur" Baustelle) hindeuten.
_CLOSURE_HINTS = ("CLOSURE", "CLOSED", "BLOCK", "SPERR")


def last_check() -> dict:
    return dict(_last_check)


def _feed_urls() -> list[str]:
    if not settings.opendata_traffic_enabled:
        return []
    return [u.strip() for u in settings.opendata_traffic_feeds.split(",") if u.strip()]


def _parse_time(value) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _is_active(props: dict, now: datetime) -> bool:
    """Nur aktuell gültige/künftige Ereignisse behalten (abgelaufene ausblenden)."""
    end = _parse_time(props.get("endtime"))
    if end is not None and end < now:
        return False
    return True


def _to_feature(raw: dict, provider: str) -> dict | None:
    geom = raw.get("geometry")
    if not isinstance(geom, dict) or not geom.get("type") or not geom.get("coordinates"):
        return None
    props = raw.get("properties") or {}

    typ = str(props.get("type") or "").upper()
    subtype = str(props.get("subtype") or "").upper()
    is_closure = any(h in typ or h in subtype for h in _CLOSURE_HINTS)

    street = props.get("street")
    description = props.get("description")
    title = street or description or "Baustelle/Sperrung"
    subtitle = description if street and description and description != street else None

    return {
        "type": "Feature",
        "geometry": {"type": geom["type"], "coordinates": geom["coordinates"]},
        "properties": {
            "source": "opendata",
            "provider": props.get("reference") or provider,
            "service": "closure" if is_closure else "roadworks",
            "title": title,
            "subtitle": subtitle,
            "description": description,
            "isBlocked": "true" if is_closure else "false",
            "street": street,
            "starttime": props.get("starttime"),
            "endtime": props.get("endtime"),
            "identifier": props.get("id"),
        },
    }


async def _fetch_feed(client: httpx.AsyncClient, url: str) -> list[dict]:
    """Einen Feed holen und in unsere Feature-Form wandeln (Fehler → leer)."""
    try:
        resp = await client.get(url)
        resp.raise_for_status()
        data = resp.json()
    except Exception:
        return []
    if not isinstance(data, dict) or data.get("type") != "FeatureCollection":
        return []

    provider = url.split("/")[2] if "//" in url else url  # Host als Fallback-Name
    now = datetime.now(timezone.utc)
    out = []
    for raw in data.get("features", []):
        if not isinstance(raw, dict):
            continue
        if not _is_active(raw.get("properties") or {}, now):
            continue
        feature = _to_feature(raw, provider)
        if feature is not None:
            out.append(feature)
    return out


async def _fetch_all_features() -> list[dict]:
    urls = _feed_urls()
    if not urls:
        return []
    async with httpx.AsyncClient(timeout=20.0, headers=_HEADERS) as client:
        results = await asyncio.gather(*[_fetch_feed(client, u) for u in urls])
    features: list[dict] = []
    for res in results:
        features.extend(res)
    return features


async def _get_features() -> list[dict]:
    """Gecachte offene Verkehrsdaten; behält bei Fehler den alten Cache."""
    global _last_check
    if not _feed_urls():
        return []

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
            return []


async def features_around(lat: float, lon: float, radius_m: int) -> list[dict]:
    features = await _get_features()
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
    if len(coordinates) < 2:
        return []
    features = await _get_features()
    if not features:
        return []
    route = _sample_route([(lat, lon) for lon, lat in coordinates])

    lats = [p[0] for p in route]
    lons = [p[1] for p in route]
    deg_pad = corridor_m / 111_000 + 0.02
    min_lat, max_lat = min(lats) - deg_pad, max(lats) + deg_pad
    min_lon, max_lon = min(lons) - deg_pad, max(lons) + deg_pad

    out = []
    for f in features:
        pts = _feature_points(f)
        if not any(min_lat <= p[0] <= max_lat and min_lon <= p[1] <= max_lon for p in pts):
            continue
        if _near_route(pts, route, corridor_m):
            out.append(f)
    return out
