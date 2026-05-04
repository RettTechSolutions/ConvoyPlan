from typing import Any

import httpx

from app.config import settings


async def calculate_route(
    points: list[dict[str, float]],
    vehicle_params: dict[str, Any] | None = None,
) -> dict:
    """Call GraphHopper routing API and return route data."""
    payload = {
        "points": [[p["lon"], p["lat"]] for p in points],
        "profile": "car",
        "instructions": False,
        "points_encoded": False,
    }

    if vehicle_params:
        # Custom vehicle profile hints
        if "max_height_m" in vehicle_params:
            payload["custom_model"] = {
                "priority": [
                    {"if": f"max_height < {vehicle_params['max_height_m']}", "multiply_by": "0"}
                ]
            }

    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(
            f"{settings.graphhopper_url}/route",
            json=payload,
        )
        resp.raise_for_status()
        data = resp.json()

    path = data["paths"][0]
    return {
        "distance_m": int(path["distance"]),
        "duration_s": int(path["time"] / 1000),
        "geometry": path["points"],  # GeoJSON LineString
    }
