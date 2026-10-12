"""Konvoi aktiv schalten: der Knopf in Planung und Tracking-Ansicht.

„Aktiv" ist keine Beschriftung — fest eingebaute Tracker senden nur, solange
ihr Fahrzeug in einem aktiven Konvoi steht. Der Status war lange Freitext und
ohne Knopf nur über API und MCP erreichbar; ein „aktiv" statt „active" ließ
den Tracker still schweigen.
"""
import pytest

from tests.aktionsseite_fixtures import client, h, reset_db_engine  # noqa: F401
from tests.test_tracker_geraete import _eingerichtet, _konvoi_status, org  # noqa: F401


async def _status(client, org, status: str, token=None):
    return await client.put(
        f"/api/convoys/{org.konvoi}", json={"status": status}, headers=h(token or org.admin)
    )


async def test_aktiv_geschaltet_sendet_der_tracker(client, org):
    await _konvoi_status(org.konvoi, "planning")
    _, kopf = await _eingerichtet(client, org)
    assert (await client.post("/api/geraete/hallo", json={}, headers=kopf)).json()["modus"] == "schweigen"

    r = await _status(client, org, "active")
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "active"
    assert (await client.post("/api/geraete/hallo", json={}, headers=kopf)).json()["modus"] == "senden"

    assert (await _status(client, org, "completed")).status_code == 200
    assert (await client.post("/api/geraete/hallo", json={}, headers=kopf)).json()["modus"] == "schweigen"


@pytest.mark.parametrize("falsch", ["aktiv", "ACTIVE", "läuft", ""])
async def test_unbekannter_status_wird_abgewiesen(client, org, falsch):
    await _konvoi_status(org.konvoi, "planning")
    assert (await _status(client, org, falsch)).status_code == 422
    r = await client.get(f"/api/convoys/{org.konvoi}", headers=h(org.admin))
    assert r.json()["status"] == "planning"


async def test_fahrer_darf_nicht_schalten(client, org):
    await _konvoi_status(org.konvoi, "planning")
    assert (await _status(client, org, "active", org.fahrer)).status_code == 403
