"""Tests for the feedback-review fixes:

- demo accounts may not change password / enable MFA
- recommended Technische Halte appended to the end of the waypoint list are
  re-ordered by their projection onto the route (the ~700 km detour bug)
"""
import uuid
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

def _wp(lat, lon, order_index):
    """Minimal stand-in for a Waypoint with coordinates and an order_index."""
    wp = MagicMock()
    wp.id = uuid.uuid4()
    wp.order_index = order_index
    wp._lat = lat
    wp._lon = lon
    return wp


def test_appended_halt_is_reordered_by_route_projection():
    """A halt appended to the end of the list but physically in the middle of
    the route must sort into the middle when projected onto the route geometry.

    Mirrors calculate_route's pre-routing ordering: without it the router would
    visit the appended halt last and detour back, inflating the distance."""
    # Straight west->east route along latitude 50.0 from lon 8 to lon 12.
    route_coords = [[8.0, 50.0], [9.0, 50.0], [10.0, 50.0], [11.0, 50.0], [12.0, 50.0]]

    # Two real waypoints near the start/end and a halt added "at the end" of the
    # list (highest order_index) that actually lies in the middle (lon 10).
    wp_early = _wp(50.0, 9.0, order_index=0)
    wp_late = _wp(50.0, 11.0, order_index=1)
    halt_middle = _wp(50.0, 10.0, order_index=2)  # appended last

    waypoints = [wp_early, wp_late, halt_middle]
    ordered = sorted(
        waypoints, key=lambda w: project_onto_route(route_coords, w._lat, w._lon)
    )

    assert [w._lon for w in ordered] == [9.0, 10.0, 11.0]
    # The appended halt ends up in the middle, not last.
    assert ordered[1] is halt_middle


def test_projection_is_monotonic_along_route():
    route_coords = [[8.0, 50.0], [12.0, 50.0]]
    d_start = project_onto_route(route_coords, 50.0, 8.5)
    d_mid = project_onto_route(route_coords, 50.0, 10.0)
    d_end = project_onto_route(route_coords, 50.0, 11.5)
    assert d_start < d_mid < d_end
