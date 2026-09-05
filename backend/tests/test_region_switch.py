import json
import os

import pytest

from app.services import region_switch


def test_write_request_creates_readable_json(tmp_path, monkeypatch):
    monkeypatch.setattr(region_switch, "VOLUME", str(tmp_path))
    region_switch.write_request(
        url="https://download.geofabrik.de/europe/dach-latest.osm.pbf",
        filename="dach-latest.osm.pbf",
        java_opts="-Xmx8g -Xms1g -XX:+UseG1GC",
        actor_email="admin@example.org",
    )
    data = json.loads((tmp_path / "region_request.json").read_text())
    assert data["url"].endswith("dach-latest.osm.pbf")
    assert data["java_opts"] == "-Xmx8g -Xms1g -XX:+UseG1GC"
    assert data["requested_by"] == "admin@example.org"
    assert "requested_at" in data


def test_is_busy_true_while_request_pending(tmp_path, monkeypatch):
    monkeypatch.setattr(region_switch, "VOLUME", str(tmp_path))
    assert region_switch.is_busy() is False
    region_switch.write_request("https://download.geofabrik.de/e-latest.osm.pbf",
                                "e-latest.osm.pbf", "-Xmx4g", "a@b.c")
    assert region_switch.is_busy() is True


def test_read_status_defaults_to_idle(tmp_path, monkeypatch):
    monkeypatch.setattr(region_switch, "VOLUME", str(tmp_path))
    assert region_switch.read_status()["phase"] == "idle"


def test_read_status_defaults_to_idle_on_broken_json(tmp_path, monkeypatch):
    monkeypatch.setattr(region_switch, "VOLUME", str(tmp_path))
    (tmp_path / region_switch.STATUS_FILE).write_text("{kaputtes json")
    assert region_switch.read_status()["phase"] == "idle"


def test_is_busy_true_while_lock_held(tmp_path, monkeypatch):
    monkeypatch.setattr(region_switch, "VOLUME", str(tmp_path))
    assert region_switch.is_busy() is False
    (tmp_path / region_switch.LOCK_FILE).write_text("locked")
    assert region_switch.is_busy() is True


def test_write_request_leaves_no_temp_file_behind(tmp_path, monkeypatch):
    monkeypatch.setattr(region_switch, "VOLUME", str(tmp_path))
    region_switch.write_request("https://download.geofabrik.de/e-latest.osm.pbf",
                                "e-latest.osm.pbf", "-Xmx4g", "a@b.c")
    remaining = os.listdir(tmp_path)
    assert set(remaining) == {region_switch.LOG_FILE, region_switch.REQUEST_FILE}
    assert not any(name.startswith(".tmp-") for name in remaining)


def test_write_request_second_call_raises_and_first_survives(tmp_path, monkeypatch):
    """Belegt die Exklusivität aus Fix-Runde 1 zu Task 5: eine zweite,
    gleichzeitige Anforderung darf die erste niemals stillschweigend
    überschreiben, sondern muss mit FileExistsError scheitern."""
    monkeypatch.setattr(region_switch, "VOLUME", str(tmp_path))
    region_switch.write_request(
        url="https://download.geofabrik.de/europe/dach-latest.osm.pbf",
        filename="dach-latest.osm.pbf",
        java_opts="-Xmx8g",
        actor_email="first@example.org",
    )

    with pytest.raises(FileExistsError):
        region_switch.write_request(
            url="https://download.geofabrik.de/europe/berlin-latest.osm.pbf",
            filename="berlin-latest.osm.pbf",
            java_opts="-Xmx3g",
            actor_email="second@example.org",
        )

    # Die zuerst geschriebene Anforderung bleibt unveraendert erhalten.
    data = json.loads((tmp_path / region_switch.REQUEST_FILE).read_text())
    assert data["requested_by"] == "first@example.org"
    assert data["filename"] == "dach-latest.osm.pbf"

    # Kein Leichnam der gescheiterten zweiten Anforderung im Volume.
    remaining = os.listdir(tmp_path)
    assert not any(name.startswith(".tmp-") for name in remaining)


def _write_request(tmp_path):
    region_switch.write_request(
        "https://download.geofabrik.de/europe/poland-latest.osm.pbf",
        "poland-latest.osm.pbf", "-Xmx6g", "a@b.c",
    )


def test_read_status_meldet_wartend_solange_der_updater_nicht_zugreift(tmp_path, monkeypatch):
    """Der Befund aus dem Betrieb: Nach dem Klick sah der Operator nicht, dass
    ein Wechsel laeuft. Zwischen dem Schreiben der Anforderung und dem Moment,
    in dem der Updater sie aufgreift, liegt sein Poll-Intervall — und in dieser
    Zeit gab es nur die Statusdatei, die noch nichts von diesem Wechsel weiss.
    """
    monkeypatch.setattr(region_switch, "VOLUME", str(tmp_path))
    _write_request(tmp_path)
    status = region_switch.read_status()
    assert status["phase"] == "queued"
    assert status["message"] == region_switch.QUEUED_MESSAGE
    # Zeitstempel kommt aus der Anforderung selbst, damit das Panel zeigen kann,
    # seit wann gewartet wird.
    assert status["at"]


def test_read_status_zeigt_nicht_das_ergebnis_des_vorigen_wechsels(tmp_path, monkeypatch):
    """Der irrefuehrendere Teil desselben Fehlers: Lag noch ein 'done' des
    VORIGEN Wechsels in der Statusdatei, meldete der Endpunkt es weiter — das
    Panel behauptete 'Abgeschlossen' ueber einem gerade erst angestossenen
    Wechsel."""
    monkeypatch.setattr(region_switch, "VOLUME", str(tmp_path))
    (tmp_path / region_switch.STATUS_FILE).write_text(
        json.dumps({"phase": "done", "message": "Regionswechsel abgeschlossen"})
    )
    assert region_switch.read_status()["phase"] == "done"   # vorher: zu Recht
    _write_request(tmp_path)
    assert region_switch.read_status()["phase"] == "queued"  # nachher: wartend


def test_read_status_haelt_sich_ans_lock_sobald_der_updater_arbeitet(tmp_path, monkeypatch):
    """Sobald das Lock liegt, arbeitet der Updater und SEIN Status gilt — die
    Anforderungsdatei liegt waehrend des ganzen Laufs weiter im Volume und darf
    den echten Fortschritt nicht ueberdecken."""
    monkeypatch.setattr(region_switch, "VOLUME", str(tmp_path))
    _write_request(tmp_path)
    (tmp_path / region_switch.LOCK_FILE).write_text("")
    (tmp_path / region_switch.STATUS_FILE).write_text(
        json.dumps({"phase": "importing", "message": "Baue Routing-Graph"})
    )
    assert region_switch.read_status()["phase"] == "importing"


def test_read_status_ohne_anforderung_unveraendert(tmp_path, monkeypatch):
    """Regressionsschutz: Ohne wartende Anforderung bleibt alles wie bisher."""
    monkeypatch.setattr(region_switch, "VOLUME", str(tmp_path))
    assert region_switch.read_status()["phase"] == "idle"
    (tmp_path / region_switch.STATUS_FILE).write_text(json.dumps({"phase": "failed"}))
    assert region_switch.read_status()["phase"] == "failed"
