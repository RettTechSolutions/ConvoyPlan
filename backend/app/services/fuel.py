"""Fuel analysis: calculates minimum convoy range and interpolates the stop position."""
import math
from typing import Any


def haversine_m(lon1: float, lat1: float, lon2: float, lat2: float) -> float:
    R = 6_371_000
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def interpolate_along_route(coords: list[list[float]], target_m: float) -> dict[str, float] | None:
    """Return {lat, lon} at exactly target_m metres along the GeoJSON coord list."""
    accumulated = 0.0
    for i in range(len(coords) - 1):
        lon1, lat1 = coords[i]
        lon2, lat2 = coords[i + 1]
        seg = haversine_m(lon1, lat1, lon2, lat2)
        if accumulated + seg >= target_m:
            frac = (target_m - accumulated) / seg if seg > 0 else 0.0
            return {
                "lat": lat1 + frac * (lat2 - lat1),
                "lon": lon1 + frac * (lon2 - lon1),
            }
        accumulated += seg
    # target beyond route end → return last point
    if coords:
        return {"lat": coords[-1][1], "lon": coords[-1][0]}
    return None


def analyse_fuel(
    convoy_vehicles: list[Any],
    route_distance_m: float,
    route_coords: list[list[float]],
) -> dict:
    """
    Returns a fuel analysis dict:
      - vehicles_with_range: list of {name, range_km}
      - min_range_km: minimum range across convoy (None if no data)
      - route_distance_km: total route length
      - fuel_stop_needed: bool
      - fuel_stop_km: distance along route where stop is recommended (at 80 % of min range)
      - fuel_stop_position: {lat, lon} or None
      - limiting_vehicle: name of the vehicle with shortest range
    """
    route_km = route_distance_m / 1000

    ranges = []
    for cv in convoy_vehicles:
        v = cv.vehicle
        fuel = v.current_fuel_l if v.current_fuel_l is not None else v.tank_capacity_l
        cons = v.fuel_consumption_l100km
        if fuel and cons and cons > 0:
            ranges.append({"name": v.name, "callsign": v.callsign, "range_km": round((fuel / cons) * 100, 1)})

    if not ranges:
        return {
            "vehicles_with_range": [],
            "min_range_km": None,
            "route_distance_km": round(route_km, 1),
            "fuel_stop_needed": False,
            "fuel_stop_km": None,
            "fuel_stop_position": None,
            "limiting_vehicle": None,
        }

    limiting = min(ranges, key=lambda r: r["range_km"])
    min_range = limiting["range_km"]
    stop_needed = min_range < route_km

    # Place stop at 80 % of min range (safety margin)
    stop_km = round(min_range * 0.80, 1) if stop_needed else None
    stop_pos = interpolate_along_route(route_coords, stop_km * 1000) if stop_km else None

    return {
        "vehicles_with_range": ranges,
        "min_range_km": min_range,
        "route_distance_km": round(route_km, 1),
        "fuel_stop_needed": stop_needed,
        "fuel_stop_km": stop_km,
        "fuel_stop_position": stop_pos,
        "limiting_vehicle": limiting["name"] + (f' ({limiting["callsign"]})' if limiting.get("callsign") else ""),
    }
