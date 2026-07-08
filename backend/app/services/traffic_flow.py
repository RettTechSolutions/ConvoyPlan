"""Live-Verkehrslage (Fließgeschwindigkeit/Stau) von HERE und TomTom.

Vorbereitete, aber **standardmäßig inaktive** Anbindung: Solange keine
``here_traffic_api_key``/``tomtom_traffic_api_key`` gesetzt ist, liefert der
Dienst nichts und die Karten-Ebene bleibt leer. Sobald eine Installation ihren
eigenen API-Key hinterlegt, wird die Verkehrslage entlang der Route abgefragt
und als GeoJSON-LineStrings (mit ``jamFactor`` 0–10) zurückgegeben, die das
Frontend als Ampel-Ebene (grün→gelb→rot) über die OSM-Karte legt.

Beide Anbieter liefern JSON, das wir **selbst rendern** (keine fremden
Raster-Kacheln) — nötig, weil unsere Basiskarte OSM/MapLibre ist.
"""
import asyncio
import math

import httpx

from app.config import settings
from app.services.overpass import _haversine_m, _sample_route

_HEADERS = {"Accept": "application/json", "User-Agent": "ConvoyPlan/1.0"}

HERE_FLOW_URL = "https://data.traffic.hereapi.com/v7/flow"
TOMTOM_FLOW_URL = "https://api.tomtom.com/traffic/services/4/flowSegmentData/absolute/10/json"

# TomTom ist punktbasiert: Route abtasten und je Stützpunkt eine Abfrage. Deckel
# gegen QPS-/Kontingent-Verbrauch bei langen Routen.
_TOMTOM_MAX_POINTS = 40
_TOMTOM_MIN_GAP_M = 1500
_MAX_CONCURRENCY = 8


def configured_provider() -> str | None:
    """Welcher Anbieter aktiv ist (oder None, wenn kein Key gesetzt)."""
    forced = (settings.traffic_flow_provider or "").strip().lower()
    if forced == "here" and settings.here_traffic_api_key:
        return "here"
    if forced == "tomtom" and settings.tomtom_traffic_api_key:
        return "tomtom"
    if settings.here_traffic_api_key:
        return "here"
    if settings.tomtom_traffic_api_key:
        return "tomtom"
    return None


def _empty() -> dict:
    return {"type": "FeatureCollection", "features": []}


def _jam_from_speeds(current: float | None, free: float | None, closed: bool) -> float | None:
    """jamFactor 0–10 aus aktueller/frei fließender Geschwindigkeit ableiten."""
    if closed:
        return 10.0
    if current is None or free is None or free <= 0:
        return None
    ratio = max(0.0, min(1.0, current / free))
    return round((1.0 - ratio) * 10.0, 1)


# ── HERE ──────────────────────────────────────────────────────────────


def _here_features(data: dict) -> list[dict]:
    features = []
    for res in data.get("results", []):
        flow = res.get("currentFlow") or {}
        jam = flow.get("jamFactor")
        if jam is None:
            jam = _jam_from_speeds(
                flow.get("speed"), flow.get("freeFlow"),
                (flow.get("traversability") or "").lower() == "closed",
            )
        shape = (res.get("location") or {}).get("shape") or {}
        for link in shape.get("links", []):
            pts = link.get("points") or []
            coords = [[p["lng"], p["lat"]] for p in pts if "lng" in p and "lat" in p]
            if len(coords) < 2:
                continue
            features.append({
                "type": "Feature",
                "geometry": {"type": "LineString", "coordinates": coords},
                "properties": {
                    "source": "here",
                    "service": "flow",
                    "jamFactor": jam,
                    "speed": flow.get("speed"),
                    "freeFlow": flow.get("freeFlow"),
                    "traversability": flow.get("traversability"),
                },
            })
    return features


async def _here_flow(client: httpx.AsyncClient, west, south, east, north) -> list[dict]:
    params = {
        "in": f"bbox:{west:.5f},{south:.5f},{east:.5f},{north:.5f}",
        "locationReferencing": "shape",
        "apiKey": settings.here_traffic_api_key,
    }
    resp = await client.get(HERE_FLOW_URL, params=params)
    resp.raise_for_status()
    return _here_features(resp.json())


# ── TomTom ────────────────────────────────────────────────────────────


def _tomtom_feature(data: dict) -> dict | None:
    seg = data.get("flowSegmentData") or {}
    line = (seg.get("coordinates") or {}).get("coordinate") or []
    coords = [[c["longitude"], c["latitude"]] for c in line
              if "longitude" in c and "latitude" in c]
    if len(coords) < 2:
        return None
    jam = _jam_from_speeds(seg.get("currentSpeed"), seg.get("freeFlowSpeed"),
                           bool(seg.get("roadClosure")))
    return {
        "type": "Feature",
        "geometry": {"type": "LineString", "coordinates": coords},
        "properties": {
            "source": "tomtom",
            "service": "flow",
            "jamFactor": jam,
            "speed": seg.get("currentSpeed"),
            "freeFlow": seg.get("freeFlowSpeed"),
            "roadClosure": seg.get("roadClosure"),
            "frc": seg.get("frc"),
        },
    }


async def _tomtom_point(client: httpx.AsyncClient, lat: float, lon: float,
                        sem: asyncio.Semaphore) -> dict | None:
    async with sem:
        try:
            resp = await client.get(TOMTOM_FLOW_URL, params={
                "key": settings.tomtom_traffic_api_key, "point": f"{lat:.5f},{lon:.5f}",
            })
            resp.raise_for_status()
            return _tomtom_feature(resp.json())
        except Exception:
            return None


def _thin_points(route: list[tuple[float, float]]) -> list[tuple[float, float]]:
    """Route auf Stützpunkte mit Mindestabstand ausdünnen (TomTom-Abfragedeckel)."""
    if not route:
        return []
    kept = [route[0]]
    for lat, lon in route[1:]:
        p_lat, p_lon = kept[-1]
        if _haversine_m(p_lat, p_lon, lat, lon) >= _TOMTOM_MIN_GAP_M:
            kept.append((lat, lon))
        if len(kept) >= _TOMTOM_MAX_POINTS:
            break
    return kept


def _dedupe(features: list[dict]) -> list[dict]:
    seen = set()
    out = []
    for f in features:
        coords = f["geometry"]["coordinates"]
        key = (f["properties"].get("frc"), round(coords[0][0], 5), round(coords[0][1], 5),
               round(coords[-1][0], 5), round(coords[-1][1], 5))
        if key in seen:
            continue
        seen.add(key)
        out.append(f)
    return out


# ── Bounding-Box-Zerlegung für HERE ──────────────────────────────────


def _bbox_chunks(route: list[tuple[float, float]], pad_deg: float,
                 max_span_deg: float = 0.4) -> list[tuple[float, float, float, float]]:
    """Route in Bounding-Boxen begrenzter Größe zerlegen (HERE-bbox-Limit)."""
    chunks = []
    seg = [route[0]]
    for pt in route[1:]:
        seg.append(pt)
        lats = [p[0] for p in seg]
        lons = [p[1] for p in seg]
        if (max(lats) - min(lats) > max_span_deg) or (max(lons) - min(lons) > max_span_deg):
            chunks.append(seg)
            seg = [pt]
    if len(seg) >= 1:
        chunks.append(seg)

    boxes = []
    for s in chunks:
        if len(s) < 1:
            continue
        lats = [p[0] for p in s]
        lons = [p[1] for p in s]
        boxes.append((min(lons) - pad_deg, min(lats) - pad_deg,
                      max(lons) + pad_deg, max(lats) + pad_deg))
    return boxes


def _near_route(features: list[dict], route: list[tuple[float, float]], corridor_m: int) -> list[dict]:
    out = []
    for f in features:
        coords = f["geometry"]["coordinates"]
        sample = coords[:: max(1, len(coords) // 6)] or coords
        hit = any(
            _haversine_m(c[1], c[0], r_lat, r_lon) <= corridor_m
            for c in sample for r_lat, r_lon in route
        )
        if hit:
            out.append(f)
    return out


# ── Öffentliche API ───────────────────────────────────────────────────


async def flow_along_route(coordinates: list[tuple[float, float]], corridor_m: int = 1000) -> dict:
    """Verkehrslage entlang der Route ([(lon, lat), ...] GeoJSON-Reihenfolge)."""
    provider = configured_provider()
    if provider is None or len(coordinates) < 2:
        return _empty()

    route = _sample_route([(lat, lon) for lon, lat in coordinates])
    pad_deg = corridor_m / 111_000 + 0.01
    sem = asyncio.Semaphore(_MAX_CONCURRENCY)

    async with httpx.AsyncClient(timeout=20.0, headers=_HEADERS) as client:
        if provider == "here":
            boxes = _bbox_chunks(route, pad_deg)
            results = await asyncio.gather(
                *[_here_flow(client, *b) for b in boxes], return_exceptions=True
            )
            features = [f for r in results if isinstance(r, list) for f in r]
        else:  # tomtom
            pts = _thin_points(route)
            results = await asyncio.gather(*[_tomtom_point(client, lat, lon, sem) for lat, lon in pts])
            features = [f for f in results if f]

    features = _near_route(_dedupe(features), route, corridor_m)
    return {"type": "FeatureCollection", "features": features}


async def flow_around(lat: float, lon: float, radius_m: int = 3000) -> dict:
    """Verkehrslage im Umkreis eines Punktes."""
    provider = configured_provider()
    if provider is None:
        return _empty()

    async with httpx.AsyncClient(timeout=20.0, headers=_HEADERS) as client:
        if provider == "here":
            try:
                params = {
                    "in": f"circle:{lat:.5f},{lon:.5f};r={radius_m}",
                    "locationReferencing": "shape",
                    "apiKey": settings.here_traffic_api_key,
                }
                resp = await client.get(HERE_FLOW_URL, params=params)
                resp.raise_for_status()
                features = _here_features(resp.json())
            except Exception:
                features = []
        else:  # tomtom – Einzelpunkt-Abfrage am Zentrum
            f = await _tomtom_point(client, lat, lon, asyncio.Semaphore(1))
            features = [f] if f else []

    return {"type": "FeatureCollection", "features": _dedupe(features)}
