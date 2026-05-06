from math import asin, cos, radians, sin, sqrt
from typing import Any

import httpx

from app.config import settings

URBAN_ROAD_CLASSES = {"residential", "living_street", "service"}

_PRIORITY_RULES = {
    "schnell": [],
    "bundesstrasse": [
        {"if": "road_class == MOTORWAY", "multiply_by": "0.3"}
    ],
    "landstrasse": [
        {"if": "road_class == MOTORWAY || road_class == TRUNK", "multiply_by": "0.05"}
    ],
}


def _haversine_m(lon1: float, lat1: float, lon2: float, lat2: float) -> float:
    R = 6_371_000
    dlon, dlat = radians(lon2 - lon1), radians(lat2 - lat1)
    a = sin(dlat / 2) ** 2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlon / 2) ** 2
    return 2 * R * asin(sqrt(a))


def _segment_dist_m(coords: list, from_i: int, to_i: int) -> float:
    return sum(
        _haversine_m(coords[i][0], coords[i][1], coords[i + 1][0], coords[i + 1][1])
        for i in range(from_i, to_i)
    )


async def calculate_route(
    points: list[dict[str, float]],
    vehicle_params: dict[str, Any] | None = None,
    road_preference: str = "schnell",
) -> dict:
    """Call GraphHopper routing API and return route data with road_class details."""
    payload: dict[str, Any] = {
        "points": [[p["lon"], p["lat"]] for p in points],
        "profile": "car",
        "instructions": False,
        "points_encoded": False,
        "details": ["road_class"],
    }

    priority_rules = list(_PRIORITY_RULES.get(road_preference, []))

    custom_model: dict[str, Any] = {}
    if vehicle_params and "max_height_m" in vehicle_params:
        custom_model["priority"] = [
            {"if": f"max_height < {vehicle_params['max_height_m']}", "multiply_by": "0"},
            *priority_rules,
        ]
    elif priority_rules:
        custom_model["priority"] = priority_rules

    if custom_model:
        payload["custom_model"] = custom_model

    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(
            f"{settings.graphhopper_url}/route",
            json=payload,
        )
        if not resp.is_success:
            try:
                detail = resp.json().get("message", resp.text)
            except Exception:
                detail = resp.text
            raise ValueError(f"GraphHopper {resp.status_code}: {detail}")
        data = resp.json()

    path = data["paths"][0]
    return {
        "distance_m": int(path["distance"]),
        "duration_s": int(path["time"] / 1000),
        "geometry": path["points"],
        "road_class_details": path.get("details", {}).get("road_class", []),
    }
