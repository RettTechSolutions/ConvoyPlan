import json
from datetime import datetime
from typing import Any

import gpxpy
import gpxpy.gpx


def build_gpx(convoy_name: str, waypoints: list[Any], route_coords: list[list[float]]) -> str:
    """Generate GPX file content from convoy data."""
    gpx = gpxpy.gpx.GPX()
    gpx.name = convoy_name

    track = gpxpy.gpx.GPXTrack(name=convoy_name)
    gpx.tracks.append(track)
    segment = gpxpy.gpx.GPXTrackSegment()
    track.segments.append(segment)

    for lon, lat in route_coords:
        segment.points.append(gpxpy.gpx.GPXTrackPoint(lat, lon))

    for wp in waypoints:
        if wp.get("lat") and wp.get("lon"):
            wpt = gpxpy.gpx.GPXWaypoint(
                latitude=wp["lat"],
                longitude=wp["lon"],
                name=wp["name"],
                description=wp.get("notes", ""),
            )
            gpx.waypoints.append(wpt)

    return gpx.to_xml()


def build_json_export(convoy: Any, waypoints: list[dict], vehicles: list[dict]) -> str:
    """Serialize full convoy data to JSON."""
    data = {
        "name": convoy.name,
        "organization": convoy.organization,
        "start_time": convoy.start_time.isoformat() if convoy.start_time else None,
        "speed_urban_kmh": convoy.speed_urban_kmh,
        "speed_rural_kmh": convoy.speed_rural_kmh,
        "vehicles": vehicles,
        "waypoints": waypoints,
    }
    return json.dumps(data, ensure_ascii=False, indent=2)
