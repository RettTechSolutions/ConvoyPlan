"""Zusammensetzung mehrerer Geofabrik-Regionen zu einer Karte.

Der Kern ist der Hash: Er wandert in den Dateinamen der zusammengefuehrten
Datei, und `graphhopper/entrypoint.sh:90` bildet den Fingerprint aus genau
diesem Namen. Dadurch erkennt der bestehende Mechanismus aus #420 einen
Wechsel der Zusammensetzung, ohne dass hier etwas Eigenes noetig waere.

Die Sortierung ist keine Kosmetik: Ohne sie ergaeben "DE, PL" und "PL, DE"
verschiedene Hashes und damit einen ueberfluessigen, stundenlangen Neubau.
"""
import hashlib

_SEP = "|"


def compose_hash(paths: list[str]) -> str:
    """Acht Zeichen aus der sortierten Bestandteilsliste."""
    joined = _SEP.join(sorted(paths))
    return hashlib.sha256(joined.encode()).hexdigest()[:8]


def merged_filename(paths: list[str]) -> str:
    return f"merged-{compose_hash(paths)}.osm.pbf"


def sources_value(paths: list[str]) -> str:
    """Der Wert fuer OSM_SOURCES in `.region` — sortiert, |-getrennt."""
    return _SEP.join(sorted(paths))


def parse_sources(value: str) -> list[str]:
    if not value.strip():
        return []
    return sorted(p for p in value.split(_SEP) if p)


def overlapping(paths: list[str]) -> list[tuple[str, str]]:
    """Paare (Oberregion, Unterregion) — erlaubt, aber verschwenderisch.

    osmium merge dedupliziert das korrekt; der Operator laedt dann aber
    Daten doppelt herunter und wartet laenger als noetig.
    """
    out = []
    for a in sorted(paths):
        for b in sorted(paths):
            if a != b and b.startswith(a + "/"):
                out.append((a, b))
    return out
