"""Die Werkzeuge des MCP-Servers, über eine echte Sitzung aufgerufen.

Nicht über die Registrierungsfunktion geprüft, sondern über den Transport:
was hier durchgeht, geht auch für einen echten Client durch.
"""
import pytest

import tests.mcp_fixtures as fixtures
from app.mcp import ALLOWED_TOOLS
from tests.mcp_fixtures import (
    mcp_app,
    purge_clients,
    reset_db_engine,  # noqa: F401 — autouse-Fixture, per Import aktiviert
    seeded,
)


@pytest.mark.asyncio
async def test_registrierte_werkzeuge_entsprechen_der_positivliste():
    """Die schärfste Zusage des Plans: kein Werkzeug löscht Daten.

    Geprüft über eine Positivliste statt über eine Namensregel — ein neues
    Werkzeug bricht diesen Test, bis es bewusst eingetragen wurde."""
    async with seeded() as fx, mcp_app() as (_app, client):
        reg, token = await fixtures.connect(client, fx.planer, fx.org_a)
        session = await fixtures.mcp_session(client, token["access_token"])
        listing = await fixtures.call(client, token["access_token"], session, "tools/list")
        namen = sorted(t["name"] for t in listing["result"]["tools"])
        assert namen == sorted(ALLOWED_TOOLS)
        await purge_clients([reg["client_id"]])


@pytest.mark.asyncio
async def test_konvois_auflisten_zeigt_nur_die_eigene_organisation():
    """Mandantentrennung. Der Benutzer ist Mitglied in **beiden**
    Organisationen — das Token gilt aber nur für eine. Trennt hier etwas
    nicht sauber, sieht ein Modell fremde Einsatzdaten."""
    async with seeded() as fx, mcp_app() as (_app, client):
        reg, token = await fixtures.connect(client, fx.planer, fx.org_a)
        session = await fixtures.mcp_session(client, token["access_token"])
        antwort = fixtures.tool_payload(
            await fixtures.call(
                client, token["access_token"], session,
                "tools/call", {"name": "konvois_auflisten", "arguments": {}},
            )
        )
        namen = [k["name"] for k in antwort["konvois"]]
        assert fx.convoy_a.name in namen
        assert fx.convoy_b.name not in namen
        assert antwort["organisation"] == fx.org_a.name
        await purge_clients([reg["client_id"]])


@pytest.mark.asyncio
async def test_fremder_konvoi_ist_ueber_die_id_nicht_erreichbar():
    """Die ID eines fremden Konvois zu kennen darf nichts nützen — und die
    Antwort darf nicht verraten, ob es ihn gibt."""
    async with seeded() as fx, mcp_app() as (_app, client):
        reg, token = await fixtures.connect(client, fx.planer, fx.org_a)
        session = await fixtures.mcp_session(client, token["access_token"])
        antwort = await fixtures.call(
            client, token["access_token"], session,
            "tools/call",
            {"name": "konvoi_details", "arguments": {"konvoi_id": str(fx.convoy_b.id)}},
        )
        assert antwort["result"]["isError"] is True
        text = antwort["result"]["content"][0]["text"]
        assert "Kein Konvoi" in text
        assert fx.convoy_b.name not in text
        await purge_clients([reg["client_id"]])


@pytest.mark.asyncio
async def test_konvoi_details_liefert_marschbefehl_und_fahrzeuge():
    async with seeded() as fx, mcp_app() as (_app, client):
        reg, token = await fixtures.connect(client, fx.planer, fx.org_a)
        session = await fixtures.mcp_session(client, token["access_token"])
        antwort = fixtures.tool_payload(
            await fixtures.call(
                client, token["access_token"], session,
                "tools/call",
                {"name": "konvoi_details", "arguments": {"konvoi_id": str(fx.convoy_a.id)}},
            )
        )
        assert antwort["name"] == fx.convoy_a.name
        assert "marschbefehl" in antwort
        assert [f["funkrufname"] for f in antwort["fahrzeuge"]] == ["Florian 1"]
        await purge_clients([reg["client_id"]])


@pytest.mark.asyncio
async def test_route_abrufen_sagt_deutlich_wenn_keine_route_da_ist():
    """Eine leere Antwort ließe ein Modell raten. Der Hinweis sagt ihm, was
    fehlt — und dass Berechnen ein anderer Schritt wäre."""
    async with seeded() as fx, mcp_app() as (_app, client):
        reg, token = await fixtures.connect(client, fx.planer, fx.org_a)
        session = await fixtures.mcp_session(client, token["access_token"])
        antwort = fixtures.tool_payload(
            await fixtures.call(
                client, token["access_token"], session,
                "tools/call",
                {"name": "route_abrufen", "arguments": {"konvoi_id": str(fx.convoy_a.id)}},
            )
        )
        assert antwort["route_vorhanden"] is False
        assert "noch keine Route" in antwort["hinweis"]
        await purge_clients([reg["client_id"]])


@pytest.mark.asyncio
async def test_fahrzeuge_auflisten_zeigt_nur_die_felder_der_antriebsart():
    """Ein Verbrenner mit "akku_kapazitaet_kwh: null" lädt nur zu
    Fehlschlüssen ein."""
    async with seeded() as fx, mcp_app() as (_app, client):
        reg, token = await fixtures.connect(client, fx.planer, fx.org_a)
        session = await fixtures.mcp_session(client, token["access_token"])
        antwort = fixtures.tool_payload(
            await fixtures.call(
                client, token["access_token"], session,
                "tools/call", {"name": "fahrzeuge_auflisten", "arguments": {}},
            )
        )
        fahrzeug = antwort["fahrzeuge"][0]
        assert "tank_kapazitaet_l" in fahrzeug
        assert "akku_kapazitaet_kwh" not in fahrzeug
        await purge_clients([reg["client_id"]])
