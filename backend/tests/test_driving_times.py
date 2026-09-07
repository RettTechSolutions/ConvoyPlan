"""Halte-Empfehlungen: Technische Halte + Lenk- und Ruhezeiten (VO (EG) 561/2006)."""
from app.services.fuel import (
    BREAK_DURATION_MIN,
    DAILY_REST_MIN,
    MAX_CONTINUOUS_DRIVE_S,
    MAX_DAILY_DRIVE_S,
    TH_INTERVAL_S,
    _arrival_window_s,
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
    """Kein Halt faellt in das Ankunftsfenster — gemessen an der Funktion,
    nicht an einer festen Zahl, damit der Test einer Anpassung folgt."""
    for hours in (4.1, 6.4, 12.0, 25.0):
        dur = hours * 3600
        for h in _halts(hours, hours * 63):
            assert h["after_drive_s"] <= dur - _arrival_window_s(dur)


def test_halt_just_inside_the_arrival_window_is_dropped():
    """Bei 4 h 20 min Lenkzeit liegt die 4,5-h-Lenkpause hinter dem Ziel,
    der 4-h-TH aber nur 20 min davor — also im Fenster und damit weg."""
    halts = _halts(4 + 20 / 60, 275)
    assert [h["after_drive_s"] for h in halts] == [2 * 3600]


def test_arrival_window_grows_with_the_march():
    """Eine Stunde vor dem Ziel ist auf einer Tagesfahrt der Endanflug, auf
    einer kurzen Fahrt ein Drittel der Strecke — das Fenster muss mitwachsen."""
    assert _arrival_window_s(3 * 3600) < _arrival_window_s(12 * 3600)


def test_arrival_window_has_a_floor_for_short_marches():
    """Ohne Untergrenze waere das Fenster bei 3 h nur 18 min und die Regel
    praktisch wirkungslos; ein 2-h-TH bleibt dort erhalten."""
    assert _arrival_window_s(3 * 3600) == 30 * 60
    assert [h["after_drive_s"] for h in _halts(3.5, 220)] == [2 * 3600]


def test_arrival_window_is_capped_at_the_th_interval():
    """Halte liegen nie enger als das TH-Intervall. Bleibt das Fenster darunter,
    kann selbst auf einem mehrtaegigen Marsch nur der LETZTE Halt entfallen —
    ungedeckelt waeren es bei 40 h Lenkzeit vier Stunden und damit mehrere."""
    assert _arrival_window_s(40 * 3600) == TH_INTERVAL_S
    for hours in (25.0, 40.0):
        dur = hours * 3600
        halts = _halts(hours, hours * 63)
        # Nach dem letzten Halt bleibt weniger als ein volles TH-Intervall
        # plus Fenster — sonst waere ein weiterer Halt zu Unrecht entfallen.
        assert dur - halts[-1]["after_drive_s"] < TH_INTERVAL_S + _arrival_window_s(dur)


def test_long_march_loses_only_the_final_halt():
    """Regressionsschutz gegen ein zu grosses Fenster: Bei 12 h entfaellt der
    TH eine Stunde vor dem Ziel, alles davor bleibt unangetastet."""
    zeiten = [h["after_drive_s"] // 3600 for h in _halts(12, 760)]
    assert zeiten == [2, 4, 6, 8, 9]


def test_halt_km_increase_monotonically():
    halts = _halts(25, 1600)
    kms = [h["stop_km"] for h in halts]
    assert kms == sorted(kms)
    assert all(0 < k < 1600 for k in kms)
