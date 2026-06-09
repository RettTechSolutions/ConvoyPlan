import json
import math
from dataclasses import dataclass

import gpxpy
import gpxpy.gpx

# Hard caps to prevent import-based DoS.
_MAX_WAYPOINTS = 500
_MAX_ROUTE_COORDS = 50_000


def _check_coord(lat: float, lon: float) -> None:
    """Raise ValueError when lat/lon are outside valid WGS-84 ranges or non-finite."""
    if not (math.isfinite(lat) and math.isfinite(lon)):
        raise ValueError("Coordinate contains non-finite value (NaN or Inf)")
    if not (-90.0 <= lat <= 90.0 and -180.0 <= lon <= 180.0):
        raise ValueError(
            f"Coordinate out of range: lat={lat}, lon={lon} "
            "(lat must be -90..90, lon must be -180..180)"
        )


@dataclass
class ImportResult:
    waypoints: list[dict]
    route_coords: list[tuple[float, float]] | None  # (lon, lat) order for PostGIS


def parse_gpx(content: bytes) -> ImportResult:
    try:
        gpx = gpxpy.parse(content.decode("utf-8"))
    except (gpxpy.gpx.GPXException, UnicodeDecodeError, ValueError) as e:
        raise ValueError("Invalid GPX file") from e

    if len(gpx.waypoints) > _MAX_WAYPOINTS:
        raise ValueError(
            f"Too many waypoints in GPX file (max {_MAX_WAYPOINTS}, got {len(gpx.waypoints)})"
        )

    waypoints = []
    for i, wpt in enumerate(gpx.waypoints):
        _check_coord(wpt.latitude, wpt.longitude)
        waypoints.append({
            "name": wpt.name or f"Waypoint {i + 1}",
            "lat": wpt.latitude,
            "lon": wpt.longitude,
            "notes": wpt.description or None,
        })

    route_coords: list[tuple[float, float]] | None = None
    for track in gpx.tracks:
        for segment in track.segments:
            for p in segment.points:
                if route_coords is None:
                    route_coords = []
                if len(route_coords) >= _MAX_ROUTE_COORDS:
                    raise ValueError(
                        f"Track contains too many points (max {_MAX_ROUTE_COORDS})"
                    )
                _check_coord(p.latitude, p.longitude)
                route_coords.append((p.longitude, p.latitude))
        if route_coords is not None:
            break  # use first track only, but all its segments

    if not waypoints and route_coords is None:
        raise ValueError("No importable data found")

    return ImportResult(waypoints=waypoints, route_coords=route_coords)


def parse_geojson(content: bytes) -> ImportResult:
    try:
        data = json.loads(content)
    except (json.JSONDecodeError, UnicodeDecodeError, ValueError) as e:
        raise ValueError("Invalid GeoJSON file") from e

    if data.get("type") == "FeatureCollection":
        features = data.get("features", [])
    elif data.get("type") == "Feature":
        features = [data]
    else:
        raise ValueError("Invalid GeoJSON file")

    waypoints: list[dict] = []
    route_coords: list[tuple[float, float]] | None = None
    wp_count = 0

    for feature in features:
        geom = feature.get("geometry") or {}
        props = feature.get("properties") or {}

        if geom.get("type") == "Point":
            try:
                lon, lat = geom["coordinates"][0], geom["coordinates"][1]
            except (KeyError, IndexError, TypeError):
                raise ValueError("Invalid GeoJSON file")
            if wp_count >= _MAX_WAYPOINTS:
                raise ValueError(
                    f"Too many waypoints in GeoJSON file (max {_MAX_WAYPOINTS})"
                )
            _check_coord(lat, lon)
            wp_count += 1
            waypoints.append({
                "name": props.get("name") or f"Waypoint {wp_count}",
                "lat": lat,
                "lon": lon,
                "notes": props.get("description") or props.get("notes") or None,
            })
        elif geom.get("type") == "LineString" and route_coords is None:
            try:
                coords_raw = geom["coordinates"]
            except (KeyError, TypeError):
                raise ValueError("Invalid GeoJSON file")
            if len(coords_raw) > _MAX_ROUTE_COORDS:
                raise ValueError(
                    f"LineString contains too many vertices (max {_MAX_ROUTE_COORDS})"
                )
            try:
                parsed: list[tuple[float, float]] = []
                for c in coords_raw:
                    lon_c, lat_c = c[0], c[1]
                    _check_coord(lat_c, lon_c)
                    parsed.append((lon_c, lat_c))
                route_coords = parsed
            except (KeyError, IndexError, TypeError):
                raise ValueError("Invalid GeoJSON file")

    if not waypoints and route_coords is None:
        raise ValueError("No importable data found")

    return ImportResult(waypoints=waypoints, route_coords=route_coords)
