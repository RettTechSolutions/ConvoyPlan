"""Offene, lizenzfreie Verkehrsdaten-Feeds (Baustellen/Sperrungen).

Dritte Datenquelle neben Overpass und der Autobahn-API. Länder und Städte
veröffentlichen Baustellen/Sperrungen als **offenes GeoJSON** (ohne API-Key,
ohne Registrierung) — allerdings jeweils in **eigenen Schemata**. Deshalb gibt
es pro Format einen kleinen Adapter:

- ``mobidata_bw`` — MobiData BW / CIFS-Stil (Baden-Württemberg, bis Kreisstraße)
- ``berlin_viz`` — Berliner Verkehrsinformationszentrale (VIZ)

Weitere Regionen lassen sich über ``settings.opendata_traffic_feeds`` ergänzen:
je Eintrag ``format|url`` (oder nur ``url`` → Standard ``mobidata_bw``). Jeder
Feed wird gebündelt geholt, kurz gecacht, auf aktuell gültige Ereignisse und den
Routenkorridor bzw. Radius gefiltert.

Für eine wirklich bundesweite Abdeckung abseits der Autobahn ist die mobilithek
(DATEX II) die offizielle Aggregation — der maschinelle Zugang erfordert dort
allerdings Registrierung und Client-Zertifikat.
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

# Begriffe, die auf eine echte Sperrung (statt „nur" Baustelle) hindeuten.
_CLOSURE_HINTS = ("CLOSURE", "CLOSED", "BLOCK", "SPERR", "VOLLSPERR")


def last_check() -> dict:
    return dict(_last_check)


def _feeds() -> list[tuple[str, str]]:
    """Konfigurierte Feeds als ``(format, url)``-Paare."""
    if not settings.opendata_traffic_enabled:
        return []
    feeds = []
    for entry in settings.opendata_traffic_feeds.split(","):
        entry = entry.strip()
        if not entry:
            continue
        if "|" in entry:
            fmt, url = entry.split("|", 1)
            feeds.append((fmt.strip() or "mobidata_bw", url.strip()))
        else:
            feeds.append(("mobidata_bw", entry))
    return feeds


def _parse_time(value) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        dt = datetime.fromisoformat(value)
    except ValueError:
        return None
    # Naive Zeiten (z. B. Berlin „2026-08-17T17:00") als UTC behandeln, damit der
    # Vergleich mit dem aktuellen Zeitpunkt nicht an tz-naiv/aware scheitert.
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _is_active(props: dict, now: datetime) -> bool:
    """Nur aktuell gültige/künftige Ereignisse behalten (abgelaufene ausblenden)."""
    end = _parse_time(props.get("endtime"))
    if end is not None and end < now:
        return False
    return True


def _is_closure(*values: object) -> bool:
    joined = " ".join(str(v) for v in values if v).upper()
    if "KEINE SPERR" in joined:  # z. B. Berlin: „keine Sperrung"
        return False
    return any(h in joined for h in _CLOSURE_HINTS)


def _flatten_geoms(geom: dict) -> list[dict]:
    """Beliebige Geometrie in eine Liste aus Point/LineString zerlegen.

    MapLibre rendert GeometryCollection/Polygon nicht als Linienebene sauber —
    daher zu Point/LineString normalisieren (Polygon → äußerer Ring als Linie).
    """
    t = geom.get("type")
    c = geom.get("coordinates")
    if t in ("Point", "LineString"):
        return [geom] if c else []
    if t == "MultiPoint":
        return [{"type": "Point", "coordinates": p} for p in c or []]
    if t == "MultiLineString":
        return [{"type": "LineString", "coordinates": ln} for ln in c or [] if ln]
    if t == "Polygon":
        return [{"type": "LineString", "coordinates": c[0]}] if c and c[0] else []
    if t == "MultiPolygon":
        return [{"type": "LineString", "coordinates": poly[0]} for poly in c or [] if poly and poly[0]]
    if t == "GeometryCollection":
        out: list[dict] = []
        for g in geom.get("geometries", []):
            if isinstance(g, dict):
                out.extend(_flatten_geoms(g))
        return out
    return []


def _build(geom: dict, props: dict) -> list[dict]:
    """Aus normalisierten Properties + Geometrie 0..n GeoJSON-Features bauen."""
    return [
        {"type": "Feature", "geometry": g, "properties": dict(props)}
        for g in _flatten_geoms(geom)
    ]


# ── Format-Adapter ───────────────────────────────────────────────────
# Jeder Adapter bekommt ein rohes Feature + Provider-Name und liefert 0..n
# normalisierte Features mit gemeinsamer Property-Form.


def _adapt_mobidata_bw(raw: dict, provider: str) -> list[dict]:
    geom = raw.get("geometry")
    if not isinstance(geom, dict):
        return []
    p = raw.get("properties") or {}
    street = p.get("street")
    description = p.get("description")
    closure = _is_closure(p.get("type"), p.get("subtype"))
    props = {
        "source": "opendata",
        "provider": p.get("reference") or provider,
        "service": "closure" if closure else "roadworks",
        "title": street or description or "Baustelle/Sperrung",
        "subtitle": description if street and description and description != street else None,
        "description": description,
        "isBlocked": "true" if closure else "false",
        "street": street,
        "starttime": p.get("starttime"),
        "endtime": p.get("endtime"),
        "identifier": p.get("id"),
    }
    return _build(geom, props)


def _adapt_berlin_viz(raw: dict, provider: str) -> list[dict]:
    geom = raw.get("geometry")
    if not isinstance(geom, dict):
        return []
    p = raw.get("properties") or {}
    street = p.get("street")
    content = p.get("content")
    validity = p.get("validity") if isinstance(p.get("validity"), dict) else {}
    closure = _is_closure(p.get("severity"), p.get("subtype"))
    props = {
        "source": "opendata",
        "provider": provider,
        "service": "closure" if closure else "roadworks",
        "title": street or content or "Baustelle/Sperrung",
        "subtitle": content if street and content else (p.get("section") or None),
        "description": content,
        "isBlocked": "true" if closure else "false",
        "street": street,
        "starttime": validity.get("from"),
        "endtime": validity.get("to"),
        "identifier": p.get("id"),
    }
    return _build(geom, props)


_ADAPTERS = {
    "mobidata_bw": ("MobiData BW", _adapt_mobidata_bw),
    "berlin_viz": ("Berlin VIZ", _adapt_berlin_viz),
}


# ── Abruf & Cache ────────────────────────────────────────────────────


async def _fetch_feed(client: httpx.AsyncClient, fmt: str, url: str) -> list[dict]:
    """Einen Feed holen, per Adapter normalisieren, Abgelaufenes ausfiltern."""
    adapter = _ADAPTERS.get(fmt)
    if adapter is None:
        return []
    provider_name, adapt = adapter
    try:
        resp = await client.get(url)
        resp.raise_for_status()
        data = resp.json()
    except Exception:
        return []
    if not isinstance(data, dict) or data.get("type") != "FeatureCollection":
        return []

    now = datetime.now(timezone.utc)
    out = []
    for raw in data.get("features", []):
        if not isinstance(raw, dict):
            continue
        for feature in adapt(raw, provider_name):
            if _is_active(feature["properties"], now):
                out.append(feature)
    return out


async def _fetch_all_features() -> list[dict]:
    feeds = _feeds()
    if not feeds:
        return []
    async with httpx.AsyncClient(timeout=20.0, headers=_HEADERS) as client:
        results = await asyncio.gather(*[_fetch_feed(client, fmt, url) for fmt, url in feeds])
    features: list[dict] = []
    for res in results:
        features.extend(res)
    return features


async def _get_features() -> list[dict]:
    """Gecachte offene Verkehrsdaten; behält bei Fehler den alten Cache."""
    global _last_check
    if not _feeds():
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
