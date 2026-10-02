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
    assert BAYERN_BYTES // 2 <= small <= 3 * BAYERN_BYTES
    assert DACH_BYTES // 2 <= large <= 3 * DACH_BYTES


# Gemessen am 2026-10-02 auf der gehosteten Instanz (siehe Docstring in
# region_estimate.py): 8,5 GB Extracts ergaben einen Graphen von 4,9 GB.
GEMESSEN_EXTRACT = int(8.5 * GB)
GEMESSEN_GRAPH = int(4.9 * GB)


def test_graph_schaetzung_unterschreitet_die_messung_nicht():
    """Die Plattenrechnung darf nicht optimistischer sein als die Wirklichkeit."""
    assert estimate_graph_bytes(GEMESSEN_EXTRACT) >= GEMESSEN_GRAPH


def test_graph_schaetzung_bleibt_in_der_naehe_der_messung():
    """Und nicht wieder das Zweieinhalbfache davon, wie mit dem alten Faktor 1,5."""
    assert estimate_graph_bytes(GEMESSEN_EXTRACT) <= 1.5 * GEMESSEN_GRAPH


# --- Arbeitsspeicher: dieselbe Schwelle wie der Updater ---

def test_rohbedarf_ist_der_bedarf_ohne_aufschlag():
    """Der Updater rechnet aus dem angeforderten -Xmx mit `* 10 / 12` zurueck
    (switch-region.sh, _raw_need_mb). Beide Seiten muessen dieselbe Zahl haben."""
    from app.services.region_estimate import estimate_ram_raw_bytes
    for pbf in (BAYERN_BYTES, DACH_BYTES, int(9.5 * GB)):
        mit = estimate_ram_bytes(pbf)
        assert abs(mit * 10 // 12 - estimate_ram_raw_bytes(pbf)) <= 1


def test_ram_reicht_nicht_erst_wenn_der_rohbedarf_nicht_passt():
    from app.services.region_estimate import HEAP_RESERVE_BYTES, estimate_ram_raw_bytes, ram_verdict
    pbf = int(9.5 * GB)
    knapp_daneben = estimate_ram_raw_bytes(pbf) + HEAP_RESERVE_BYTES - 1
    assert ram_verdict(pbf, knapp_daneben) == "reicht nicht"


def test_ram_im_aufschlag_ist_knapp_und_nicht_gesperrt():
    """Der Fall vom 2026-10-02: 16-GB-Server, rund 14 GB frei, Erweiterung auf
    9,5 GB Extracts. Mit Aufschlag ~15 GB, ohne ~12,5 GB — der Updater fuehrt
    das aus, also darf das Panel es nicht sperren."""
    from app.services.region_estimate import ram_verdict
    assert ram_verdict(int(9.5 * GB), int(14 * GB)) == "knapp"


def test_ram_mit_luft_ist_ok():
    from app.services.region_estimate import ram_verdict
    assert ram_verdict(BAYERN_BYTES, int(16 * GB)) == "ok"


def test_ram_zieht_die_reserve_des_updaters_ab():
    """Passt der Bedarf mit Aufschlag genau in den freien Speicher, aber nicht
    mehr nach Abzug der Reserve, ist das nicht "ok"."""
    from app.services.region_estimate import ram_verdict
    pbf = DACH_BYTES
    assert ram_verdict(pbf, estimate_ram_bytes(pbf)) != "ok"

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


def test_reserve_ist_dieselbe_wie_im_updater():
    """Panel und Updater ziehen dieselbe Reserve ab — sonst sperrt das eine,
    was das andere ausfuehrt, oder umgekehrt."""
    import re
    from pathlib import Path
    from app.services.region_estimate import HEAP_RESERVE_BYTES
    skript = Path(__file__).resolve().parents[2] / "docker" / "updater" / "switch-region.sh"
    m = re.search(r'REGION_HEAP_RESERVE_MB="\$\{REGION_HEAP_RESERVE_MB:-(\d+)\}"', skript.read_text())
    assert m, "Vorgabe von REGION_HEAP_RESERVE_MB in switch-region.sh nicht gefunden"
    assert HEAP_RESERVE_BYTES == int(m.group(1)) * 1024 ** 2
