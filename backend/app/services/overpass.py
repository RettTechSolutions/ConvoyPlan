import httpx

OVERPASS_URL = "https://overpass-api.de/api/interpreter"


def _build_query(lat: float, lon: float, radius_m: int = 15000) -> str:
    return f"""
[out:json][timeout:25];
(
  way["highway"]["construction"](around:{radius_m},{lat},{lon});
  node["highway"="road_works"](around:{radius_m},{lat},{lon});
  way["access"="no"]["highway"](around:{radius_m},{lat},{lon});
  node["access"="no"]["highway"](around:{radius_m},{lat},{lon});
);
out body geom;
"""


def _to_geojson(elements: list) -> dict:
    features = []
    for el in elements:
        props = {k: v for k, v in el.get("tags", {}).items()}
        props["osm_type"] = el.get("type")
        props["osm_id"] = el.get("id")

        if el["type"] == "node":
            geometry = {"type": "Point", "coordinates": [el["lon"], el["lat"]]}
        elif el["type"] == "way" and "geometry" in el:
            coords = [[g["lon"], g["lat"]] for g in el["geometry"]]
            geometry = {"type": "LineString", "coordinates": coords}
        else:
            continue

        features.append({"type": "Feature", "geometry": geometry, "properties": props})

    return {"type": "FeatureCollection", "features": features}


async def find_fuel_stations(lat: float, lon: float, radius_m: int = 3000) -> list[dict]:
    """Return nearby fuel stations sorted by distance from (lat, lon)."""
    query = f"""
[out:json][timeout:15];
node["amenity"="fuel"](around:{radius_m},{lat},{lon});
out body;
"""
    async with httpx.AsyncClient(timeout=20.0) as client:
        resp = await client.post(OVERPASS_URL, data={"data": query})
        resp.raise_for_status()
        data = resp.json()

    import math

    def _dist(a_lat, a_lon):
        dlat = math.radians(a_lat - lat)
        dlon = math.radians(a_lon - lon)
        a = math.sin(dlat / 2) ** 2 + math.cos(math.radians(lat)) * math.cos(math.radians(a_lat)) * math.sin(dlon / 2) ** 2
        return 6_371_000 * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))

    stations = []
    for el in data.get("elements", []):
        if el.get("type") != "node":
            continue
        tags = el.get("tags", {})
        stations.append({
            "osm_id": el["id"],
            "lat": el["lat"],
            "lon": el["lon"],
            "name": tags.get("name") or tags.get("brand") or "Tankstelle",
            "brand": tags.get("brand"),
            "operator": tags.get("operator"),
            "opening_hours": tags.get("opening_hours"),
            "distance_m": round(_dist(el["lat"], el["lon"])),
        })

    stations.sort(key=lambda s: s["distance_m"])
    return stations[:10]


async def get_closures(lat: float, lon: float, radius_m: int = 15000) -> dict:
    query = _build_query(lat, lon, radius_m)
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(OVERPASS_URL, data={"data": query})
        resp.raise_for_status()
        data = resp.json()

    return _to_geojson(data.get("elements", []))
