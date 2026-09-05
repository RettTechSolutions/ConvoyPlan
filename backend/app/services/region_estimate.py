"""Ressourcenschätzung für einen Regionswechsel.

Stützstellen sind die in scripts/install.sh:375 dokumentierten Werte:
Bayern >= 3 GB, Deutschland >= 6 GB, DACH >= 8 GB. Die Extract-Groessen
dazu stammen aus Task 1, Step 1 (HTTP-HEAD gegen Geofabrik, gemessen am
2026-09-03):

    europe/dach                  6.211.622.102 Bytes (5,79 GB)
    europe/germany               4.829.692.709 Bytes (4,50 GB)
    europe/germany/bayern          850.301.620 Bytes (0,79 GB)
    europe/germany/berlin           99.143.742 Bytes (0,09 GB)
    europe                      34.885.514.453 Bytes (32,49 GB)

Gegenprobe der Formel `(2 GB + 1,1 * Extract) * 1,2` (Grundlast + Steigung,
danach 20 % Sicherheitsaufschlag) gegen die drei belegten Stuetzstellen:

    Bayern (0,79 GB):     (2 + 1,1*0,79) * 1,2 = 3,44 GB  >= 3 GB  (Installer)
    Deutschland (4,50 GB):(2 + 1,1*4,50) * 1,2 = 8,34 GB  >= 6 GB  (Installer)
    DACH (5,79 GB):       (2 + 1,1*5,79) * 1,2 = 10,04 GB >= 8 GB  (Installer)

Alle drei Testfaelle bestehen mit den urspruenglich angenommenen Koeffizienten
(_BASE_BYTES = 2 GB, _PER_PBF_BYTE = 1,1) — eine Anpassung war nicht noetig,
die gemessenen Groessen stuetzen die Formel.

Dauer-Koeffizienten (_MINUTES_PER_GB_LOW / _MINUTES_PER_GB_HIGH), Herleitung
aus denselben drei Stuetzstellen gegen die dokumentierten Dauern
(scripts/install.sh:375: Bayern 10-20 min, Deutschland 45-90 min, DACH
60-120 min). Dokumentierte Minuten je GB Extract, mit den gemessenen
Groessen von oben:

    Bayern (0,79 GB):      10/0,79 = 12,63 min/GB (untere Grenze)
                            20/0,79 = 25,26 min/GB (obere Grenze)
    Deutschland (4,50 GB): 45/4,50 = 10,00 min/GB
                            90/4,50 = 20,00 min/GB
    DACH (5,79 GB):        60/5,79 = 10,37 min/GB
                           120/5,79 = 20,74 min/GB

Die Verhaeltnisse fallen mit wachsender Extract-Groesse (fixe Grundlast wie
JVM-Start und Indizierung faellt bei kleinen Extracts staerker ins Gewicht).
Eine einzige Gerade durch den Ursprung trifft daher nicht alle drei Punkte
exakt — sie muss sich an der kleinsten, strengsten Stuetzstelle (Bayern)
ausrichten. Eine zu optimistische Dauerangabe ist schlimmer als eine zu
pessimistische, weil der Operator danach sein Wartungsfenster plant: die
Koeffizienten werden deshalb auf den Bayern-Quotienten aufgerundet, nicht
gemittelt. Das ergibt 13 min/GB (untere Grenze) und 26 min/GB (obere Grenze).
Damit unterschreitet keine der drei Stuetzstellen die Installer-Angabe;
Deutschland und DACH werden dadurch bewusst grosszuegig (konservativ)
geschaetzt, was laut Spec Abschnitt 6 der sicherere Fehler ist.
"""

GB = 1024 ** 3

_BASE_BYTES = 2 * GB          # JVM, Betriebssystem, GraphHopper-Grundlast
_PER_PBF_BYTE = 1.1           # Steigung der Geraden durch die drei Stuetzstellen
_SAFETY_MARGIN = 1.2          # 20 % Aufschlag (Spec Abschnitt 6)
_MINUTES_PER_GB_LOW = 13   # aufgerundeter Bayern-Quotient 12,63 min/GB (strengste Stuetzstelle)
_MINUTES_PER_GB_HIGH = 26  # aufgerundeter Bayern-Quotient 25,26 min/GB (strengste Stuetzstelle)
_TIGHT_THRESHOLD = 0.8


def estimate_ram_bytes(pbf_bytes: int) -> int:
    """Geschaetzter Heap-Bedarf des Imports, inklusive Sicherheitsaufschlag."""
    raw = _BASE_BYTES + int(_PER_PBF_BYTE * pbf_bytes)
    return int(raw * _SAFETY_MARGIN)


def estimate_graph_bytes(pbf_bytes: int) -> int:
    """Der gebaute Graph liegt erfahrungsgemaess in der Groessenordnung des Extracts."""
    return int(pbf_bytes * 1.5)


def estimate_duration_minutes(pbf_bytes: int) -> tuple[int, int]:
    gb = pbf_bytes / GB
    return (max(1, int(gb * _MINUTES_PER_GB_LOW)), max(2, int(gb * _MINUTES_PER_GB_HIGH)))


def verdict(needed: int, available: int) -> str:
    """'ok' | 'knapp' | 'reicht nicht' — die Einstufung fuer das Panel."""
    if needed > available:
        return "reicht nicht"
    if needed > available * _TIGHT_THRESHOLD:
        return "knapp"
    return "ok"


# ── Zusammengesetzte Regionen ───────────────────────────────────────────────
# Mehrere Geofabrik-Extracts werden zu einer Karte verschmolzen. Die Funktionen
# oben rechnen mit EINER Groesse; die beiden hier fassen die Bestandteile
# zusammen, bevor sie dort hineingehen.

_STAGING_GRAPH_FACTOR = 1.5   # der gebaute Graph im Staging, Erfahrungswert wie oben


def sum_extract_bytes(sizes: list[int]) -> int:
    """Summe der Bestandteile einer zusammengesetzten Region.

    Die Ueberlappung im Grenzstreifen wird bewusst NICHT abgezogen. Der
    Machbarkeits-Spike mass 0,67 % zwischen Sachsen und Niederschlesien, aber
    dieser Anteil haengt von Laenge und Zuschnitt der gemeinsamen Grenze ab —
    zwischen Deutschland und Frankreich faellt er anders aus als zwischen
    Deutschland und Daenemark. Eine Ueberschaetzung ist hier der sichere
    Fehler: Sie fuehrt hoechstens dazu, dass das Panel eine Kombination als
    knapp meldet, die gerade noch gepasst haette.
    """
    if not sizes:
        raise ValueError("Keine Region ausgewählt — es gibt nichts zu schätzen.")
    return sum(sizes)


def estimate_disk_during_switch(sizes: list[int]) -> int:
    """Spitzenbedarf auf der Platte waehrend eines Wechsels.

    Gleichzeitig liegen dort: die N heruntergeladenen Quelldateien, die daraus
    zusammengefuehrte Datei (etwa die Summe), der im Staging gebaute Graph
    (etwa das 1,5-fache) sowie der alte Graph und das alte Extract, die bis
    nach dem Health-Check aufgehoben werden. Die letzten beiden sind hier
    unbekannt — als Naeherung wird die Summe noch einmal veranschlagt.

    Ergibt zusammen das 4,5-fache der Quellsumme; fuer Deutschland + Polen +
    Tschechien (~7 GB) also rund 32 GB.
    """
    total = sum_extract_bytes(sizes)
    merged = total
    staging_graph = int(total * _STAGING_GRAPH_FACTOR)
    alter_bestand = total
    return total + merged + staging_graph + alter_bestand
