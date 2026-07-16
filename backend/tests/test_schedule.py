from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from app.services import schedule as schedule_svc


def _wp(wp_id, hold_min=0):
    return SimpleNamespace(id=wp_id, hold_duration_min=hold_min)


def test_split_duration_by_distance_proportional():
    # Two legs, 20 km and 80 km of a 100 km route → 20 % / 80 % of the drive time.
    durations = schedule_svc.split_duration_by_distance(
        total_duration_s=10_000,
        segment_distances_m=[20_000, 80_000],
        total_distance_m=100_000,
    )
    assert durations == [2_000, 8_000]


def test_split_duration_uses_full_route_distance_not_sum_of_legs():
    # A single waypoint at 40 % of the route must get 40 % of the drive time,
    # not 100 % (the old even split gave 50 % for one waypoint).
    durations = schedule_svc.split_duration_by_distance(
        total_duration_s=18_000,
        segment_distances_m=[48_000],  # 40 % of 120 km
        total_distance_m=120_000,
    )
    assert durations == [7_200]  # 0.4 * 18000


def test_split_duration_even_fallback_when_distance_unknown():
    durations = schedule_svc.split_duration_by_distance(
        total_duration_s=900,
        segment_distances_m=[0.0, 0.0, 0.0],
        total_distance_m=0,
    )
    assert durations == [300, 300, 300]


def test_split_duration_empty():
    assert schedule_svc.split_duration_by_distance(1000, [], 5000) == []


def test_destination_arrival_adds_drive_time_and_holds():
    start = datetime(2026, 7, 16, 6, 0, tzinfo=timezone.utc)
    # 2 h drive + two 15 min holds → 08:30
    arrival = schedule_svc.destination_arrival(
        start, total_duration_s=7_200, waypoints=[_wp("a", 15), _wp("b", 15)]
    )
    assert arrival == start + timedelta(hours=2, minutes=30)


def test_destination_arrival_no_waypoints():
    start = datetime(2026, 7, 16, 6, 0, tzinfo=timezone.utc)
    arrival = schedule_svc.destination_arrival(start, total_duration_s=3_600, waypoints=[])
    assert arrival == start + timedelta(hours=1)


def test_calculate_schedule_cascades_holds():
    start = datetime(2026, 7, 16, 6, 0, tzinfo=timezone.utc)
    wps = [_wp("wp1", 10), _wp("wp2", 0)]
    # Leg 1 = 30 min, leg 2 = 45 min
    schedule = schedule_svc.calculate_schedule(wps, start, [1_800, 2_700])
    # WP1: arrive 06:30, hold 10 min → depart 06:40
    assert schedule[0]["planned_arrival"] == start + timedelta(minutes=30)
    assert schedule[0]["planned_departure"] == start + timedelta(minutes=40)
    # WP2: 06:40 + 45 min = 07:25 (the 10 min hold cascades forward)
    assert schedule[1]["planned_arrival"] == start + timedelta(minutes=85)
    assert schedule[1]["planned_departure"] == start + timedelta(minutes=85)


def test_schedule_and_destination_are_consistent():
    # The destination ETA must equal the last waypoint departure plus the final
    # leg, i.e. start + total drive + all holds — independent of the per-leg split.
    start = datetime(2026, 7, 16, 6, 0, tzinfo=timezone.utc)
    wps = [_wp("wp1", 20)]
    total_drive = 10_000
    # Waypoint at 40 % of a 100 km route.
    seg = schedule_svc.split_duration_by_distance(total_drive, [40_000], 100_000)
    schedule = schedule_svc.calculate_schedule(wps, start, seg)
    dest = schedule_svc.destination_arrival(start, total_drive, wps)
    final_leg = timedelta(seconds=total_drive - seg[0])
    assert schedule[0]["planned_departure"] + final_leg == dest
