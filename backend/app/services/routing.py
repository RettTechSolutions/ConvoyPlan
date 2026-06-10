import logging
from math import asin, cos, radians, sin, sqrt
from typing import Any

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

URBAN_ROAD_CLASSES = {"residential", "living_street", "service"}
URBAN_SPEED_THRESHOLD_KMH = 50  # posted limit ≤ this → innerorts

_PRIORITY_RULES = {
    "schnell": [],
    "bundesstrasse": [
        {"if": "road_class == MOTORWAY", "multiply_by": "0.3"},
        # Prefer PRIMARY/SECONDARY (Bundesstraße/Staatsstraße) over Kreisstraßen —
        # TERTIARY roads are often narrower and less suitable for convoy movement.
        {"if": "road_class == TERTIARY", "multiply_by": "0.5"},
        # Avoid village streets and living zones entirely.
        {"if": "road_class == RESIDENTIAL || road_class == LIVING_STREET", "multiply_by": "0.1"},
    ],
    "landstrasse": [
        {"if": "road_class == MOTORWAY || road_class == TRUNK", "multiply_by": "0.05"},
        # Avoid village streets and living zones entirely.
        {"if": "road_class == RESIDENTIAL || road_class == LIVING_STREET", "multiply_by": "0.1"},
    ],
}


def _haversine_m(lon1: float, lat1: float, lon2: float, lat2: float) -> float:
    R = 6_371_000  # mean Earth radius in metres
    dlon, dlat = radians(lon2 - lon1), radians(lat2 - lat1)
    a = sin(dlat / 2) ** 2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlon / 2) ** 2
    return 2 * R * asin(sqrt(a))


def _segment_dist_m(coords: list, from_i: int, to_i: int) -> float:
    return sum(
        _haversine_m(coords[i][0], coords[i][1], coords[i + 1][0], coords[i + 1][1])
        for i in range(from_i, to_i)
    )


def convoy_duration_s(
    distance_m: int,
    coords: list,
    road_class_details: list,
    speed_urban_kmh: int,
    speed_rural_kmh: int,
    max_speed_details: list | None = None,
) -> int:
    """Calculate convoy travel time using posted speed limits (preferred) or road class."""
    speed_urban_kmh = max(1, speed_urban_kmh)
    speed_rural_kmh = max(1, speed_rural_kmh)

    n_coords = len(coords)
    has_details = (road_class_details or max_speed_details) and n_coords >= 2

    if has_details:
        # Build per-segment urban flag (None = unknown) for each coord-pair index.
        n_segs = n_coords - 1
        is_urban: list[bool | None] = [None] * n_segs

        # First pass: road_class (coarse baseline)
        for from_i, to_i, rc in (road_class_details or []):
            urban = rc.lower() in URBAN_ROAD_CLASSES
            for i in range(from_i, min(to_i, n_segs)):
                is_urban[i] = urban

        # Second pass: max_speed overrides (accurate innerorts/außerorts detection).
        # GraphHopper may return numeric values (e.g. 50) or country-specific
        # string designations (e.g. "DE:urban", "DE:rural") — handle both.
        for from_i, to_i, ms in (max_speed_details or []):
            if ms is None:
                continue
            if isinstance(ms, str):
                try:
                    ms_val = float(ms)
                    urban = ms_val <= URBAN_SPEED_THRESHOLD_KMH
                except ValueError:
                    low = ms.lower()
                    if any(k in low for k in ("urban", "living_street", "walk")):
                        urban = True
                    elif any(k in low for k in ("rural", "motorway", "trunk")):
                        urban = False
                    else:
                        continue
            else:
                urban = ms <= URBAN_SPEED_THRESHOLD_KMH
            for i in range(from_i, min(to_i, n_segs)):
                is_urban[i] = urban

        urban_dist = 0.0
        nonurban_dist = 0.0
        unknown_dist = 0.0
        for i in range(n_segs):
            d = _haversine_m(coords[i][0], coords[i][1], coords[i + 1][0], coords[i + 1][1])
            flag = is_urban[i]
            if flag is True:
                urban_dist += d
            elif flag is False:
                nonurban_dist += d
            else:
                unknown_dist += d

        # Distribute unknown segments with the 30/70 urban/rural fallback split
        urban_dist += 0.3 * unknown_dist
        nonurban_dist += 0.7 * unknown_dist

        h = urban_dist / 1000 / speed_urban_kmh + nonurban_dist / 1000 / speed_rural_kmh
    else:
        # No geometry details — fixed 70/30 split
        avg_speed = 0.7 * speed_rural_kmh + 0.3 * speed_urban_kmh
        h = distance_m / 1000 / avg_speed
    return max(1, int(h * 3600))


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
        "details": ["road_class", "max_speed"],
    }

    if road_preference not in _PRIORITY_RULES:
        logger.warning("Unknown road_preference %r, falling back to 'schnell'", road_preference)
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
        payload["ch.disable"] = True

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
            logger.warning("GraphHopper routing error (%s): %s", resp.status_code, detail)
            raise ValueError(f"Routing service error ({resp.status_code})")
        data = resp.json()

    path = data["paths"][0]
    return {
        "distance_m": int(path["distance"]),
        "duration_s": int(path["time"] / 1000),
        "geometry": path["points"],
        "road_class_details": path.get("details", {}).get("road_class", []),
        "max_speed_details": path.get("details", {}).get("max_speed", []),
    }
