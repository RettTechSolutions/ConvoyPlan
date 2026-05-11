import json
from dataclasses import dataclass

import gpxpy
import gpxpy.gpx


@dataclass
class ImportResult:
    waypoints: list[dict]
    route_coords: list[tuple[float, float]] | None  # (lon, lat) order for PostGIS


def parse_gpx(content: bytes) -> ImportResult:
    try:
        gpx = gpxpy.parse(content.decode("utf-8"))
    except Exception:
        raise ValueError("Invalid GPX file")

    waypoints = []
    for i, wpt in enumerate(gpx.waypoints):
        waypoints.append({
            "name": wpt.name or f"Waypoint {i + 1}",
            "lat": wpt.latitude,
            "lon": wpt.longitude,
            "notes": wpt.description or None,
        })

    route_coords = None
    for track in gpx.tracks:
        for segment in track.segments:
            if segment.points:
                route_coords = [(p.longitude, p.latitude) for p in segment.points]
                break
        if route_coords is not None:
            break

    if not waypoints and route_coords is None:
        raise ValueError("No importable data found")

    return ImportResult(waypoints=waypoints, route_coords=route_coords)


def parse_geojson(content: bytes) -> ImportResult:
    try:
        data = json.loads(content)
    except Exception:
        raise ValueError("Invalid GeoJSON file")

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
            lon, lat = geom["coordinates"][0], geom["coordinates"][1]
            wp_count += 1
            waypoints.append({
                "name": props.get("name") or f"Waypoint {wp_count}",
                "lat": lat,
                "lon": lon,
                "notes": props.get("description") or props.get("notes") or None,
            })
        elif geom.get("type") == "LineString" and route_coords is None:
            route_coords = [(c[0], c[1]) for c in geom["coordinates"]]

    if not waypoints and route_coords is None:
        raise ValueError("No importable data found")

    return ImportResult(waypoints=waypoints, route_coords=route_coords)
