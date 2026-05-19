from datetime import datetime, timedelta
from typing import Any


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
