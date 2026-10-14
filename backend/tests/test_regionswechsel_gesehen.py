"""„Schließen" auf einem beendeten Regionswechsel gilt am Server.

Vorher blendete der Knopf die Phasenkarte nur für den einen Seitenaufruf aus:
Der Endstatus steht bis zum nächsten Wechsel in `region_status.json`, und
jedes Öffnen des Admin-Portals klappte ihn samt komplettem Log wieder auf.
Die Zusagen:
  - quittiert wird genau der Endstatus, den der Bediener gesehen hat;
  - ein neuer Wechsel (anderes `at`) ist wieder ungesehen;
  - ein laufender Wechsel lässt sich nicht wegklicken, ein veralteter Klick
    nichts Neueres;
  - der Status meldet `seen` nur für den quittierten Endstatus.
"""
import json

import pytest
from httpx import ASGITransport, AsyncClient

from app.api.deps import require_superadmin
from app.main import app
from app.services import graph_aufbau, region_switch

ENDE = {"phase": "done", "message": "Regionswechsel abgeschlossen", "at": "2026-10-14T06:08:13Z"}


@pytest.fixture
def volume(tmp_path, monkeypatch):
    monkeypatch.setattr(region_switch, "VOLUME", str(tmp_path))
    monkeypatch.setattr(graph_aufbau, "graph_zustand", lambda: None)

    def status(s: dict) -> None:
        (tmp_path / region_switch.STATUS_FILE).write_text(json.dumps(s))

    return status


@pytest.fixture
def client():
    app.dependency_overrides[require_superadmin] = lambda: object()
    yield AsyncClient(transport=ASGITransport(app=app), base_url="http://test")
    app.dependency_overrides.clear()


async def _status(client) -> dict:
    resp = await client.get("/api/admin/region/status")
    assert resp.status_code == 200
    return resp.json()


@pytest.mark.parametrize("phase", ["done", "failed", "cancelled"])
async def test_quittierter_endstatus_bleibt_quittiert(volume, client, phase):
    volume({**ENDE, "phase": phase})
    assert "seen" not in await _status(client)

    resp = await client.post("/api/admin/region/seen", json={"phase": phase, "at": ENDE["at"]})
    assert resp.status_code == 204
    # Jeder weitere Abruf — also jeder weitere Seitenaufruf — sieht die Marke.
    assert (await _status(client))["seen"] is True
    assert (await _status(client))["seen"] is True


async def test_ein_neuer_wechsel_ist_wieder_ungesehen(volume, client):
    volume(ENDE)
    await client.post("/api/admin/region/seen", json={"phase": "done", "at": ENDE["at"]})

    volume({**ENDE, "phase": "failed", "at": "2026-10-15T03:12:00Z"})
    assert "seen" not in await _status(client)


async def test_laufender_wechsel_laesst_sich_nicht_wegklicken(volume, client):
    volume({"phase": "importing", "at": "2026-10-14T06:00:00Z"})
    resp = await client.post(
        "/api/admin/region/seen", json={"phase": "importing", "at": "2026-10-14T06:00:00Z"}
    )
    assert resp.status_code == 409
    assert "seen" not in await _status(client)


async def test_veralteter_klick_quittiert_nichts_neueres(volume, client):
    # Der Bediener sah das Ende von gestern, inzwischen endete ein anderer.
    volume({**ENDE, "at": "2026-10-15T03:12:00Z"})
    resp = await client.post("/api/admin/region/seen", json={"phase": "done", "at": ENDE["at"]})
    assert resp.status_code == 409
    assert "seen" not in await _status(client)


async def test_wartende_anforderung_ist_nie_gesehen(volume, client, tmp_path):
    """Das Ende des vorigen Wechsels steht noch in der Datei, aber eine neue
    Anforderung liegt an — `read_status` meldet `queued`, nicht das alte Ende."""
    volume(ENDE)
    await client.post("/api/admin/region/seen", json={"phase": "done", "at": ENDE["at"]})
    (tmp_path / region_switch.REQUEST_FILE).write_text(json.dumps({"requested_at": "x"}))

    status = await _status(client)
    assert status["phase"] == "queued"
    assert "seen" not in status


def test_ohne_at_gibt_es_nichts_zu_quittieren(volume):
    volume({"phase": "done"})
    assert region_switch.mark_seen("done", "") is False
    assert region_switch.is_seen({"phase": "done"}) is False


async def test_nur_fuer_superadmins():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        resp = await c.post("/api/admin/region/seen", json={"phase": "done", "at": ENDE["at"]})
    assert resp.status_code in (401, 403)
