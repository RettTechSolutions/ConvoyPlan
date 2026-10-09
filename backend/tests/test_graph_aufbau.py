"""Erkennung eines laufenden Kartenaufbaus an den Spuren des GraphHopper-Entrypoints.

Echte Dateien im Temp-Verzeichnis, keine Mocks: die Entscheidung hängt an
Existenz und Änderungszeit, und genau die soll der Test anfassen.
"""
import os
import time

from app.services import graph_aufbau
from app.services.graph_aufbau import Aufbau, graph_zustand, laufender_aufbau

JETZT = 1_800_000_000.0


def _datei(pfad, alter_s: float = 0.0):
    pfad.write_text("x")
    os.utime(pfad, (JETZT - alter_s, JETZT - alter_s))


def _dirs(tmp_path):
    graph, osm = tmp_path / "graph", tmp_path / "osm"
    graph.mkdir()
    osm.mkdir()
    return graph, osm


def _frage(graph, osm):
    return laufender_aufbau(str(graph), str(osm), jetzt=JETZT)


def test_fertiger_graph_ist_kein_aufbau(tmp_path):
    graph, osm = _dirs(tmp_path)
    _datei(graph / ".graph_fingerprint")
    _datei(graph / "edges")

    assert _frage(graph, osm) is None


def test_fingerprint_ohne_edges_ist_ein_laufender_import(tmp_path):
    """Der Fingerprint entsteht vor dem Import, edges erst an seinem Ende."""
    graph, osm = _dirs(tmp_path)
    _datei(graph / ".graph_fingerprint", alter_s=600)

    assert _frage(graph, osm) == Aufbau("import", JETZT - 600)


def test_import_ueber_der_frist_gilt_nicht_mehr_als_laufend(tmp_path):
    """Ein gestoppter Container hinterlässt dieselben Spuren — nach der Frist
    wäre „wird aufgebaut" eine Ausrede für einen echten Ausfall."""
    graph, osm = _dirs(tmp_path)
    _datei(graph / ".graph_fingerprint", alter_s=graph_aufbau.IMPORT_FRIST_S + 1)

    assert _frage(graph, osm) is None


def test_leeres_graphverzeichnis_ist_kein_aufbau(tmp_path):
    graph, osm = _dirs(tmp_path)

    assert _frage(graph, osm) is None


def test_frischer_download_wird_erkannt(tmp_path):
    graph, osm = _dirs(tmp_path)
    _datei(osm / "dach-latest.osm.pbf.tmp", alter_s=5)

    assert _frage(graph, osm) == Aufbau("download", None)


def test_liegengebliebener_download_zaehlt_nicht(tmp_path):
    graph, osm = _dirs(tmp_path)
    _datei(osm / "dach-latest.osm.pbf.tmp", alter_s=graph_aufbau.DOWNLOAD_STILLSTAND_S + 1)

    assert _frage(graph, osm) is None


def test_fehlende_mounts_sind_kein_aufbau(tmp_path):
    """Altinstallationen ohne die lesenden Mounts: keine Aussage, kein Fehler."""
    assert laufender_aufbau(str(tmp_path / "fehlt"), str(tmp_path / "auch"), jetzt=JETZT) is None


def test_ohne_zeitangabe_gilt_die_uhr(tmp_path):
    graph, osm = _dirs(tmp_path)
    (graph / ".graph_fingerprint").write_text("x")

    aufbau = laufender_aufbau(str(graph), str(osm))
    assert aufbau is not None and aufbau.phase == "import"
    assert abs(aufbau.seit - time.time()) < 60


def test_admin_sieht_den_haengenden_import(tmp_path):
    """Öffentlich ist er ein Ausfall — wer betreibt, soll sehen, dass ein Import
    nicht fertig wurde, und seit wann."""
    graph, osm = _dirs(tmp_path)
    alter = graph_aufbau.IMPORT_FRIST_S + 60
    _datei(graph / ".graph_fingerprint", alter_s=alter)

    assert graph_zustand(str(graph), str(osm), jetzt=JETZT) == Aufbau("haengt", JETZT - alter)
    assert _frage(graph, osm) is None


def test_admin_und_oeffentlich_sind_sich_bei_laufendem_import_einig(tmp_path):
    graph, osm = _dirs(tmp_path)
    _datei(graph / ".graph_fingerprint", alter_s=60)

    assert graph_zustand(str(graph), str(osm), jetzt=JETZT) == _frage(graph, osm)
