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


async def get_closures(lat: float, lon: float, radius_m: int = 15000) -> dict:
    query = _build_query(lat, lon, radius_m)
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(OVERPASS_URL, data={"data": query})
        resp.raise_for_status()
        data = resp.json()

    return _to_geojson(data.get("elements", []))
