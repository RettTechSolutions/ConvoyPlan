import logging
import re
from math import asin, cos, radians, sin, sqrt
from typing import Any

import httpx

from app.config import settings

logger = logging.getLogger(__name__)


class RoutingOutOfBoundsError(ValueError):
    """A start-, waypoint- or end point lies outside the loaded map area.

    GraphHopper hält aus Ressourcengründen nur ein OSM-Extract vor — per
    Voreinstellung DACH (DE, AT, CH, LI), konfigurierbar über
    ``OSM_DOWNLOAD_URL``. Liegt ein Punkt außerhalb dieser Bounding-Box, lehnt
    GraphHopper die Anfrage mit „Point N is out of bounds/range" ab. Wir fangen
    das ab, um im Frontend eine verständliche Meldung statt der rohen
    Koordinaten zu zeigen.

    ``point_index`` ist der 0-basierte Index aus der GraphHopper-Meldung
    (0 = Start, letzter = Ziel, dazwischen = Wegpunkte) — soweit ermittelbar.
    """

    def __init__(self, point_index: int | None = None) -> None:
        self.point_index = point_index
        super().__init__("Point outside covered map area")

URBAN_ROAD_CLASSES = {"residential", "living_street", "service"}
URBAN_SPEED_THRESHOLD_KMH = 50  # posted limit ≤ this → innerorts

# Three simple modes:
#   standard  — avoids built-up areas where possible and prefers the
#               best-developed road available (Autobahn/B-Straße before
#               Kreisstraße before Ortsdurchfahrt)
#   schnell   — fastest route, GraphHopper default weighting
#   kuerzeste — shortest route by distance
# Legacy values from older convoys are mapped onto the new modes.
_LEGACY_PREFERENCES = {
    "bundesstrasse": "standard",
    "landstrasse": "standard",
}

_PRIORITY_RULES: dict[str, list[dict[str, str]]] = {
    "schnell": [],
    "kuerzeste": [],
    "standard": [
        # Prefer well-developed roads: mild penalty for Kreisstraßen so
        # PRIMARY/SECONDARY win when roughly comparable, but TERTIARY stays
        # usable as a connector.
        {"if": "road_class == TERTIARY", "multiply_by": "0.6"},
        # Avoid built-up areas: penalise residential streets, but not so hard
        # that the router detours via unclassified/track roads instead — many
        # B roads pass through town centres tagged residential in OSM.
        {"if": "road_class == RESIDENTIAL || road_class == LIVING_STREET", "multiply_by": "0.3"},
        # Convoy-unsuitable road classes must always be more expensive than
        # any penalised main road, otherwise they become cheap workarounds.
        {"if": "road_class == UNCLASSIFIED", "multiply_by": "0.25"},
        {"if": "road_class == SERVICE", "multiply_by": "0.1"},
        {"if": "road_class == TRACK", "multiply_by": "0.01"},
    ],
}

# Cost per km added to the edge weight ("kuerzeste" mode). GraphHopper's
# default is ~70; a high value makes distance dominate travel time so the
# route approximates the shortest path without using footpath-grade roads.
_SHORTEST_DISTANCE_INFLUENCE = 300


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

    road_preference = _LEGACY_PREFERENCES.get(road_preference, road_preference)
    if road_preference not in _PRIORITY_RULES:
        logger.warning("Unknown road_preference %r, falling back to 'schnell'", road_preference)
        road_preference = "schnell"
    priority_rules = list(_PRIORITY_RULES[road_preference])

    custom_model: dict[str, Any] = {}
    if vehicle_params and "max_height_m" in vehicle_params:
        custom_model["priority"] = [
            {"if": f"max_height < {vehicle_params['max_height_m']}", "multiply_by": "0"},
            *priority_rules,
        ]
    elif priority_rules:
        custom_model["priority"] = priority_rules

    if road_preference == "kuerzeste":
        custom_model["distance_influence"] = _SHORTEST_DISTANCE_INFLUENCE

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
            msg = str(detail)
            lower = msg.lower()
            # Punkt außerhalb der geladenen Kartendaten (Standard: DACH)
            # — GraphHopper: „Point N is out of bounds/range" bzw. „Cannot find
            # point N". Dedizierter Fehler für eine verständliche Frontend-Meldung.
            if "out of bounds" in lower or "out of range" in lower or "cannot find point" in lower:
                m = re.search(r"point\s+(\d+)", lower)
                raise RoutingOutOfBoundsError(int(m.group(1)) if m else None)
            raise ValueError(f"Routing service error ({resp.status_code}): {msg[:300]}")
        data = resp.json()

    path = data["paths"][0]
    return {
        "distance_m": int(path["distance"]),
        "duration_s": int(path["time"] / 1000),
        "geometry": path["points"],
        "road_class_details": path.get("details", {}).get("road_class", []),
        "max_speed_details": path.get("details", {}).get("max_speed", []),
    }
