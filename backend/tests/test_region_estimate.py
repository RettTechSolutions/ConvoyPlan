import pytest
from app.services.region_estimate import (
    estimate_ram_bytes, estimate_graph_bytes, estimate_duration_minutes, verdict,
)

GB = 1024 ** 3

@pytest.mark.parametrize("pbf_gb,documented_ram_gb", [(0.7, 3), (4.0, 6), (5.5, 8)])
def test_estimate_matches_documented_installer_values(pbf_gb, documented_ram_gb):
    """Die Schätzung darf die Installer-Angaben nicht unterschreiten."""
    got = estimate_ram_bytes(int(pbf_gb * GB))
    assert got >= documented_ram_gb * GB

def test_estimate_includes_safety_margin():
    """20 % Aufschlag: die rohe Gerade allein reicht nicht."""
    raw = 2 * GB + int(1.1 * 5.5 * GB)
    assert estimate_ram_bytes(int(5.5 * GB)) >= int(raw * 1.2)

def test_verdict_tight_above_80_percent():
    assert verdict(needed=9 * GB, available=10 * GB) == "knapp"

def test_verdict_insufficient_when_over():
    assert verdict(needed=11 * GB, available=10 * GB) == "reicht nicht"

def test_verdict_ok_with_headroom():
    assert verdict(needed=4 * GB, available=10 * GB) == "ok"

# Reale, in Task 1 (Step 1) gemessene Extract-Groessen — siehe Docstring in
# region_estimate.py. Bayern ist mit Abstand die kleinste Stuetzstelle und
# damit die strengste Pruefung fuer die Dauer-Koeffizienten.
BAYERN_BYTES = 850_301_620
GERMANY_BYTES = 4_829_692_709
DACH_BYTES = 6_211_622_102

@pytest.mark.parametrize("pbf_bytes,documented_low,documented_high", [
    (BAYERN_BYTES, 10, 20),
    (GERMANY_BYTES, 45, 90),
    (DACH_BYTES, 60, 120),
])
def test_estimate_duration_never_undershoots_documented_values(pbf_bytes, documented_low, documented_high):
    """Die Dauer-Schätzung darf scripts/install.sh:375 nie unterschreiten.

    Eine zu optimistische Angabe ist schlimmer als eine zu pessimistische,
    weil der Operator danach sein Wartungsfenster plant.
    """
    low, high = estimate_duration_minutes(pbf_bytes)
    assert low >= documented_low
    assert high >= documented_high

def test_estimate_graph_bytes_is_monotonic_and_stays_in_order_of_magnitude():
    """Groesserer Extract -> groesserer Graph, Groessenordnung bleibt beim Extract."""
    small = estimate_graph_bytes(BAYERN_BYTES)
    large = estimate_graph_bytes(DACH_BYTES)
    assert small < large
    assert BAYERN_BYTES <= small <= 3 * BAYERN_BYTES
    assert DACH_BYTES <= large <= 3 * DACH_BYTES

# --- Task 3: Schaetzung ueber mehrere Extracts ---

def test_summe_der_extracts():
    from app.services.region_estimate import sum_extract_bytes
    assert sum_extract_bytes([4 * GB, 2 * GB, 1 * GB]) == 7 * GB

def test_plattenbedarf_beruecksichtigt_alle_gleichzeitig_liegenden_dateien():
    """Waehrend des Wechsels liegen N Quellen, die zusammengefuehrte Datei,
    Staging-Graph, alter Graph und altes Extract gleichzeitig auf der Platte."""
    from app.services.region_estimate import estimate_disk_during_switch
    need = estimate_disk_during_switch([4 * GB, 2 * GB, 1 * GB])
    assert need > 7 * GB * 2   # deutlich mehr als nur Quellen + Merge

def test_sum_extract_bytes_lehnt_leere_liste_ab():
    """Eine leere Auswahl hat keine sinnvolle Groesse — statt stillschweigend
    0 zurueckzugeben (was das Panel als 'passt problemlos' werten wuerde),
    wird ein Fehler ausgeloest."""
    from app.services.region_estimate import sum_extract_bytes
    with pytest.raises(ValueError):
        sum_extract_bytes([])

def test_estimate_disk_during_switch_lehnt_leere_liste_ab():
    from app.services.region_estimate import estimate_disk_during_switch
    with pytest.raises(ValueError):
        estimate_disk_during_switch([])
