"""Tests for the feedback-review fixes:

- demo accounts may not change password / enable MFA
- recommended Technische Halte appended to the end of the waypoint list are
  slotted into the route by projection (the ~700 km detour bug). Die
  Einordnung selbst steht in ``test_wegpunkt_reihenfolge.py``; hier bleibt nur
  die Eigenschaft, auf der sie beruht.
"""
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException

from app.api.routes.auth import _reject_demo_user
from app.services.fuel import project_onto_route


# ── Demo account security guard ────────────────────────────────────────────────

def test_reject_demo_user_blocks_demo_account():
    user = MagicMock()
    user.is_demo = True
    with pytest.raises(HTTPException) as exc:
        _reject_demo_user(user)
    assert exc.value.status_code == 403


def test_reject_demo_user_allows_regular_account():
    user = MagicMock()
    user.is_demo = False
    # Should not raise.
    _reject_demo_user(user)


def test_reject_demo_user_allows_when_flag_missing():
    # A plain object without an is_demo attribute is treated as non-demo.
    class _U:
        pass
    _reject_demo_user(_U())


# ── March-order / Technische-Halt projection ───────────────────────────────────

def test_projection_is_monotonic_along_route():
    route_coords = [[8.0, 50.0], [12.0, 50.0]]
    d_start = project_onto_route(route_coords, 50.0, 8.5)
    d_mid = project_onto_route(route_coords, 50.0, 10.0)
    d_end = project_onto_route(route_coords, 50.0, 11.5)
    assert d_start < d_mid < d_end


# ── Electric vehicle range ─────────────────────────────────────────────────────

def _cv(**vehicle_attrs):
    v = MagicMock()
    # sensible defaults so unrelated fields don't interfere
    for f in ("current_fuel_l", "tank_capacity_l", "fuel_consumption_l100km",
              "current_charge_kwh", "battery_capacity_kwh", "consumption_kwh_100km"):
        setattr(v, f, None)
    v.propulsion = "combustion"
    v.name = "KFZ"
    v.callsign = None
    for k, val in vehicle_attrs.items():
        setattr(v, k, val)
    cv = MagicMock()
    cv.vehicle = v
    return cv


def test_electric_vehicle_range_uses_kwh():
    from app.services.fuel import analyse_fuel
    # 60 kWh / 20 kWh/100km -> 300 km
    ev = _cv(propulsion="electric", current_charge_kwh=60.0, consumption_kwh_100km=20.0, name="E-LKW")
    result = analyse_fuel([ev], route_distance_m=100_000, route_coords=[[8.0, 50.0], [9.0, 50.0]])
    assert result["vehicles_with_range"][0]["range_km"] == 300.0
    assert result["vehicles_with_range"][0]["propulsion"] == "electric"


def test_electric_vehicle_triggers_charging_stop_propulsion():
    from app.services.fuel import analyse_fuel
    # 20 kWh / 20 kWh/100km -> 100 km range, route 250 km -> stop needed
    ev = _cv(propulsion="electric", current_charge_kwh=20.0, consumption_kwh_100km=20.0, name="E-LKW")
    result = analyse_fuel([ev], route_distance_m=250_000, route_coords=[[8.0, 50.0], [12.0, 50.0]])
    assert result["fuel_stop_needed"] is True
    assert result["limiting_propulsion"] == "electric"


def test_combustion_range_unchanged():
    from app.services.fuel import analyse_fuel
    # 70 L / 7 L/100km -> 1000 km
    car = _cv(current_fuel_l=70.0, fuel_consumption_l100km=7.0, name="MTW")
    result = analyse_fuel([car], route_distance_m=100_000, route_coords=[[8.0, 50.0], [9.0, 50.0]])
    assert result["vehicles_with_range"][0]["range_km"] == 1000.0
    assert result["vehicles_with_range"][0]["propulsion"] == "combustion"
