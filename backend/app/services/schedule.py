from datetime import datetime, timedelta
from typing import Any


def split_duration_by_distance(
    total_duration_s: int,
    segment_distances_m: list[float],
    total_distance_m: float,
) -> list[int]:
    """Split a total travel time onto legs proportionally to their length.

    Each returned value is the travel time for the corresponding leg, scaled by
    that leg's share of the **whole** route distance (``total_distance_m``) — not
    just the share of the summed leg lengths. That keeps a waypoint's ETA at the
    same fraction of the total drive time as its position along the route, e.g. a
    waypoint at 40 % of the route arrives after 40 % of the driving time.

    Falls back to an even split when the route distance is unknown/zero so a
    schedule is still produced instead of raising.
    """
    if total_distance_m and total_distance_m > 0:
        return [
            max(0, round(total_duration_s * d / total_distance_m))
            for d in segment_distances_m
        ]
    n = len(segment_distances_m)
    return [total_duration_s // n] * n if n else []


def destination_arrival(
    start_time: datetime,
    total_duration_s: int,
    waypoints: list[Any],
) -> datetime:
    """Planned arrival at the final destination (Ziel).

    Equals the departure plus the full driving time plus every waypoint hold,
    which is exactly where the cascaded per-waypoint schedule ends up — the
    destination itself carries no hold.
    """
    total_hold_min = sum(getattr(wp, "hold_duration_min", 0) or 0 for wp in waypoints)
    return start_time + timedelta(seconds=total_duration_s) + timedelta(minutes=total_hold_min)


def calculate_schedule(
    waypoints: list[Any],
    start_time: datetime,
    segment_durations_s: list[int],
) -> list[dict]:
    """
    Calculate planned arrival/departure times for each waypoint.

    waypoints:          ordered list of Waypoint ORM objects
    start_time:         convoy start datetime
    segment_durations_s: travel time in seconds between consecutive points
                         (len = len(waypoints) - 1)
    """
    schedule = []
    current_time = start_time

    for i, wp in enumerate(waypoints):
        # segment_durations_s[i] = travel time from previous point (start or last wp) to this wp
        current_time += timedelta(seconds=segment_durations_s[i])

        arrival = current_time
        departure = arrival + timedelta(minutes=wp.hold_duration_min)
        current_time = departure

        schedule.append(
            {
                "waypoint_id": wp.id,
                "planned_arrival": arrival,
                "planned_departure": departure,
            }
        )

    return schedule
