"""Offene, lizenzfreie Verkehrsdaten-Feeds (Baustellen/Sperrungen).

Dritte Datenquelle neben Overpass und der Autobahn-API. Länder und Städte
veröffentlichen Baustellen/Sperrungen als **offenes GeoJSON** (ohne API-Key,
ohne Registrierung) — allerdings jeweils in **eigenen Schemata**. Deshalb gibt
es pro Format einen kleinen Adapter:

- ``mobidata_bw`` — MobiData BW / CIFS-Stil (Baden-Württemberg, bis Kreisstraße)
- ``berlin_viz`` — Berliner Verkehrsinformationszentrale (VIZ)
- ``datex2``     — DATEX II v2 (europäischer XML-Standard), z. B. Länder-Feeds
                   aus der mobilithek für bundesweite Abdeckung abseits der
                   Autobahn. Per mTLS geschützte Feeds (mobilithek-Broker) nutzen
                   ``settings.opendata_traffic_client_cert`` (eigenes Client-
                   Zertifikat) und ``settings.opendata_traffic_ca_cert`` (private
                   Broker-CA zum Verifizieren des Servers).

Weitere Regionen lassen sich über ``settings.opendata_traffic_feeds`` ergänzen:
je Eintrag ``format|url`` (oder nur ``url`` → Standard ``mobidata_bw``). Jeder
Feed wird gebündelt geholt, kurz gecacht, auf aktuell gültige Ereignisse und den
Routenkorridor bzw. Radius gefiltert.
"""
import asyncio
import io
import os
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timezone

import httpx

from app.config import settings
from app.services.autobahn import _feature_points, _near_route
from app.services.overpass import _haversine_m, _sample_route

_HEADERS = {"Accept": "application/json", "User-Agent": "ConvoyPlan/1.0"}
# DATEX-II-Feeds (u. a. mobilithek-Broker) liefern XML — nicht JSON anfragen.
_XML_HEADERS = {"Accept": "application/xml, text/xml, */*", "User-Agent": "ConvoyPlan/1.0"}

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


# ── DATEX II v2 (europäischer Standard, z. B. mobilithek-Länderfeeds) ─


def _datex2_geoms(rec: ET.Element) -> list[dict]:
    """Geometrie eines situationRecord: bevorzugt Linie (posList), sonst Punkt."""
    geoms: list[dict] = []
    for pl in rec.findall(".//{*}posList"):
        nums = (pl.text or "").split()
        # posList ist „lat lon lat lon …" (WGS84) → zu [lon, lat] paaren.
        coords = []
        for i in range(0, len(nums) - 1, 2):
            try:
                coords.append([float(nums[i + 1]), float(nums[i])])
            except ValueError:
                continue
        if len(coords) >= 2:
            geoms.append({"type": "LineString", "coordinates": coords})
    if not geoms:
        lat = rec.findtext(".//{*}locationForDisplay/{*}latitude")
        lon = rec.findtext(".//{*}locationForDisplay/{*}longitude")
        try:
            if lat and lon:
                geoms.append({"type": "Point", "coordinates": [float(lon), float(lat)]})
        except ValueError:
            # Upstream feed may contain malformed coordinates; ignore this point.
            pass
    return geoms


def _parse_datex2(resp: httpx.Response, provider: str) -> list[dict]:
    """DATEX-II-SituationPublication in unsere Feature-Form übersetzen.

    Speicherschonend per iterparse (die Feeds können viele MB groß sein): je
    ``situation`` extrahieren und den Teilbaum danach freigeben.
    """
    out: list[dict] = []
    for _event, elem in ET.iterparse(io.BytesIO(resp.content), events=("end",)):
        tag = elem.tag.rsplit("}", 1)[-1]
        if tag != "situation":
            continue
        for rec in elem.findall("{*}situationRecord"):
            geoms = _datex2_geoms(rec)
            if not geoms:
                continue
            comments = [v.text for v in rec.findall(
                ".//{*}generalPublicComment/{*}comment/{*}values/{*}value") if v.text]
            description = comments[1] if len(comments) > 1 else None
            end = rec.findtext(".//{*}validityTimeSpecification/{*}overallEndTime")
            start = rec.findtext(".//{*}validityTimeSpecification/{*}overallStartTime")
            street = rec.findtext(".//{*}roadName") or rec.findtext(".//{*}roadNumber")
            # Verlässliches Sperr-Signal: roadOrCarriagewayOrLaneManagementType
            # = roadClosed / carriagewayClosures. Das lane-Feld ist konstant
            # „allLanesCompleteCarriageway" (nur Fahrbahn-Bezug) und untauglich.
            mgmt = " ".join(t for t in (e.text for e in rec.findall(
                ".//{*}roadOrCarriagewayOrLaneManagementType")) if t)
            closure = _is_closure(mgmt)
            title = comments[0] if comments else (street or ("Sperrung" if closure else "Baustelle"))
            props = {
                "source": "opendata",
                "provider": provider,
                "service": "closure" if closure else "roadworks",
                "title": title,
                "subtitle": description,
                "description": description or title,
                "isBlocked": "true" if closure else "false",
                "street": street,
                "starttime": start,
                "endtime": end,
                "identifier": rec.get("id"),
            }
            out.extend({"type": "Feature", "geometry": g, "properties": dict(props)} for g in geoms)
        elem.clear()
    return out


def _geojson_parser(adapt):
    def _parse(resp: httpx.Response, provider: str) -> list[dict]:
        data = resp.json()
        if not isinstance(data, dict) or data.get("type") != "FeatureCollection":
            return []
        out: list[dict] = []
        for raw in data.get("features", []):
            if isinstance(raw, dict):
                out.extend(adapt(raw, provider))
        return out
    return _parse


# Format → (Provider-Anzeigename, Parse-Funktion(response, provider) → Features)
_FORMATS = {
    "mobidata_bw": ("MobiData BW", _geojson_parser(_adapt_mobidata_bw)),
    "berlin_viz": ("Berlin VIZ", _geojson_parser(_adapt_berlin_viz)),
    "datex2": ("DATEX II", _parse_datex2),
}


# ── Abruf & Cache ────────────────────────────────────────────────────


async def _fetch_feed(client: httpx.AsyncClient, fmt: str, url: str) -> list[dict]:
    """Einen Feed holen, per Format-Parser normalisieren, Abgelaufenes ausfiltern."""
    entry = _FORMATS.get(fmt)
    if entry is None:
        return []
    provider_name, parse = entry
    try:
        resp = await client.get(url)
        resp.raise_for_status()
        features = parse(resp, provider_name)
    except Exception:
        return []
    now = datetime.now(timezone.utc)
    return [f for f in features if _is_active(f["properties"], now)]


async def _fetch_all_features() -> list[dict]:
    feeds = _feeds()
    if not feeds:
        return []

    plain = [(f, u) for f, u in feeds if f != "datex2"]
    datex = [(f, u) for f, u in feeds if f == "datex2"]
    features: list[dict] = []

    if plain:
        async with httpx.AsyncClient(timeout=20.0, headers=_HEADERS) as client:
            results = await asyncio.gather(*[_fetch_feed(client, f, u) for f, u in plain])
        for res in results:
            features.extend(res)

    # DATEX-II-Feeds ggf. mit Client-Zertifikat (mobilithek-Broker/mTLS) und in
    # einem eigenen Client, damit ein fehlkonfiguriertes Zertifikat die offenen
    # Feeds nicht mitreißt.
    if datex:
        cert = settings.opendata_traffic_client_cert or None
        if cert and not os.path.exists(cert):
            cert = None
        # Vertrauenskette des Brokers (mobilithek nutzt eine private M2M-CA);
        # ohne sie schlägt die TLS-Verifikation fehl. Fällt auf den öffentlichen
        # Trust-Store zurück, wenn keine CA-Datei hinterlegt/vorhanden ist.
        ca = settings.opendata_traffic_ca_cert or None
        verify = ca if ca and os.path.exists(ca) else True
        async with httpx.AsyncClient(
            timeout=40.0, headers=_XML_HEADERS, cert=cert, verify=verify, follow_redirects=True
        ) as client:
            results = await asyncio.gather(*[_fetch_feed(client, f, u) for f, u in datex])
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
