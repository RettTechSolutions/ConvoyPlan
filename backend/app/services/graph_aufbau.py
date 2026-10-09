"""Baut GraphHopper gerade seine Straßenkarte? — abgelesen an den Volumes.

Das Backend sieht keine Container (kein Docker-Socket), aber es hat ``gh_graph``
und ``osm_data`` lesend gemountet, und ``graphhopper/entrypoint.sh`` hinterlässt
dort eindeutige Spuren:

- ``<osm>.tmp`` in ``/data/osm``: der Entrypoint lädt das Extract herunter.
  ``curl`` schreibt fortlaufend hinein, eine frische Änderungszeit belegt also,
  dass der Download *läuft* — eine liegengebliebene Datei aus einem
  abgebrochenen Container ist bald alt.
- ``.graph_fingerprint`` **ohne** ``edges`` in ``/data/graph``: der Fingerprint
  wird unmittelbar *vor* dem Import geschrieben, ``edges`` legt GraphHopper erst
  bei einem vollständigen Graphen an. Dazwischen läuft der Import, und die
  Änderungszeit des Fingerprints ist sein Beginn.

Für den zweiten Fall gibt es keinen Lebensbeweis — der Import hält den Graphen
im Heap (``RAM_STORE``) und schreibt bis zum Schluss nichts. Ein Container, der
mitten im Import gestoppt wurde und nicht wiederkommt, ließe dieselben Spuren
zurück. Gedeckelt wird deshalb mit derselben Frist wie im Updater
(``GH_IMPORT_GRACE`` in ``graphhopper-deploy.sh``): was nach vier Stunden noch
„baut", baut nicht mehr, und dann wäre die Aussage „wird aufgebaut" eine
Ausrede für einen echten Ausfall.

Die Entscheidung steht hier ohne Bezug zur Statusroute und wird von
``tests/test_graph_aufbau.py`` gegen echte Dateien im Temp-Verzeichnis geprüft.
"""
import os
import time
from dataclasses import dataclass

GRAPH_DIR = "/data/graph"
OSM_DIR = "/data/osm"

FINGERPRINT = ".graph_fingerprint"
EDGES = "edges"

#: Wie lange ein Import höchstens als laufend gilt. Gleich ``GH_IMPORT_GRACE``.
IMPORT_FRIST_S = 4 * 3600
#: Wie alt die letzte Änderung an der Download-Datei höchstens sein darf.
DOWNLOAD_STILLSTAND_S = 10 * 60


@dataclass(frozen=True)
class Aufbau:
    phase: str  # "download" | "import" | "haengt" (nur graph_zustand)
    #: Beginn als Unix-Zeit — nur beim Import bekannt. Beim Download gibt der
    #: Mount keinen Erstellzeitpunkt her (ctime ändert sich mit jedem Schreiben).
    seit: float | None


def _mtime(path: str) -> float | None:
    try:
        return os.stat(path).st_mtime
    except OSError:
        return None


def _laufender_download(osm_dir: str, jetzt: float) -> Aufbau | None:
    try:
        namen = os.listdir(osm_dir)
    except OSError:
        return None
    for name in namen:
        if not name.endswith(".osm.pbf.tmp"):
            continue
        pfad = os.path.join(osm_dir, name)
        geaendert = _mtime(pfad)
        if geaendert is not None and jetzt - geaendert <= DOWNLOAD_STILLSTAND_S:
            return Aufbau("download", None)
    return None


def graph_zustand(
    graph_dir: str = GRAPH_DIR,
    osm_dir: str = OSM_DIR,
    jetzt: float | None = None,
) -> Aufbau | None:
    """Download, Import oder ein Import über der Frist („haengt"); sonst ``None``.

    Die dritte Phase ist für das Admin-Panel: Wer die Instanz betreibt, soll
    sehen, dass ein Import nicht fertig geworden ist. Die öffentliche Seite
    fragt :func:`laufender_aufbau` und meldet dann schlicht einen Ausfall.
    """
    jetzt = time.time() if jetzt is None else jetzt

    download = _laufender_download(osm_dir, jetzt)
    if download is not None:
        return download

    if os.path.exists(os.path.join(graph_dir, EDGES)):
        return None
    beginn = _mtime(os.path.join(graph_dir, FINGERPRINT))
    if beginn is None:
        return None
    if jetzt - beginn > IMPORT_FRIST_S:
        return Aufbau("haengt", beginn)
    return Aufbau("import", beginn)


def laufender_aufbau(
    graph_dir: str = GRAPH_DIR,
    osm_dir: str = OSM_DIR,
    jetzt: float | None = None,
) -> Aufbau | None:
    """Download oder Import, falls einer läuft; sonst ``None``."""
    zustand = graph_zustand(graph_dir, osm_dir, jetzt)
    if zustand is None or zustand.phase == "haengt":
        return None
    return zustand
