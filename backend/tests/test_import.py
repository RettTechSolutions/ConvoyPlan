import json
import uuid
import pytest
from unittest.mock import AsyncMock, MagicMock


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


# ── _apply_import helper tests (mock DB) ────────────────────────────────────

def _mock_db(*scalar_values):
    """Mock db where each execute() call returns a result whose scalar_one_or_none() returns the given value."""
    db = AsyncMock()
    db.add = MagicMock()  # add() is synchronous in SQLAlchemy
    mocks = []
    for val in scalar_values:
        mr = MagicMock()
        mr.scalar_one_or_none.return_value = val
        mocks.append(mr)
    db.execute.side_effect = mocks
    return db


@pytest.mark.asyncio
async def test_apply_import_replace_deletes_existing():
    from app.api.routes.routing import _apply_import
    from app.services.importer import ImportResult

    convoy_id = uuid.uuid4()
    result = ImportResult(
        waypoints=[{"name": "A", "lat": 48.1, "lon": 11.5, "notes": None}],
        route_coords=None,
    )
    db = _mock_db(None)  # one execute call (delete), result not used

    response = await _apply_import(convoy_id, result, "replace", db)

    assert response == {"waypoints_imported": 1, "route_stored": False}
    assert db.execute.call_count == 1  # only the delete statement
    assert db.add.call_count == 1
    db.commit.assert_called_once()


@pytest.mark.asyncio
async def test_apply_import_add_mode_appends_order_index():
    from app.api.routes.routing import _apply_import
    from app.services.importer import ImportResult

    convoy_id = uuid.uuid4()
    result = ImportResult(
        waypoints=[
            {"name": "A", "lat": 48.1, "lon": 11.5, "notes": None},
            {"name": "B", "lat": 48.2, "lon": 11.6, "notes": None},
        ],
        route_coords=None,
    )
    # add mode: max existing order_index is 2 → new ones start at 3
    db = _mock_db(2)

    response = await _apply_import(convoy_id, result, "add", db)

    assert response == {"waypoints_imported": 2, "route_stored": False}
    added = [call.args[0] for call in db.add.call_args_list]
    assert added[0].order_index == 3
    assert added[1].order_index == 4


@pytest.mark.asyncio
async def test_apply_import_add_mode_no_existing_starts_at_zero():
    from app.api.routes.routing import _apply_import
    from app.services.importer import ImportResult

    convoy_id = uuid.uuid4()
    result = ImportResult(
        waypoints=[{"name": "A", "lat": 48.1, "lon": 11.5, "notes": None}],
        route_coords=None,
    )
    # add mode: no existing waypoints → scalar_one_or_none returns None
    db = _mock_db(None)

    await _apply_import(convoy_id, result, "add", db)

    added = db.add.call_args_list[0].args[0]
    assert added.order_index == 0


@pytest.mark.asyncio
async def test_apply_import_stores_route_when_no_existing():
    from app.api.routes.routing import _apply_import
    from app.services.importer import ImportResult
    from app.models.route import Route

    convoy_id = uuid.uuid4()
    result = ImportResult(
        waypoints=[],
        route_coords=[(11.5, 48.1), (11.6, 48.2)],
    )
    # replace mode: delete call (result ignored), route select returns None
    db = _mock_db(None, None)

    response = await _apply_import(convoy_id, result, "replace", db)

    assert response == {"waypoints_imported": 0, "route_stored": True}
    assert db.add.call_count == 1
    added = db.add.call_args_list[0].args[0]
    assert isinstance(added, Route)
    assert added.distance_m is None
    assert added.duration_s is None


@pytest.mark.asyncio
async def test_apply_import_updates_existing_route():
    from app.api.routes.routing import _apply_import
    from app.services.importer import ImportResult
    from app.models.route import Route

    convoy_id = uuid.uuid4()
    result = ImportResult(
        waypoints=[],
        route_coords=[(11.5, 48.1), (11.6, 48.2)],
    )
    existing_route = MagicMock(spec=Route)
    # replace mode: delete call, route select returns existing route
    db = _mock_db(None, existing_route)

    response = await _apply_import(convoy_id, result, "replace", db)

    assert response["route_stored"] is True
    assert db.add.call_count == 0  # updated in-place, not added again
    assert existing_route.distance_m is None
    assert existing_route.duration_s is None
