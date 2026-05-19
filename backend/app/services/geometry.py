from geoalchemy2.shape import to_shape
from shapely.geometry import mapping


def point_to_wkt(lat: float, lon: float) -> str:
    return f"SRID=4326;POINT({lon} {lat})"


def wkb_to_point(geom) -> dict | None:
    if geom is None:
        return None
    try:
        shape = to_shape(geom)
        return {"lat": shape.y, "lon": shape.x}
    except (AssertionError, Exception):
        return None


def waypoint_coords(waypoint) -> dict:
    coords = wkb_to_point(waypoint.location)
    if coords:
        return {"lat": coords["lat"], "lon": coords["lon"]}
    return {"lat": None, "lon": None}


def linestring_to_geojson(geom) -> dict | None:
    if geom is None:
        return None
    shape = to_shape(geom)
    return mapping(shape)
