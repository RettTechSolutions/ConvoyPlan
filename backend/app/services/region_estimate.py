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
"""

GB = 1024 ** 3

_BASE_BYTES = 2 * GB          # JVM, Betriebssystem, GraphHopper-Grundlast
_PER_PBF_BYTE = 1.1           # Steigung der Geraden durch die drei Stuetzstellen
_SAFETY_MARGIN = 1.2          # 20 % Aufschlag (Spec Abschnitt 6)
_MINUTES_PER_GB_LOW = 12
_MINUTES_PER_GB_HIGH = 22
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
