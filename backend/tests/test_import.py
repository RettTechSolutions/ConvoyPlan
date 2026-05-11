import json
import uuid  # noqa: F401
import pytest
from unittest.mock import AsyncMock, MagicMock  # noqa: F401


# ── importer service tests (pure functions, no DB) ──────────────────────────

def test_parse_gpx_waypoints_and_track():
    from app.services.importer import parse_gpx
    content = b"""<?xml version="1.0"?>
<gpx version="1.1" xmlns="http://www.topografix.com/GPX/1/1">
  <wpt lat="48.1" lon="11.5"><name>Start</name><desc>Startpunkt</desc></wpt>
  <wpt lat="48.2" lon="11.6"><name>Ziel</name></wpt>
  <trk><trkseg>
    <trkpt lat="48.1" lon="11.5"/>
    <trkpt lat="48.15" lon="11.55"/>
    <trkpt lat="48.2" lon="11.6"/>
  </trkseg></trk>
</gpx>"""
    result = parse_gpx(content)
    assert len(result.waypoints) == 2
    assert result.waypoints[0] == {"name": "Start", "lat": 48.1, "lon": 11.5, "notes": "Startpunkt"}
    assert result.waypoints[1] == {"name": "Ziel", "lat": 48.2, "lon": 11.6, "notes": None}
    assert result.route_coords == [(11.5, 48.1), (11.55, 48.15), (11.6, 48.2)]


def test_parse_gpx_waypoints_only():
    from app.services.importer import parse_gpx
    content = b"""<?xml version="1.0"?>
<gpx version="1.1" xmlns="http://www.topografix.com/GPX/1/1">
  <wpt lat="48.1" lon="11.5"><name>A</name></wpt>
</gpx>"""
    result = parse_gpx(content)
    assert len(result.waypoints) == 1
    assert result.route_coords is None


def test_parse_gpx_track_only():
    from app.services.importer import parse_gpx
    content = b"""<?xml version="1.0"?>
<gpx version="1.1" xmlns="http://www.topografix.com/GPX/1/1">
  <trk><trkseg>
    <trkpt lat="48.1" lon="11.5"/>
    <trkpt lat="48.2" lon="11.6"/>
  </trkseg></trk>
</gpx>"""
    result = parse_gpx(content)
    assert result.waypoints == []
    assert result.route_coords == [(11.5, 48.1), (11.6, 48.2)]


def test_parse_gpx_multi_segment_track_concatenated():
    from app.services.importer import parse_gpx
    content = b"""<?xml version="1.0"?>
<gpx version="1.1" xmlns="http://www.topografix.com/GPX/1/1">
  <trk>
    <trkseg>
      <trkpt lat="48.1" lon="11.5"/>
      <trkpt lat="48.15" lon="11.55"/>
    </trkseg>
    <trkseg>
      <trkpt lat="48.2" lon="11.6"/>
      <trkpt lat="48.25" lon="11.65"/>
    </trkseg>
  </trk>
</gpx>"""
    result = parse_gpx(content)
    assert result.route_coords == [
        (11.5, 48.1), (11.55, 48.15), (11.6, 48.2), (11.65, 48.25)
    ]


def test_parse_gpx_fallback_name():
    from app.services.importer import parse_gpx
    content = b"""<?xml version="1.0"?>
<gpx version="1.1" xmlns="http://www.topografix.com/GPX/1/1">
  <wpt lat="48.1" lon="11.5"></wpt>
</gpx>"""
    result = parse_gpx(content)
    assert result.waypoints[0]["name"] == "Waypoint 1"


def test_parse_gpx_invalid_raises():
    from app.services.importer import parse_gpx
    with pytest.raises(ValueError, match="Invalid GPX"):
        parse_gpx(b"not xml at all")


def test_parse_gpx_empty_raises():
    from app.services.importer import parse_gpx
    content = b"""<?xml version="1.0"?>
<gpx version="1.1" xmlns="http://www.topografix.com/GPX/1/1"></gpx>"""
    with pytest.raises(ValueError, match="No importable data"):
        parse_gpx(content)


def test_parse_geojson_feature_collection():
    from app.services.importer import parse_geojson
    data = {
        "type": "FeatureCollection",
        "features": [
            {"type": "Feature", "geometry": {"type": "Point", "coordinates": [11.5, 48.1]},
             "properties": {"name": "Alpha", "description": "Desc"}},
            {"type": "Feature", "geometry": {"type": "Point", "coordinates": [11.6, 48.2]},
             "properties": {"name": "Beta"}},
            {"type": "Feature", "geometry": {"type": "LineString",
             "coordinates": [[11.5, 48.1], [11.6, 48.2]]}, "properties": {}},
        ],
    }
    result = parse_geojson(json.dumps(data).encode())
    assert len(result.waypoints) == 2
    assert result.waypoints[0] == {"name": "Alpha", "lat": 48.1, "lon": 11.5, "notes": "Desc"}
    assert result.waypoints[1]["notes"] is None
    assert result.route_coords == [(11.5, 48.1), (11.6, 48.2)]


def test_parse_geojson_points_only():
    from app.services.importer import parse_geojson
    data = {"type": "FeatureCollection", "features": [
        {"type": "Feature", "geometry": {"type": "Point", "coordinates": [11.5, 48.1]},
         "properties": {"name": "X"}},
    ]}
    result = parse_geojson(json.dumps(data).encode())
    assert len(result.waypoints) == 1
    assert result.route_coords is None


def test_parse_geojson_fallback_name():
    from app.services.importer import parse_geojson
    data = {"type": "FeatureCollection", "features": [
        {"type": "Feature", "geometry": {"type": "Point", "coordinates": [11.5, 48.1]},
         "properties": {}},
    ]}
    result = parse_geojson(json.dumps(data).encode())
    assert result.waypoints[0]["name"] == "Waypoint 1"


def test_parse_geojson_invalid_raises():
    from app.services.importer import parse_geojson
    with pytest.raises(ValueError, match="Invalid GeoJSON"):
        parse_geojson(b"not json {{{")


def test_parse_geojson_empty_raises():
    from app.services.importer import parse_geojson
    data = {"type": "FeatureCollection", "features": []}
    with pytest.raises(ValueError, match="No importable data"):
        parse_geojson(json.dumps(data).encode())
