import json
import os

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
