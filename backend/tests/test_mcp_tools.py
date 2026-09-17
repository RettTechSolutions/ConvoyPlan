"""Die Werkzeuge des MCP-Servers, über eine echte Sitzung aufgerufen.

Nicht über die Registrierungsfunktion geprüft, sondern über den Transport:
was hier durchgeht, geht auch für einen echten Client durch.
"""
from datetime import datetime

import pytest

from app.database import AsyncSessionLocal
from app.mcp import ALLOWED_TOOLS
from app.models.convoy import Convoy
from tests.mcp_fixtures import (
    call,
    connect,
    mcp_app,
    mcp_session,
    purge_clients,
    reset_db_engine,  # noqa: F401 — autouse-Fixture, per Import aktiviert
    seeded,
    tool_payload,
)


@pytest.mark.asyncio
async def test_registrierte_werkzeuge_entsprechen_der_positivliste():
    """Die schärfste Zusage des Plans: kein Werkzeug löscht Daten.

    Geprüft über eine Positivliste statt über eine Namensregel — ein neues
    Werkzeug bricht diesen Test, bis es bewusst eingetragen wurde."""
    async with seeded() as fx, mcp_app() as (_app, client):
        reg, token = await connect(client, fx.planer, fx.org_a)
        session = await mcp_session(client, token["access_token"])
        listing = await call(client, token["access_token"], session, "tools/list")
        namen = sorted(t["name"] for t in listing["result"]["tools"])
        assert namen == sorted(ALLOWED_TOOLS)
        await purge_clients([reg["client_id"]])


@pytest.mark.asyncio
async def test_konvois_auflisten_zeigt_nur_die_eigene_organisation():
    """Mandantentrennung. Der Benutzer ist Mitglied in **beiden**
    Organisationen — das Token gilt aber nur für eine. Trennt hier etwas
    nicht sauber, sieht ein Modell fremde Einsatzdaten."""
    async with seeded() as fx, mcp_app() as (_app, client):
        reg, token = await connect(client, fx.planer, fx.org_a)
        session = await mcp_session(client, token["access_token"])
        antwort = tool_payload(
            await call(
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
        reg, token = await connect(client, fx.planer, fx.org_a)
        session = await mcp_session(client, token["access_token"])
        antwort = await call(
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
        reg, token = await connect(client, fx.planer, fx.org_a)
        session = await mcp_session(client, token["access_token"])
        antwort = tool_payload(
            await call(
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
        reg, token = await connect(client, fx.planer, fx.org_a)
        session = await mcp_session(client, token["access_token"])
        antwort = tool_payload(
            await call(
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
        reg, token = await connect(client, fx.planer, fx.org_a)
        session = await mcp_session(client, token["access_token"])
        antwort = tool_payload(
            await call(
                client, token["access_token"], session,
                "tools/call", {"name": "fahrzeuge_auflisten", "arguments": {}},
            )
        )
        fahrzeug = antwort["fahrzeuge"][0]
        assert "tank_kapazitaet_l" in fahrzeug
        assert "akku_kapazitaet_kwh" not in fahrzeug
        await purge_clients([reg["client_id"]])


# ── Filter auf der Konvoi-Liste ──────────────────────────────────────────
#
# „Welche Konvois stehen nächste Woche an?" muss serverseitig zu beantworten
# sein. Ohne Filter bleibt einem Modell nur, den gesamten Bestand zu ziehen
# und selbst auszusortieren — das skaliert nicht und füllt den Kontext mit
# Konvois, nach denen niemand gefragt hat.


async def _konvoi_mit_startzeit(org_id, owner_id, name: str, start) -> None:
    async with AsyncSessionLocal() as db:
        db.add(
            Convoy(
                name=name, organization_id=org_id, owner_id=owner_id, start_time=start
            )
        )
        await db.commit()


@pytest.mark.asyncio
async def test_konvois_auflisten_filtert_auf_einen_zeitraum():
    async with seeded() as fx, mcp_app() as (_app, client):
        await _konvoi_mit_startzeit(
            fx.org_a.id, fx.planer.id, "Marsch nächste Woche",
            datetime(2026, 9, 21, 6, 30),
        )
        await _konvoi_mit_startzeit(
            fx.org_a.id, fx.planer.id, "Marsch im Oktober",
            datetime(2026, 10, 5, 6, 30),
        )
        reg, token = await connect(client, fx.planer, fx.org_a)
        session = await mcp_session(client, token["access_token"])

        antwort = tool_payload(
            await call(
                client, token["access_token"], session, "tools/call",
                {
                    "name": "konvois_auflisten",
                    "arguments": {"von": "2026-09-21", "bis": "2026-09-27"},
                },
            )
        )
        namen = [k["name"] for k in antwort["konvois"]]
        assert namen == ["Marsch nächste Woche"]
        await purge_clients([reg["client_id"]])


@pytest.mark.asyncio
async def test_obere_zeitgrenze_schliesst_den_ganzen_tag_ein():
    """„bis 21.09." meint niemand als „bis 21.09. 00:00 Uhr"."""
    async with seeded() as fx, mcp_app() as (_app, client):
        await _konvoi_mit_startzeit(
            fx.org_a.id, fx.planer.id, "Abmarsch 06:30", datetime(2026, 9, 21, 6, 30)
        )
        reg, token = await connect(client, fx.planer, fx.org_a)
        session = await mcp_session(client, token["access_token"])
        antwort = tool_payload(
            await call(
                client, token["access_token"], session, "tools/call",
                {
                    "name": "konvois_auflisten",
                    "arguments": {"von": "2026-09-21", "bis": "2026-09-21"},
                },
            )
        )
        assert [k["name"] for k in antwort["konvois"]] == ["Abmarsch 06:30"]
        await purge_clients([reg["client_id"]])


@pytest.mark.asyncio
async def test_unlesbare_zeitangabe_erklaert_sich_statt_zu_scheitern():
    """Ein Modell soll aus dem Fehler ableiten können, was erwartet wird."""
    async with seeded() as fx, mcp_app() as (_app, client):
        reg, token = await connect(client, fx.planer, fx.org_a)
        session = await mcp_session(client, token["access_token"])
        ergebnis = await call(
            client, token["access_token"], session, "tools/call",
            {"name": "konvois_auflisten", "arguments": {"von": "nächsten Montag"}},
        )
        text = str(ergebnis)
        assert "ISO-8601" in text
        await purge_clients([reg["client_id"]])


@pytest.mark.asyncio
async def test_konvois_auflisten_sucht_im_namen():
    async with seeded() as fx, mcp_app() as (_app, client):
        reg, token = await connect(client, fx.planer, fx.org_a)
        session = await mcp_session(client, token["access_token"])
        antwort = tool_payload(
            await call(
                client, token["access_token"], session, "tools/call",
                {"name": "konvois_auflisten", "arguments": {"suche": "marschverband"}},
            )
        )
        assert antwort["anzahl"] == 1
        assert antwort["konvois"][0]["id"] == str(fx.convoy_a.id)
        await purge_clients([reg["client_id"]])


@pytest.mark.asyncio
async def test_konvois_auflisten_sagt_wenn_mehr_da_ist():
    """Ein abgeschnittenes Ergebnis, das sich nicht als solches zu erkennen
    gibt, liest ein Modell als vollständig."""
    async with seeded() as fx, mcp_app() as (_app, client):
        for i in range(3):
            await _konvoi_mit_startzeit(
                fx.org_a.id, fx.planer.id, f"Marsch {i}", datetime(2026, 9, 21, 6, 0)
            )
        reg, token = await connect(client, fx.planer, fx.org_a)
        session = await mcp_session(client, token["access_token"])
        antwort = tool_payload(
            await call(
                client, token["access_token"], session, "tools/call",
                {"name": "konvois_auflisten", "arguments": {"limit": 2}},
            )
        )
        assert antwort["anzahl"] == 2
        assert "hinweis" in antwort
        await purge_clients([reg["client_id"]])


# ── Auskunft über die eigene Verbindung ──────────────────────────────────


@pytest.mark.asyncio
async def test_organisation_details_nennt_organisation_rolle_und_rechte():
    """Auf wessen Daten diese Verbindung zeigt und was sie darf — sonst
    bleibt beides nur durch Ausprobieren zu klären."""
    async with seeded() as fx, mcp_app() as (_app, client):
        reg, token = await connect(client, fx.planer, fx.org_a)
        session = await mcp_session(client, token["access_token"])
        antwort = tool_payload(
            await call(
                client, token["access_token"], session, "tools/call",
                {"name": "organisation_details", "arguments": {}},
            )
        )
        assert antwort["organisation"] == fx.org_a.name
        assert antwort["eigene_rolle"] == "planer"
        assert antwort["konvois_anzahl"] == 1
        assert antwort["fahrzeuge_anzahl"] == 1
        # Die Verbindung ist lesend erteilt — also steht auch nur Lesendes drin.
        assert "konvois_auflisten" in antwort["verfuegbare_werkzeuge"]
        assert "konvoi_anlegen" not in antwort["verfuegbare_werkzeuge"]
        await purge_clients([reg["client_id"]])


@pytest.mark.asyncio
async def test_organisation_details_zeigt_fremde_organisation_nicht():
    """Der Planer ist Mitglied in beiden Organisationen; das Token gilt für
    eine. Die Zahlen dürfen die andere nicht mitzählen."""
    async with seeded() as fx, mcp_app() as (_app, client):
        reg, token = await connect(client, fx.planer, fx.org_b)
        session = await mcp_session(client, token["access_token"])
        antwort = tool_payload(
            await call(
                client, token["access_token"], session, "tools/call",
                {"name": "organisation_details", "arguments": {}},
            )
        )
        assert antwort["organisation"] == fx.org_b.name
        assert antwort["fahrzeuge_anzahl"] == 0
        await purge_clients([reg["client_id"]])


@pytest.mark.asyncio
async def test_werkzeuge_antworten_strukturiert_und_als_text():
    """Beides, nicht eines von beidem.

    Die Oberflächen (`app/mcp/widgets.py`) lesen `structuredContent`; ein
    Client ohne Schemaunterstützung liest weiterhin den Textteil. Fiele der
    Textteil weg, verlöre der zweite alles — fiele die Struktur weg, zeigten
    die Oberflächen eine leere Fläche."""
    async with seeded() as fx, mcp_app() as (_app, client):
        reg, token = await connect(client, fx.planer, fx.org_a)
        session = await mcp_session(client, token["access_token"])
        antwort = await call(
            client, token["access_token"], session, "tools/call",
            {"name": "konvois_auflisten", "arguments": {}},
        )
        result = antwort["result"]
        assert result["structuredContent"]["organisation"] == fx.org_a.name
        assert result["content"][0]["type"] == "text"
        assert fx.org_a.name in result["content"][0]["text"]
        await purge_clients([reg["client_id"]])
