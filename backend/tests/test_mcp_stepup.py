"""Step-up-Autorisierung: die Scope-Challenge auf Protokollebene.

Ohne sie muss ein Benutzer die Verbindung von Hand mit erweiterten Rechten
neu erteilen. Mit ihr sagt der Server dem Client, was fehlt, und der holt es
selbst nach.
"""
import pytest

from app.mcp import ALLOWED_TOOLS
from app.mcp import scopes as scope_svc
from tests.mcp_fixtures import (
    MCP_HEADERS,
    connect,
    mcp_app,
    mcp_session,
    purge_clients,
    reset_db_engine,  # noqa: F401 — autouse-Fixture, per Import aktiviert
    seeded,
)

PRM_PATH = "/.well-known/oauth-protected-resource/mcp"


# ── Die Tabelle darf nicht auseinanderlaufen ─────────────────────────────


def test_jedes_werkzeug_steht_in_der_scope_tabelle():
    """Die Tabelle ist eine zweite Quelle derselben Wahrheit — dieser Test
    ist der Grund, warum sie es bleiben darf."""
    assert set(scope_svc.TOOL_SCOPES) == set(ALLOWED_TOOLS)


def test_die_tabelle_kennt_nur_gueltige_scopes():
    assert set(scope_svc.TOOL_SCOPES.values()) <= set(scope_svc.ALL_SCOPES)


def test_unbekanntes_werkzeug_ergibt_keinen_scope():
    """Unbekannt heißt nicht „darf alles" — es heißt: hier nicht entscheiden."""
    assert scope_svc.required_for_tool("rm_minus_rf") is None


# ── Die Challenge ────────────────────────────────────────────────────────


async def _sitzung(client, user, org, scopes):
    reg, token = await connect(client, user, org, scopes)
    session = await mcp_session(client, token["access_token"])
    return reg, token["access_token"], session


async def _aufruf(client, token, session, name, argumente=None):
    return await client.post(
        "/mcp",
        json={
            "jsonrpc": "2.0", "id": 7, "method": "tools/call",
            "params": {"name": name, "arguments": argumente or {}},
        },
        headers={
            **MCP_HEADERS,
            "Authorization": f"Bearer {token}",
            "mcp-session-id": session,
            "MCP-Protocol-Version": "2025-06-18",
        },
    )


@pytest.mark.asyncio
async def test_schreibversuch_mit_lese_token_ergibt_403_mit_challenge():
    """Der Kern: ein Client, der zu wenig hat, erfährt *was* er braucht."""
    async with seeded() as fx, mcp_app() as (_app, client):
        reg, token, session = await _sitzung(
            client, fx.planer, fx.org_a, [scope_svc.SCOPE_READ]
        )
        resp = await _aufruf(client, token, session, "konvoi_anlegen", {"name": "X"})

        assert resp.status_code == 403
        challenge = resp.headers.get("www-authenticate", "")
        assert 'error="insufficient_scope"' in challenge
        assert f'scope="{scope_svc.SCOPE_WRITE}"' in challenge
        # Der Verweis auf die Metadaten gehört laut Spec auch in die
        # 403-Antwort, nicht nur in die 401 — sonst muss der Client die
        # Discovery erraten.
        assert PRM_PATH in challenge
        await purge_clients([reg["client_id"]])


@pytest.mark.asyncio
async def test_statusmeldung_mit_lese_token_fordert_fleet_status():
    async with seeded() as fx, mcp_app() as (_app, client):
        reg, token, session = await _sitzung(
            client, fx.planer, fx.org_a, [scope_svc.SCOPE_READ]
        )
        resp = await _aufruf(client, token, session, "fahrzeugstatus_setzen", {
            "konvoi_id": str(fx.convoy_a.id),
            "fahrzeug_id": str(fx.vehicle_a.id),
            "status": "en_route",
        })
        assert resp.status_code == 403
        assert f'scope="{scope_svc.SCOPE_FLEET_STATUS}"' in resp.headers["www-authenticate"]
        await purge_clients([reg["client_id"]])


@pytest.mark.asyncio
async def test_ausreichende_rechte_gehen_unveraendert_durch():
    """Die Schicht darf nichts zusätzlich verbieten — nur früher ablehnen."""
    async with seeded() as fx, mcp_app() as (_app, client):
        reg, token, session = await _sitzung(
            client, fx.planer, fx.org_a, list(scope_svc.ALL_SCOPES)
        )
        resp = await _aufruf(client, token, session, "konvois_auflisten")
        assert resp.status_code == 200
        resp = await _aufruf(client, token, session, "konvoi_anlegen", {"name": "Darf"})
        assert resp.status_code == 200
        await purge_clients([reg["client_id"]])


@pytest.mark.asyncio
async def test_lesen_bleibt_mit_lese_token_moeglich():
    async with seeded() as fx, mcp_app() as (_app, client):
        reg, token, session = await _sitzung(
            client, fx.planer, fx.org_a, [scope_svc.SCOPE_READ]
        )
        resp = await _aufruf(client, token, session, "konvois_auflisten")
        assert resp.status_code == 200
        await purge_clients([reg["client_id"]])


@pytest.mark.asyncio
async def test_der_rumpf_kommt_unversehrt_beim_transport_an():
    """Die Schicht liest den Anfragerumpf, um ihn zu prüfen. Ein ASGI-Server
    liefert ihn nur einmal — wird er nicht sauber zurückgespielt, sieht der
    Transport eine leere Anfrage und die Argumente gehen verloren."""
    async with seeded() as fx, mcp_app() as (_app, client):
        reg, token, session = await _sitzung(
            client, fx.planer, fx.org_a, list(scope_svc.ALL_SCOPES)
        )
        resp = await _aufruf(client, token, session, "konvoi_anlegen", {
            "name": "Rumpf kam an", "auftrag": "mit allen Feldern",
        })
        assert resp.status_code == 200
        assert "Rumpf kam an" in resp.text
        await purge_clients([reg["client_id"]])


@pytest.mark.asyncio
async def test_ohne_token_bleibt_es_bei_401():
    """Reihenfolge: erst muss überhaupt ein Token da sein (401), dann geht es
    um dessen Breite (403). Andersherum verriete die Antwort einem
    Unangemeldeten, welche Werkzeuge es gibt."""
    async with mcp_app() as (_app, client):
        resp = await client.post(
            "/mcp",
            json={"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                  "params": {"name": "konvoi_anlegen", "arguments": {}}},
            headers=MCP_HEADERS,
        )
        assert resp.status_code == 401
