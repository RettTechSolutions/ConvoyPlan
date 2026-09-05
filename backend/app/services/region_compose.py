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


def normalize(paths: list[str]) -> list[str]:
    """Sortiert und ENTDOPPELT — die kanonische Form der Bestandteilsliste.

    Die Sortierung verhindert, dass "DE, PL" und "PL, DE" verschiedene Hashes
    und damit einen ueberfluessigen Neubau ergeben. Die Entdopplung verhindert
    Schlimmeres: Waehlt jemand dieselbe Region zweimal aus, entstuende sonst
    `sources="a|a"`, der Updater lud dieselbe Datei zweimal unter denselben
    Namen und `osmium merge` fuehrte sie mit sich selbst zusammen. Das Ergebnis
    ist formal gueltig und faellt durch keine Groessenpruefung — es waere eine
    Karte, die zwei Regionen behauptet und eine enthaelt.
    """
    return sorted(set(paths))


def compose_hash(paths: list[str]) -> str:
    """Acht Zeichen aus der kanonischen Bestandteilsliste."""
    joined = _SEP.join(normalize(paths))
    return hashlib.sha256(joined.encode()).hexdigest()[:8]


def merged_filename(paths: list[str]) -> str:
    return f"merged-{compose_hash(paths)}.osm.pbf"


def sources_value(paths: list[str]) -> str:
    """Der Wert fuer OSM_SOURCES in `.region` — kanonisch, |-getrennt."""
    return _SEP.join(normalize(paths))


def parse_sources(value: str) -> list[str]:
    if not value.strip():
        return []
    return normalize([p for p in value.split(_SEP) if p])


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


def path_from_url(url: str) -> str:
    """Geofabrik-URL -> Regionspfad ohne Schema und Suffix.

    `https://download.geofabrik.de/europe/germany-latest.osm.pbf`
      -> `europe/germany`

    Die Umkehrung von dem, was das Panel schickt: Es kennt Pfade (aus dem
    Index), die API bekommt URLs. Fuer den Hash und fuer OSM_SOURCES brauchen
    wir wieder die Pfade — kuerzer, stabiler und unabhaengig davon, ob die URL
    spaeter einmal anders zusammengesetzt wird.
    """
    path = url.split("://", 1)[-1]
    path = path.split("/", 1)[-1] if "/" in path else path
    if path.endswith("-latest.osm.pbf"):
        path = path[: -len("-latest.osm.pbf")]
    return path.lstrip("/")
