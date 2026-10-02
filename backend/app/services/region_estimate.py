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

Erste Messung an einer echten Instanz (2026-10-02, gehostete Instanz,
zusammengesetzte Region aus DACH, Italien, Slowenien, Kroatien, Montenegro und
Albanien, 8,5 GB Extracts, ein Profil `car` mit CH): der fertige Graph belegt
4,9 GB, also das 0,58-fache des Extracts — nicht das 1,5-fache, mit dem die
Plattenrechnung bis dahin lief. `_GRAPH_FACTOR` steht seitdem auf 0,75: die
Messung plus Luft fuer weitere Profile, aber nicht mehr doppelt so viel wie
gemessen. Den Heap-Bedarf belegt die Messung nur nach unten (mit RAM_STORE
muss der Graph in den Heap passen); die Gerade oben bleibt deshalb, bis
`gc+heap+exit` aus graphhopper/entrypoint.sh echte Hoechststaende liefert.

Ein Import am Rand des Aufschlags
---------------------------------
Das Panel stufte bis 2026-10 mit dem Bedarf INKLUSIVE der 20 % ein und
sperrte den Wechsel, sobald der nicht in den freien Speicher passte. Der
Updater prueft dagegen den Rohbedarf (switch-region.sh, `_raw_need_mb`,
`_heap_shortfall_mb`) gegen den freien Speicher abzueglich seiner Reserve —
und liess Wechsel durch, die das Panel gar nicht erst abschickte. Auf 16 GB
traf das genau die Erweiterung von 8,5 auf 9,5 GB: rund 15 GB mit Aufschlag,
rund 12,5 GB ohne, frei rund 13 GB. `ram_verdict` rechnet deshalb wie der
Updater: „reicht nicht" erst, wenn der Rohbedarf nicht passt; passt er nur
ohne den Aufschlag, ist es „knapp".
"""

GB = 1024 ** 3

_BASE_BYTES = 2 * GB          # JVM, Betriebssystem, GraphHopper-Grundlast
_PER_PBF_BYTE = 1.1           # Steigung der Geraden durch die drei Stuetzstellen
_SAFETY_MARGIN = 1.2          # 20 % Aufschlag (Spec Abschnitt 6)
_MINUTES_PER_GB_LOW = 13   # aufgerundeter Bayern-Quotient 12,63 min/GB (strengste Stuetzstelle)
_MINUTES_PER_GB_HIGH = 26  # aufgerundeter Bayern-Quotient 25,26 min/GB (strengste Stuetzstelle)
_TIGHT_THRESHOLD = 0.8
_GRAPH_FACTOR = 0.75          # gemessen 0,58 (siehe Docstring), plus Luft
# Dieselbe Reserve, die der Updater vom freien Speicher abzieht, bevor er den
# Heap deckelt (REGION_HEAP_RESERVE_MB in docker/updater/switch-region.sh).
HEAP_RESERVE_BYTES = 1024 * 1024 ** 2


def estimate_ram_raw_bytes(pbf_bytes: int) -> int:
    """Heap-Bedarf des Imports OHNE Sicherheitsaufschlag — darunter ist er aussichtslos."""
    return _BASE_BYTES + int(_PER_PBF_BYTE * pbf_bytes)


def estimate_ram_bytes(pbf_bytes: int) -> int:
    """Geschaetzter Heap-Bedarf des Imports, inklusive Sicherheitsaufschlag.

    Das ist auch der Wert, den das Backend als -Xmx anfordert; der Updater
    rechnet daraus mit `* 10 / 12` den Rohbedarf zurueck.
    """
    return int(estimate_ram_raw_bytes(pbf_bytes) * _SAFETY_MARGIN)


def estimate_graph_bytes(pbf_bytes: int) -> int:
    """Der gebaute Graph, gemessen bei etwa dem 0,6-fachen des Extracts (siehe Docstring)."""
    return int(pbf_bytes * _GRAPH_FACTOR)


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


def ram_verdict(pbf_bytes: int, available: int) -> str:
    """Einstufung des Arbeitsspeichers — mit derselben Schwelle wie der Updater.

    `available` ist der freie Speicher samt dem, was der Wartungsmodus
    zurueckgewinnt. Davon geht die Reserve des Updaters ab; was bleibt, ist
    der Heap, den der Updater dem Import hoechstens gibt. „Reicht nicht" heisst
    dann: auch der Rohbedarf passt nicht, der Updater braeche ab. Passt nur der
    Aufschlag nicht, laeuft der Import mit gedeckeltem Heap — eng, aber nicht
    aussichtslos (Begruendung im Modul-Docstring).
    """
    usable = available - HEAP_RESERVE_BYTES
    if estimate_ram_raw_bytes(pbf_bytes) > usable:
        return "reicht nicht"
    if estimate_ram_bytes(pbf_bytes) > usable:
        return "knapp"
    return verdict(estimate_ram_bytes(pbf_bytes), usable)


# ── Zusammengesetzte Regionen ───────────────────────────────────────────────
# Mehrere Geofabrik-Extracts werden zu einer Karte verschmolzen. Die Funktionen
# oben rechnen mit EINER Groesse; die beiden hier fassen die Bestandteile
# zusammen, bevor sie dort hineingehen.

_STAGING_GRAPH_FACTOR = _GRAPH_FACTOR   # der gebaute Graph im Staging, wie oben


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
    (`_GRAPH_FACTOR`) sowie der alte Graph und das alte Extract, die bis
    nach dem Health-Check aufgehoben werden. Die letzten beiden sind hier
    unbekannt — als Naeherung wird die Summe noch einmal veranschlagt.

    Ergibt zusammen das 3,75-fache der Quellsumme; fuer Deutschland + Polen +
    Tschechien (~7 GB) also rund 26 GB.
    """
    total = sum_extract_bytes(sizes)
    merged = total
    staging_graph = int(total * _STAGING_GRAPH_FACTOR)
    alter_bestand = total
    return total + merged + staging_graph + alter_bestand
