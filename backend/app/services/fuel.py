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

# Technischer Halt (THW/Johanniter/DRK-Standard)
TH_INTERVAL_S = 2 * 3600      # TH alle 2 h Marschzeit
TH_TRIGGER_S = 3 * 3600       # TH-Empfehlung ab 3 h Marschdauer

# Lenk- und Ruhezeiten in Anlehnung an VO (EG) 561/2006
MAX_CONTINUOUS_DRIVE_S = int(4.5 * 3600)   # max. 4,5 h Lenkzeit am Stück
BREAK_DURATION_MIN = 45                    # 45 min Lenkzeitunterbrechung
MAX_DAILY_DRIVE_S = 9 * 3600               # max. 9 h Tageslenkzeit
DAILY_REST_MIN = 11 * 60                   # 11 h Tagesruhezeit

# Ab dieser Lenkzeit ist mindestens eine Lenkpause fällig
REST_TRIGGER_S = MAX_CONTINUOUS_DRIVE_S
# Halte, vor denen weniger als diese Restlenkzeit liegt, entfallen. Formal
# genuegten 15 min, praktisch legt kein Verband kurz vor dem Ziel noch eine
# WOLKE-Pruefung ein — der Halt waere am Ziel ohnehin faellig.
MIN_REMAINING_S = 30 * 60
# Fällt ein Halt in dieses Fenster vor einem höherwertigen Halt, werden beide
# zu einem einzigen Halt verschmolzen (statt zwei Stopps kurz hintereinander).
HALT_MERGE_WINDOW_S = 30 * 60
# Sicherheitsnetz gegen Endlosschleifen bei absurd langen Routen
MAX_HALTS = 100

HALT_KIND_TECH = "tech"
HALT_KIND_BREAK = "break"
HALT_KIND_DAILY_REST = "daily_rest"


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
    Simuliert die Marschzeit und leitet daraus die empfohlenen Halte ab.

    Regeln (Lenkzeiten in Anlehnung an VO (EG) 561/2006):
    - Marschdauer > 3 h: alle 2 h Lenkzeit ein Technischer Halt (WOLKE-Prüfung)
    - Nach spätestens 4,5 h Lenkzeit am Stück: 45 min Lenkzeitunterbrechung
    - Nach spätestens 9 h Tageslenkzeit: 11 h Tagesruhezeit

    ``route_duration_s`` ist reine Fahrzeit, die Haltezeiten selbst zählen
    also nicht in die Lenkzeit hinein. Ein Halt, der ohnehin mindestens
    45 min dauert (große Verbände), gilt als vollwertige
    Lenkzeitunterbrechung und setzt die Lenkzeit zurück.
    """
    if route_duration_s <= TH_TRIGGER_S:
        return []

    th_min = tech_stop_duration_min(vehicle_count)
    halts: list[dict] = []

    driven = 0.0            # gesamte bisher gefahrene Lenkzeit
    since_break = 0.0       # Lenkzeit seit der letzten Unterbrechung
    since_rest = 0.0        # Tageslenkzeit seit der letzten Tagesruhezeit
    next_th = float(TH_INTERVAL_S)

    while len(halts) < MAX_HALTS:
        to_th = next_th - driven
        to_break = MAX_CONTINUOUS_DRIVE_S - since_break
        to_rest = MAX_DAILY_DRIVE_S - since_rest
        step = min(to_th, to_break, to_rest)
        if step <= 0:
            break

        driven += step
        since_break += step
        since_rest += step

        # Kein Halt mehr kurz vor dem Ziel
        if driven > route_duration_s - MIN_REMAINING_S:
            break

        # Halte, die dicht beieinander liegen, zu einem Halt zusammenfassen
        due_rest = to_rest - step <= HALT_MERGE_WINDOW_S
        due_break = to_break - step <= HALT_MERGE_WINDOW_S

        covers_break = True
        if due_rest:
            kind = HALT_KIND_DAILY_REST
            duration = DAILY_REST_MIN
            since_rest = 0.0
            since_break = 0.0
        elif due_break:
            kind = HALT_KIND_BREAK
            duration = max(BREAK_DURATION_MIN, th_min)
            since_break = 0.0
        else:
            kind = HALT_KIND_TECH
            duration = th_min
            # Ein ohnehin langer TH erfüllt die Lenkzeitunterbrechung mit
            covers_break = th_min >= BREAK_DURATION_MIN
            if covers_break:
                since_break = 0.0
        # Nach jedem Halt läuft das TH-Intervall neu an
        next_th = driven + TH_INTERVAL_S

        frac = driven / route_duration_s
        km = round(frac * route_km, 1)
        pos = interpolate_along_route(route_coords, km * 1000) if route_coords else None
        halts.append({
            "stop_km": km,
            "stop_position": pos,
            "duration_min": duration,
            "kind": kind,
            "is_rest": kind != HALT_KIND_TECH,
            "after_drive_s": int(driven),
            "covers_break": covers_break,
        })

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
