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
