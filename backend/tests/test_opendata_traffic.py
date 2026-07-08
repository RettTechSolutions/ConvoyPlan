"""Tests für den Open-Data-Verkehrsdatenservice (Multi-Format: MobiData BW + Berlin)."""
import httpx
import pytest

from app.config import settings
from app.services import opendata_traffic as od
from app.services.opendata_traffic import (
    _adapt_berlin_viz,
    _adapt_mobidata_bw,
    _flatten_geoms,
    _is_closure,
    _parse_datex2,
    features_around,
)


_DATEX2_XML = b"""<?xml version="1.0" encoding="UTF-8"?>
<d2LogicalModel modelBaseVersion="2" xmlns="http://datex2.eu/schema/2/2_0">
 <payloadPublication xsi:type="SituationPublication" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
  <situation id="s1">
   <situationRecord xsi:type="ConstructionWorks" id="r1">
    <validity><validityTimeSpecification>
      <overallStartTime>2020-01-01T00:00:00.000+01:00</overallStartTime>
      <overallEndTime>2999-01-01T00:00:00.000+01:00</overallEndTime>
    </validityTimeSpecification></validity>
    <generalPublicComment><comment><values><value lang="DE">B10 Baustelle</value></values></comment></generalPublicComment>
    <groupOfLocations xsi:type="Linear">
     <locationForDisplay><latitude>48.70</latitude><longitude>9.00</longitude></locationForDisplay>
     <linearExtension><linearExtended><gmlLineString><srsName>WGS84 EPSG 4326</srsName>
       <posList>48.70 9.00 48.71 9.01</posList></gmlLineString></linearExtended></linearExtension>
     <roadName>B10</roadName>
    </groupOfLocations>
   </situationRecord>
   <situationRecord xsi:type="RoadOrCarriagewayOrLaneManagement" id="r2">
    <validity><validityTimeSpecification>
      <overallEndTime>2999-01-01T00:00:00.000+01:00</overallEndTime>
    </validityTimeSpecification></validity>
    <roadOrCarriagewayOrLaneManagementType>roadClosed</roadOrCarriagewayOrLaneManagementType>
    <groupOfLocations><locationForDisplay><latitude>50.0</latitude><longitude>8.0</longitude></locationForDisplay></groupOfLocations>
   </situationRecord>
  </situation>
  <situation id="s2">
   <situationRecord xsi:type="ConstructionWorks" id="r3">
    <validity><validityTimeSpecification>
      <overallEndTime>2000-01-01T00:00:00.000+01:00</overallEndTime>
    </validityTimeSpecification></validity>
    <generalPublicComment><comment><values><value lang="DE">Alte Baustelle</value></values></comment></generalPublicComment>
    <groupOfLocations><locationForDisplay><latitude>52.0</latitude><longitude>13.0</longitude></locationForDisplay></groupOfLocations>
   </situationRecord>
  </situation>
 </payloadPublication>
</d2LogicalModel>"""


class _XmlResp:
    def __init__(self, content):
        self.content = content


@pytest.fixture(autouse=True)
def _reset(monkeypatch):
    od._cache = {"features": None, "fetched_at": 0.0}
    monkeypatch.setattr(settings, "opendata_traffic_enabled", True)
    monkeypatch.setattr(settings, "opendata_traffic_feeds", "mobidata_bw|https://example.org/bw.json")
    yield


# ── Feed-Konfiguration (format|url) ──────────────────────────────────


def test_feeds_parses_format_and_url(monkeypatch):
    monkeypatch.setattr(settings, "opendata_traffic_feeds",
                        "mobidata_bw|https://a/x.json, berlin_viz|https://b/y.json")
    assert od._feeds() == [
        ("mobidata_bw", "https://a/x.json"),
        ("berlin_viz", "https://b/y.json"),
    ]


def test_feeds_bare_url_defaults_to_mobidata(monkeypatch):
    monkeypatch.setattr(settings, "opendata_traffic_feeds", "https://a/x.json")
    assert od._feeds() == [("mobidata_bw", "https://a/x.json")]


def test_feeds_disabled(monkeypatch):
    monkeypatch.setattr(settings, "opendata_traffic_enabled", False)
    assert od._feeds() == []


# ── Adapter: MobiData BW ─────────────────────────────────────────────


def test_adapt_mobidata_roadworks():
    raw = {
        "geometry": {"type": "LineString", "coordinates": [[9.0, 48.5], [9.01, 48.51]]},
        "properties": {"type": "CONSTRUCTION", "street": "K1077", "description": "Erdlager",
                       "reference": "MobiData BW", "id": "abc"},
    }
    feats = _adapt_mobidata_bw(raw, "MobiData BW")
    assert len(feats) == 1
    p = feats[0]["properties"]
    assert p["source"] == "opendata" and p["provider"] == "MobiData BW"
    assert p["service"] == "roadworks" and p["isBlocked"] == "false"
    assert p["title"] == "K1077"


def test_adapt_mobidata_closure():
    raw = {"geometry": {"type": "Point", "coordinates": [9.0, 48.5]},
           "properties": {"type": "CLOSURE", "street": "B14"}}
    assert _adapt_mobidata_bw(raw, "p")[0]["properties"]["service"] == "closure"


# ── Adapter: Berlin VIZ ──────────────────────────────────────────────


def test_adapt_berlin_geometrycollection_flattened():
    raw = {
        "geometry": {"type": "GeometryCollection", "geometries": [
            {"type": "Point", "coordinates": [13.3, 52.5]},
            {"type": "LineString", "coordinates": [[13.3, 52.5], [13.31, 52.51]]},
        ]},
        "properties": {"subtype": "Baustelle", "street": "Wolfensteindamm",
                       "content": "Fahrbahn verengt", "severity": "keine Sperrung",
                       "id": "8/2025", "validity": {"from": "2025-07-23T07:00", "to": "2099-08-17T17:00"}},
    }
    feats = _adapt_berlin_viz(raw, "Berlin VIZ")
    # GeometryCollection → zwei Einzel-Features (Point + LineString)
    assert len(feats) == 2
    assert {f["geometry"]["type"] for f in feats} == {"Point", "LineString"}
    p = feats[0]["properties"]
    assert p["provider"] == "Berlin VIZ"
    assert p["service"] == "roadworks"   # „keine Sperrung"
    assert p["endtime"] == "2099-08-17T17:00"
    assert p["street"] == "Wolfensteindamm"


def test_adapt_berlin_closure_from_severity():
    raw = {"geometry": {"type": "Point", "coordinates": [13.3, 52.5]},
           "properties": {"subtype": "Sperrung", "severity": "Vollsperrung", "street": "X"}}
    assert _adapt_berlin_viz(raw, "p")[0]["properties"]["service"] == "closure"


def test_is_closure_ignores_keine_sperrung():
    assert _is_closure("keine Sperrung", "Baustelle") is False
    assert _is_closure("Vollsperrung") is True


# ── Geometrie-Flattening ─────────────────────────────────────────────


def test_flatten_polygon_to_linestring():
    poly = {"type": "Polygon", "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 0]]]}
    out = _flatten_geoms(poly)
    assert len(out) == 1 and out[0]["type"] == "LineString"


# ── HTTP + Filter (Adapter-Auswahl je Feed) ──────────────────────────


class _FeedClient:
    payloads: dict = {}  # url -> FeatureCollection

    def __init__(self, *a, **k):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *e):
        return False

    async def get(self, url):
        return httpx.Response(200, json=_FeedClient.payloads.get(url, {"type": "FeatureCollection", "features": []}),
                              request=httpx.Request("GET", url))


def _fc(*features):
    return {"type": "FeatureCollection", "features": list(features)}


async def test_two_feeds_merged_with_correct_adapters(monkeypatch):
    monkeypatch.setattr(settings, "opendata_traffic_feeds",
                        "mobidata_bw|https://bw/x.json,berlin_viz|https://berlin/y.json")
    _FeedClient.payloads = {
        "https://bw/x.json": _fc({
            "geometry": {"type": "Point", "coordinates": [9.0, 48.5]},
            "properties": {"type": "CONSTRUCTION", "street": "BW-Strasse", "id": "1",
                           "endtime": "2999-01-01T00:00:00+00:00"}}),
        "https://berlin/y.json": _fc({
            "geometry": {"type": "Point", "coordinates": [13.4, 52.5]},
            "properties": {"subtype": "Baustelle", "street": "Berlin-Strasse", "severity": "keine Sperrung",
                           "id": "2", "validity": {"to": "2999-01-01T00:00"}}}),
    }
    monkeypatch.setattr(od.httpx, "AsyncClient", _FeedClient)
    feats = await od._get_features()
    providers = {f["properties"]["provider"] for f in feats}
    assert providers == {"MobiData BW", "Berlin VIZ"}


async def test_features_around_filters_by_radius(monkeypatch):
    _FeedClient.payloads = {"https://example.org/bw.json": _fc(
        {"geometry": {"type": "Point", "coordinates": [9.00, 48.50]},
         "properties": {"type": "CONSTRUCTION", "street": "nah", "id": "1",
                        "endtime": "2999-01-01T00:00:00+00:00"}},
        {"geometry": {"type": "Point", "coordinates": [13.40, 52.50]},
         "properties": {"type": "CONSTRUCTION", "street": "fern", "id": "2",
                        "endtime": "2999-01-01T00:00:00+00:00"}},
    )}
    monkeypatch.setattr(od.httpx, "AsyncClient", _FeedClient)
    out = await features_around(48.50, 9.00, radius_m=2000)
    assert {f["properties"]["title"] for f in out} == {"nah"}


async def test_expired_events_dropped(monkeypatch):
    _FeedClient.payloads = {"https://example.org/bw.json": _fc(
        {"geometry": {"type": "Point", "coordinates": [9.0, 48.5]},
         "properties": {"type": "CONSTRUCTION", "street": "alt", "id": "1",
                        "endtime": "2000-01-01T00:00:00+00:00"}},
    )}
    monkeypatch.setattr(od.httpx, "AsyncClient", _FeedClient)
    out = await features_around(48.5, 9.0, 5000)
    assert out == []


async def test_disabled_returns_empty(monkeypatch):
    monkeypatch.setattr(settings, "opendata_traffic_enabled", False)
    out = await features_around(48.5, 9.0, 5000)
    assert out == []


# ── DATEX II (europäischer Standard, mobilithek-Länderfeeds) ─────────


def test_parse_datex2_construction_linestring():
    feats = _parse_datex2(_XmlResp(_DATEX2_XML), "DATEX II")
    r1 = next(f for f in feats if f["properties"]["identifier"] == "r1")
    assert r1["geometry"]["type"] == "LineString"
    # posList „lat lon" → GeoJSON [lon, lat]
    assert r1["geometry"]["coordinates"] == [[9.00, 48.70], [9.01, 48.71]]
    assert r1["properties"]["service"] == "roadworks"
    assert r1["properties"]["title"] == "B10 Baustelle"
    assert r1["properties"]["street"] == "B10"


def test_parse_datex2_closure_from_management():
    feats = _parse_datex2(_XmlResp(_DATEX2_XML), "DATEX II")
    r2 = next(f for f in feats if f["properties"]["identifier"] == "r2")
    assert r2["geometry"] == {"type": "Point", "coordinates": [8.0, 50.0]}
    assert r2["properties"]["service"] == "closure"     # roadClosed
    assert r2["properties"]["title"] == "Sperrung"      # ohne Kommentar/Straße


async def test_datex2_client_uses_cert_and_ca(monkeypatch, tmp_path):
    """Der DATEX-II-Client bekommt Client-Zertifikat und CA-Kette (verify)."""
    cert = tmp_path / "client.pem"
    cert.write_text("x")
    ca = tmp_path / "ca.pem"
    ca.write_text("y")
    monkeypatch.setattr(settings, "opendata_traffic_feeds", "datex2|https://land/x.xml")
    monkeypatch.setattr(settings, "opendata_traffic_client_cert", str(cert))
    monkeypatch.setattr(settings, "opendata_traffic_ca_cert", str(ca))

    seen = {}

    class _Client:
        def __init__(self, *a, **k):
            seen.update(k)

        async def __aenter__(self):
            return self

        async def __aexit__(self, *e):
            return False

        async def get(self, url):
            return httpx.Response(200, content=_DATEX2_XML, request=httpx.Request("GET", url))

    monkeypatch.setattr(od.httpx, "AsyncClient", _Client)
    await od._get_features()
    assert seen.get("cert") == str(cert)
    assert seen.get("verify") == str(ca)


async def test_datex2_feed_filters_expired(monkeypatch):
    monkeypatch.setattr(settings, "opendata_traffic_feeds", "datex2|https://land/x.xml")

    class _Client:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *e):
            return False

        async def get(self, url):
            return httpx.Response(200, content=_DATEX2_XML, request=httpx.Request("GET", url))

    monkeypatch.setattr(od.httpx, "AsyncClient", _Client)
    feats = await od._get_features()
    ids = {f["properties"]["identifier"] for f in feats}
    # r3 ist abgelaufen (2000) → gefiltert; r1 + r2 bleiben
    assert ids == {"r1", "r2"}
