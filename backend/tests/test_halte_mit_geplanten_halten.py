"""Halte-Empfehlung rechnet mit den Halten, die schon als Wegpunkt stehen.

Gemeldet: Ein Technischer Halt wurde wenige Kilometer hinter einem bereits
eingeplanten Tankhalt vorgeschlagen — zwei Stopps kurz hintereinander. Ein
geplanter Halt zählt jetzt wie ein TH, ein TH kurz davor geht in ihm auf,
und ein übernommener Vorschlag verschwindet aus der Liste.
"""
from app.services.fuel import (
    BREAK_DURATION_MIN,
    HALT_MERGE_WINDOW_S,
    TH_INTERVAL_S,
    _duration_halts,
    analyse_fuel,
)

# 64 km/h Marschgeschwindigkeit: 1 h Lenkzeit = 64 km
KMH = 64


def _km(stunden: float) -> float:
    return stunden * KMH


def _halts(stunden: float, geplant=(), fahrzeuge: int = 3):
    return _duration_halts(_km(stunden), stunden * 3600, [], fahrzeuge, list(geplant))


def test_ohne_geplante_halte_unveraendert():
    assert [h["kind"] for h in _halts(5)] == ["tech", "break"]


def test_th_kurz_vor_tankhalt_geht_in_ihm_auf():
    """Der gemeldete Fall: TH bei 2:00, Tankhalt bei 2:10 → kein eigener TH."""
    tankhalt_km = _km(2 + 10 / 60)
    halts = _halts(5, [(tankhalt_km, 20)])
    assert not [h for h in halts if h["kind"] == "tech" and abs(h["stop_km"] - tankhalt_km) < _km(0.5)]
    # Die Lenkpause bleibt fällig — ein 20-min-Tankhalt ersetzt sie nicht.
    assert [h["kind"] for h in halts] == ["break"]


def test_th_kurz_nach_tankhalt_entfaellt_ebenfalls():
    """Der Tankhalt kommt vor dem fälligen TH: das Intervall läuft danach neu an."""
    tankhalt_km = _km(1 + 50 / 60)
    halts = _halts(6, [(tankhalt_km, 20)])
    tech = [h for h in halts if h["kind"] == "tech"]
    assert all(h["after_drive_s"] >= (1 + 50 / 60) * 3600 + TH_INTERVAL_S - 1 for h in tech)


def test_geplanter_halt_weit_hinter_dem_th_ersetzt_ihn_nicht():
    """Liegt der geplante Halt mehr als das Fenster hinter dem TH, bleibt der TH."""
    spaeter = 2 + (HALT_MERGE_WINDOW_S + 15 * 60) / 3600
    halts = _halts(5, [(_km(spaeter), 20)])
    assert halts[0]["kind"] == "tech"
    assert halts[0]["after_drive_s"] == TH_INTERVAL_S


def test_frueher_geplanter_halt_verschiebt_das_intervall():
    halts = _halts(5, [(_km(1), 15)])
    assert halts[0]["after_drive_s"] == 3 * 3600


def test_lenkpause_kurz_nach_geplantem_halt_wird_an_ihn_gelegt():
    """Früher ist bei Lenkzeiten immer zulässig: die Pause rückt an den Halt."""
    halt_bei = 4 + 10 / 60
    halts = _halts(8, [(_km(2), 15), (_km(halt_bei), 20)])
    pausen = [h for h in halts if h["kind"] == "break"]
    assert pausen[0]["stop_km"] == round(_km(halt_bei), 1)
    assert pausen[0]["duration_min"] == BREAK_DURATION_MIN
    # und kein zweiter Stopp kurz dahinter
    danach = [h for h in halts if h["after_drive_s"] > halt_bei * 3600]
    assert all(h["after_drive_s"] - halt_bei * 3600 >= TH_INTERVAL_S - 1 for h in danach)


def test_langer_geplanter_halt_ersetzt_die_lenkpause():
    halts = _halts(5, [(_km(2), 15), (_km(4), BREAK_DURATION_MIN)])
    assert halts == []


def test_uebernommene_vorschlaege_verschwinden_aus_der_liste():
    """Jeder Vorschlag als Wegpunkt übernommen → nichts mehr zu empfehlen."""
    for stunden, fahrzeuge in [(5, 3), (10, 9), (25, 3), (14, 6)]:
        vorschlaege = _halts(stunden, fahrzeuge=fahrzeuge)
        assert vorschlaege
        uebernommen = [(h["stop_km"], h["duration_min"]) for h in vorschlaege]
        assert _halts(stunden, uebernommen, fahrzeuge) == [], (stunden, fahrzeuge)


def test_teilweise_uebernommen_laesst_den_rest_stehen():
    vorschlaege = _halts(25)
    erster = vorschlaege[0]
    rest = _halts(25, [(erster["stop_km"], erster["duration_min"])])
    assert rest == vorschlaege[1:]


def test_analyse_reicht_geplante_halte_durch():
    route_km = _km(5)
    ohne = analyse_fuel([], route_km * 1000, [], route_duration_s=5 * 3600)
    mit = analyse_fuel([], route_km * 1000, [], route_duration_s=5 * 3600,
                       geplante_halte=[(_km(2), 15), (_km(4), BREAK_DURATION_MIN)])
    assert ohne["duration_halt_needed"] is True
    assert mit["duration_halt_needed"] is False
    assert mit["duration_halts"] == []
