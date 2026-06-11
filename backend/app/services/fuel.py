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


def project_onto_route(coords: list[list[float]], lat: float, lon: float) -> float:
    """Return metres from route start to the closest projection of (lat, lon) onto the polyline."""
    if not coords:
        return 0.0
    best_along = 0.0
    best_dist = float("inf")
    cumulative = 0.0
    for i in range(len(coords) - 1):
        lon1, lat1 = coords[i]
        lon2, lat2 = coords[i + 1]
        seg_len = haversine_m(lon1, lat1, lon2, lat2)
        dx, dy = lon2 - lon1, lat2 - lat1
        denom = dx * dx + dy * dy
        if denom > 0:
            t = max(0.0, min(1.0, ((lon - lon1) * dx + (lat - lat1) * dy) / denom))
        else:
            t = 0.0
        proj_lon = lon1 + t * dx
        proj_lat = lat1 + t * dy
        d = haversine_m(lon, lat, proj_lon, proj_lat)
        if d < best_dist:
            best_dist = d
            best_along = cumulative + t * seg_len
        cumulative += seg_len
    return best_along


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
    if coords:
        return {"lat": coords[-1][1], "lon": coords[-1][0]}
    return None


DEFAULT_CONSUMPTION_L100KM = 7.5
DEFAULT_TANK_L = 70.0
# E-Fahrzeug-Standardwerte (mittlerer Verbrauch / Akkukapazität)
DEFAULT_CONSUMPTION_KWH_100KM = 20.0
DEFAULT_BATTERY_KWH = 60.0
TECH_STOP_MINUTES_PER_3_VEHICLES = 15

# Technischer Halt rules (THW/Johanniter/DRK standard)
TH_INTERVAL_S = 2 * 3600      # TH every 2 hours of march
TH_TRIGGER_S = 3 * 3600       # recommend TH when march > 3 h
REST_TRIGGER_S = 6 * 3600     # recommend rest when march > 6 h
REST_AT_S = 7 * 3600          # rest around the 7 h mark
REST_DURATION_MIN = 120        # 2 h rest


def tech_stop_duration_min(vehicle_count: int) -> int:
    """15 min per started group of 3 vehicles (1-3 → 15, 4-6 → 30, …)."""
    if vehicle_count <= 0:
        return TECH_STOP_MINUTES_PER_3_VEHICLES
    groups = math.ceil(vehicle_count / 3)
    return groups * TECH_STOP_MINUTES_PER_3_VEHICLES


def _duration_halts(
    route_km: float,
    route_duration_s: float,
    route_coords: list[list[float]],
    vehicle_count: int,
) -> list[dict]:
    """
    Compute recommended Technische Halte based on march duration.

    Rules:
    - March > 3 h: one TH every 2 h of driving
    - March > 6 h: a rest stop (~2 h) around the 7 h mark
    """
    if route_duration_s <= TH_TRIGGER_S:
        return []

    th_min = tech_stop_duration_min(vehicle_count)
    halts: list[dict] = []

    t = TH_INTERVAL_S
    while t < route_duration_s:
        frac = t / route_duration_s
        km = round(frac * route_km, 1)
        is_rest = route_duration_s > REST_TRIGGER_S and t >= REST_AT_S
        dur = REST_DURATION_MIN if is_rest else th_min
        pos = interpolate_along_route(route_coords, km * 1000) if route_coords else None
        halts.append({"stop_km": km, "stop_position": pos, "duration_min": dur, "is_rest": is_rest})
        t += TH_INTERVAL_S

    # If march > 6 h but no halt has hit the REST_AT_S mark yet, insert a separate rest
    if route_duration_s > REST_TRIGGER_S and not any(h["is_rest"] for h in halts):
        if REST_AT_S < route_duration_s:
            frac = REST_AT_S / route_duration_s
            km = round(frac * route_km, 1)
            pos = interpolate_along_route(route_coords, km * 1000) if route_coords else None
            halts.append({"stop_km": km, "stop_position": pos, "duration_min": REST_DURATION_MIN, "is_rest": True})
            halts.sort(key=lambda h: h["stop_km"])

    return halts


def analyse_fuel(
    convoy_vehicles: list[Any],
    route_distance_m: float,
    route_coords: list[list[float]],
    route_duration_s: float = 0,
) -> dict:
    """
    Returns a fuel analysis dict.

    When a vehicle has no fuel data, default values are used
    (DEFAULT_CONSUMPTION_L100KM, DEFAULT_TANK_L) and flagged via
    ``using_defaults=True`` on the range entry.
    """
    route_km = route_distance_m / 1000
    vehicle_count = len(convoy_vehicles)

    # Duration-based TH recommendations (independent of fuel)
    dur_halts = _duration_halts(route_km, route_duration_s, route_coords, vehicle_count)

    ranges = []
    for cv in convoy_vehicles:
        v = cv.vehicle
        electric = getattr(v, "propulsion", "combustion") == "electric"
        if electric:
            energy = v.current_charge_kwh if v.current_charge_kwh is not None else v.battery_capacity_kwh
            cons = v.consumption_kwh_100km
            default_energy, default_cons = DEFAULT_BATTERY_KWH, DEFAULT_CONSUMPTION_KWH_100KM
        else:
            energy = v.current_fuel_l if v.current_fuel_l is not None else v.tank_capacity_l
            cons = v.fuel_consumption_l100km
            default_energy, default_cons = DEFAULT_TANK_L, DEFAULT_CONSUMPTION_L100KM

        if energy and cons and cons > 0:
            range_km = round((energy / cons) * 100, 1)
            using_defaults = False
        else:
            eff_energy = energy if energy else default_energy
            eff_cons = cons if (cons and cons > 0) else default_cons
            range_km = round((eff_energy / eff_cons) * 100, 1)
            using_defaults = True

        ranges.append({
            "name": v.name,
            "callsign": v.callsign,
            "range_km": range_km,
            "using_defaults": using_defaults,
            "propulsion": "electric" if electric else "combustion",
        })

    base = {
        "duration_halt_needed": len(dur_halts) > 0,
        "duration_halts": dur_halts,
        "rest_needed": route_duration_s > REST_TRIGGER_S,
    }

    if not ranges:
        return {
            **base,
            "vehicles_with_range": [],
            "min_range_km": None,
            "route_distance_km": round(route_km, 1),
            "fuel_stop_needed": False,
            "fuel_stop_km": None,
            "fuel_stop_position": None,
            "limiting_vehicle": None,
            "has_default_values": False,
            "vehicles_without_data": 0,
            "recommended_stop_duration_min": None,
        }

    default_count = sum(1 for r in ranges if r["using_defaults"])
    limiting = min(ranges, key=lambda r: r["range_km"])
    min_range = limiting["range_km"]
    stop_needed = min_range < route_km

    stop_km = round(min_range * 0.80, 1) if stop_needed else None
    stop_pos = interpolate_along_route(route_coords, stop_km * 1000) if stop_km else None

    limiting_label = limiting["name"] + (f' ({limiting["callsign"]})' if limiting.get("callsign") else "")
    stop_duration = tech_stop_duration_min(vehicle_count) if stop_needed else None

    return {
        **base,
        "vehicles_with_range": ranges,
        "min_range_km": min_range,
        "route_distance_km": round(route_km, 1),
        "fuel_stop_needed": stop_needed,
        "fuel_stop_km": stop_km,
        "fuel_stop_position": stop_pos,
        "limiting_vehicle": limiting_label,
        # Antriebsart des limitierenden Fahrzeugs, damit das Frontend zwischen
        # „Tankstopp" und „Ladestopp" unterscheiden kann.
        "limiting_propulsion": limiting.get("propulsion", "combustion"),
        "has_default_values": default_count > 0,
        "vehicles_without_data": default_count,
        "recommended_stop_duration_min": stop_duration,
    }
