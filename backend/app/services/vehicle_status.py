"""Shared vehicle-status vocabulary for the live-tracking status panel.

Used by both the authenticated tracking endpoints and the public driver
share-link endpoints so the allowed statuses / sub-levels stay in sync.
"""

# planned | en_route | arrived | technical_halt | breakdown
VALID_VEHICLE_STATUSES: set[str] = {"planned", "en_route", "arrived", "technical_halt", "breakdown"}

# Allowed sub-levels per status. Statuses not listed must not carry a level.
VALID_STATUS_LEVELS: dict[str, set[str]] = {
    "technical_halt": {"standard", "dringend", "sehr_dringend"},
    "breakdown": {"total", "limited"},
}

# Statuses that trigger an in-app alert to the convoy leadership / all clients.
ALERT_STATUSES: set[str] = {"technical_halt", "breakdown"}


def normalize_level(status: str, level: str | None) -> str | None:
    """Return the level if valid for the status, else raise / drop appropriately.

    Drops a stray level for statuses that have no sub-levels; raises ValueError
    when a provided level is not allowed for a status that does have sub-levels.
    """
    allowed = VALID_STATUS_LEVELS.get(status)
    if allowed is None:
        return None
    if level is not None and level not in allowed:
        raise ValueError(f"status_level for {status} must be one of {sorted(allowed)}")
    return level
