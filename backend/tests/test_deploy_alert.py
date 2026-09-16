"""deploy_alert: marker parsing and email rendering (no DB / no network)."""
import json

import app.services.deploy_alert as da


def test_read_alert_missing_file(monkeypatch, tmp_path):
    monkeypatch.setattr(da, "ALERT_FILE", str(tmp_path / "nope.json"))
    assert da._read_alert() is None


def test_read_alert_valid(monkeypatch, tmp_path):
    p = tmp_path / "deploy_alert.json"
    p.write_text(json.dumps({"id": "abc", "event": "deploy_rolled_back", "detail": "x"}))
    monkeypatch.setattr(da, "ALERT_FILE", str(p))
    alert = da._read_alert()
    assert alert is not None and alert["id"] == "abc"


def test_read_alert_malformed_is_none(monkeypatch, tmp_path):
    p = tmp_path / "deploy_alert.json"
    p.write_text("{not json")
    monkeypatch.setattr(da, "ALERT_FILE", str(p))
    assert da._read_alert() is None


def test_read_alert_without_id_is_none(monkeypatch, tmp_path):
    p = tmp_path / "deploy_alert.json"
    p.write_text(json.dumps({"event": "deploy_failed"}))
    monkeypatch.setattr(da, "ALERT_FILE", str(p))
    assert da._read_alert() is None


def test_render_rollback_includes_detail_and_images():
    subject, body = da._render_alert(
        {
            "id": "1",
            "event": "deploy_rolled_back",
            "at": "2026-07-17T10:00:00Z",
            "failed_image": "backend:beta",
            "restored_image": "backend:nightly",
            "detail": "Rollback durchgeführt.",
        }
    )
    assert "Rollback" in subject
    assert "Rollback durchgeführt." in body
    assert "backend:beta" in body
    assert "backend:nightly" in body  # restored row rendered


def test_render_boot_failure_without_restored_row():
    subject, body = da._render_alert(
        {
            "id": "2",
            "event": "boot_image_older_than_db",
            "detail": "Image älter als DB.",
            "failed_image": "abc123",
        }
    )
    assert "DB-Schema" in subject
    assert "Wiederhergestellt" not in body  # no restored_image → no row


def test_render_unknown_event_falls_back():
    subject, _ = da._render_alert({"id": "3", "event": "something_new"})
    assert subject.startswith("ConvoyPlan: ")


def test_render_signature_failure_names_the_rejected_images():
    """Der Updater bricht ab, statt ein nicht verifizierbares Image zu ziehen —
    die Mail muss sagen, welches es war, sonst kann niemand nachsehen."""
    subject, body = da._render_alert(
        {
            "id": "3",
            "event": "image_signature_invalid",
            "at": "2026-09-16T04:00:00Z",
            "failed_image": "ghcr.io/x/backend:latest, ghcr.io/x/frontend:latest",
            "detail": "Die Signaturpruefung ist fehlgeschlagen.",
        }
    )
    assert "Signatur" in subject
    assert "ghcr.io/x/backend:latest" in body
    assert "ghcr.io/x/frontend:latest" in body
    # Kein "Wiederhergestellt"-Feld: es wurde nichts zurückgerollt, weil gar
    # nichts deployt wurde.
    assert "Wiederhergestellt" not in body
