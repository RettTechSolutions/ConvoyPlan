import json
import os
from datetime import datetime, timezone

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


# ── Wartungsmodus und Terminierung ──────────────────────────────────────────


def test_write_request_schreibt_wartungsmodus_und_termin_als_strings(tmp_path, monkeypatch):
    """Der Updater liest die Datei ohne python3/jq (docker:cli-Image) und ist
    auf flache String-Werte ausgelegt — deshalb "1" statt true und die
    Epoch-Sekunden als Zeichenkette. Ausserdem stehen dort ZWEI Zeitangaben:
    der ISO-Stempel fuers Panel und die Epoch-Sekunden fuer die Shell, deren
    busybox-`date` ISO-8601 mit Offset nicht verlaesslich parst."""
    monkeypatch.setattr(region_switch, "VOLUME", str(tmp_path))
    wann = datetime(2099, 3, 1, 2, 30, tzinfo=timezone.utc)
    region_switch.write_request(
        url="https://download.geofabrik.de/europe/dach-latest.osm.pbf",
        filename="dach-latest.osm.pbf",
        java_opts="-Xmx14g",
        actor_email="admin@example.org",
        pause_routing=True,
        scheduled_for=wann,
    )
    data = json.loads((tmp_path / "region_request.json").read_text())
    assert data["pause_routing"] == "1"
    assert data["scheduled_for"] == wann.isoformat()
    assert data["scheduled_for_epoch"] == str(int(wann.timestamp()))
    assert isinstance(data["scheduled_for_epoch"], str)


def test_write_request_ohne_termin_schreibt_keine_terminfelder(tmp_path, monkeypatch):
    """Der Normalfall bleibt unveraendert: Ohne Termin liegen die Felder gar
    nicht erst in der Datei, und region-hook.sh behandelt die Anforderung als
    sofort faellig."""
    monkeypatch.setattr(region_switch, "VOLUME", str(tmp_path))
    region_switch.write_request("https://download.geofabrik.de/e-latest.osm.pbf",
                                "e-latest.osm.pbf", "-Xmx4g", "a@b.c")
    data = json.loads((tmp_path / "region_request.json").read_text())
    assert "scheduled_for" not in data
    assert "scheduled_for_epoch" not in data
    assert data["pause_routing"] == ""


def test_read_status_meldet_geplant_statt_wartend(tmp_path, monkeypatch):
    """Ein geplanter Wechsel liegt womoeglich Stunden da. Als `queued`
    gemeldet zeigte das Panel dauerhaft "wartet auf den Updater", und der
    Operator hielte das fuer eine Stoerung."""
    monkeypatch.setattr(region_switch, "VOLUME", str(tmp_path))
    wann = datetime(2099, 3, 1, 2, 30, tzinfo=timezone.utc)
    region_switch.write_request("https://download.geofabrik.de/e-latest.osm.pbf",
                                "e-latest.osm.pbf", "-Xmx4g", "a@b.c",
                                pause_routing=True, scheduled_for=wann)
    status = region_switch.read_status()
    assert status["phase"] == "scheduled"
    assert status["scheduled_for"] == wann.isoformat()
    assert status["pause_routing"] is True


def test_read_status_meldet_wartend_wenn_kein_termin_gesetzt_ist(tmp_path, monkeypatch):
    """Gegenprobe: Ohne Termin bleibt es beim bisherigen `queued`."""
    monkeypatch.setattr(region_switch, "VOLUME", str(tmp_path))
    region_switch.write_request("https://download.geofabrik.de/e-latest.osm.pbf",
                                "e-latest.osm.pbf", "-Xmx4g", "a@b.c")
    assert region_switch.read_status()["phase"] == "queued"


def test_read_status_haelt_sich_ans_lock_auch_bei_geplantem_wechsel(tmp_path, monkeypatch):
    """Sobald der Updater zugreift, zaehlt sein Status — auch wenn in der
    Anforderung noch ein Termin steht. Sonst zeigte das Panel "geplant",
    waehrend der Wechsel laengst laeuft."""
    monkeypatch.setattr(region_switch, "VOLUME", str(tmp_path))
    region_switch.write_request("https://download.geofabrik.de/e-latest.osm.pbf",
                                "e-latest.osm.pbf", "-Xmx4g", "a@b.c",
                                scheduled_for=datetime(2099, 3, 1, tzinfo=timezone.utc))
    (tmp_path / "region.lock").write_text("")
    (tmp_path / "region_status.json").write_text(
        json.dumps({"phase": "importing", "message": "Baue Routing-Graph…"}))
    assert region_switch.read_status()["phase"] == "importing"
