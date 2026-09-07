"""Halte-Empfehlungen: Technische Halte + Lenk- und Ruhezeiten (VO (EG) 561/2006)."""
from app.services.fuel import (
    BREAK_DURATION_MIN,
    DAILY_REST_MIN,
    MAX_CONTINUOUS_DRIVE_S,
    MAX_DAILY_DRIVE_S,
    _duration_halts,
)


def _halts(hours: float, km: float, vehicles: int = 3):
    return _duration_halts(km, hours * 3600, [], vehicles)


def test_short_march_has_no_halts():
    assert _halts(2.5, 160) == []


def test_th_every_two_hours_until_first_break():
    halts = _halts(5, 320)
    assert [h["kind"] for h in halts] == ["tech", "break"]
    assert halts[0]["duration_min"] == 15
    assert halts[1]["duration_min"] == BREAK_DURATION_MIN


def test_break_never_exceeds_max_continuous_drive_time():
    halts = _halts(25, 1600)
    last_break_at = 0
    for h in halts:
        assert h["after_drive_s"] - last_break_at <= MAX_CONTINUOUS_DRIVE_S
        if h["kind"] in ("break", "daily_rest"):
            last_break_at = h["after_drive_s"]


def test_daily_rest_after_nine_hours_of_driving():
    halts = _halts(25, 1600)
    rests = [h for h in halts if h["kind"] == "daily_rest"]
    assert rests, "Bei 25 h Lenkzeit muss mindestens eine Tagesruhezeit kommen"
    assert all(h["duration_min"] == DAILY_REST_MIN for h in rests)
    last_rest_at = 0
    for h in halts:
        assert h["after_drive_s"] - last_rest_at <= MAX_DAILY_DRIVE_S
        if h["kind"] == "daily_rest":
            last_rest_at = h["after_drive_s"]


def test_no_two_hour_rest_spam_on_long_marches():
    """Regression: frueher wurde ab 7 h jeder 2-h-Halt zur 2-h-Rast."""
    halts = _halts(25, 1600)
    rests = [h for h in halts if h["kind"] == "daily_rest"]
    # 25 h Lenkzeit -> hoechstens drei Tagesruhezeiten, nicht ein Dutzend
    assert len(rests) <= 3
    assert sum(1 for h in halts if h["kind"] == "tech") >= len(rests)


def test_long_tech_stop_counts_as_break():
    """9 Fahrzeuge -> 45 min TH, das erfuellt die Lenkzeitunterbrechung."""
    halts = _halts(10, 640, vehicles=9)
    tech = [h for h in halts if h["kind"] == "tech"]
    assert tech and all(h["duration_min"] == 45 for h in tech)
    assert all(h["covers_break"] for h in tech)
    assert not [h for h in halts if h["kind"] == "break"]


def test_no_halt_right_before_arrival():
    halts = _halts(4.1, 260)
    assert all(h["after_drive_s"] <= 4.1 * 3600 - 15 * 60 for h in halts)


def test_halt_km_increase_monotonically():
    halts = _halts(25, 1600)
    kms = [h["stop_km"] for h in halts]
    assert kms == sorted(kms)
    assert all(0 < k < 1600 for k in kms)
