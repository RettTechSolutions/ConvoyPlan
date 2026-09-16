"""Autorisierung und Transport des MCP-Servers.

Die Abnahmekriterien aus Task 1.9 des Plans. Jeder Test hier beschreibt
einen Angriff oder eine Verwechslung, die ohne ihn möglich wäre.
"""
from urllib.parse import parse_qs, urlparse

import pytest
from httpx import ASGITransport, AsyncClient
from app.config import settings
from app.database import AsyncSessionLocal
from sqlalchemy import select
from app.mcp import scopes as scope_svc
from app.models.oauth_refresh_token import OAuthRefreshToken
from app.services import oauth_tokens
import tests.mcp_fixtures as fixtures
from tests.mcp_fixtures import (
    BASE_URL,
    INIT_REQUEST as INIT,
    MCP_HEADERS,
    convoyplan_access_token,
    mcp_app,
    pkce_pair,
    purge_clients,
    reset_db_engine,  # noqa: F401 — autouse-Fixture, per Import aktiviert
    seeded,
)

PRM_PATH = "/.well-known/oauth-protected-resource/mcp"


# ── Discovery ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_protected_resource_metadata_liegt_an_der_wurzel():
    """RFC 9728 verlangt das Dokument unter /.well-known/… an der Wurzel.

    Läge es unter /api, fände es kein Client — die Discovery beginnt dort
    und nirgends sonst."""
    async with mcp_app() as (_app, client):
        resp = await client.get(PRM_PATH)
        assert resp.status_code == 200
        body = resp.json()
        assert body["resource"] == f"{BASE_URL}/mcp"
        assert body["authorization_servers"] == [f"{BASE_URL}/"]
        # Scope-Minimierung: nur der Grundfunktionsscope wird ausgewiesen.
        assert body["scopes_supported"] == list(scope_svc.SCOPES_SUPPORTED)


@pytest.mark.asyncio
async def test_authorization_server_metadata_kuendigt_iss_an():
    """RFC 9207: wir senden iss, also müssen wir es auch ankündigen.

    Ohne das Flag darf ein Client ein fehlendes iss nicht beanstanden — die
    Prüfung, die Mix-up-Angriffe verhindert, liefe dann ins Leere."""
    async with mcp_app() as (_app, client):
        body = (await client.get("/.well-known/oauth-authorization-server")).json()
        assert body["authorization_response_iss_parameter_supported"] is True
        assert body["code_challenge_methods_supported"] == ["S256"]
        assert body["issuer"].rstrip("/") == BASE_URL


# ── Der ungeschützte Zugriff ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_ohne_token_401_mit_verweis_auf_die_metadaten():
    """Ein 401 ohne WWW-Authenticate ließe den Client raten, wo er sich
    anmelden soll. Der Header ist der Startpunkt der ganzen Discovery."""
    async with mcp_app() as (_app, client):
        resp = await client.post("/mcp", json=INIT, headers=MCP_HEADERS)
        assert resp.status_code == 401
        challenge = resp.headers.get("www-authenticate", "")
        assert challenge.startswith("Bearer ")
        assert PRM_PATH in challenge
        # Ohne scope müsste der Client raten oder vorsichtshalber alles
        # anfordern — genau das, was die Spec vermeiden will.
        assert f'scope="{scope_svc.SCOPE_READ}"' in challenge


@pytest.mark.asyncio
async def test_kein_redirect_auf_mcp():
    """Regressionstest zur Montage-Form (Plan, Task 0.1).

    Ein app.mount() statt einer Route beantwortet POST /mcp mit 307 auf
    /mcp/. Die kanonische Resource-URI trägt aber keinen Schrägstrich —
    bricht das, stimmt die Audience der Tokens nicht mehr zum Endpunkt."""
    async with mcp_app() as (_app, client):
        resp = await client.post("/mcp", json=INIT, headers=MCP_HEADERS)
        assert resp.status_code != 307, "Transport ist als Mount statt als Route montiert"


# ── Token-Trennung ───────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_convoyplan_token_gilt_am_mcp_endpunkt_nicht():
    """Ein normales Login-Token (typ="access") darf am MCP-Endpunkt nichts
    ausrichten — sonst wäre jeder angemeldete Benutzer automatisch ein
    MCP-Client, ohne je zugestimmt zu haben."""
    async with seeded() as fx, mcp_app() as (_app, client):
        token = convoyplan_access_token(fx.planer, fx.org_a)
        resp = await client.post(
            "/mcp", json=INIT, headers={**MCP_HEADERS, "Authorization": f"Bearer {token}"}
        )
        assert resp.status_code == 401


@pytest.mark.asyncio
async def test_mcp_token_gilt_an_der_rest_api_nicht():
    """Die Gegenrichtung: ein MCP-Token darf die REST-API nicht öffnen.

    Es trägt typ="mcp", und deps._decode_token akzeptiert nur "access" und
    "stream". Diese Prüfung hält die beiden Welten auseinander."""
    from app.main import app as real_app

    async with seeded() as fx:
        token, _ = oauth_tokens.mint_access_token(
            user=fx.planer,
            organization_id=fx.org_a.id,
            client_id="c",
            scopes=[scope_svc.SCOPE_READ],
        )
        async with AsyncClient(
            transport=ASGITransport(app=real_app), base_url="http://test"
        ) as client:
            resp = await client.get(
                "/api/convoys/", headers={"Authorization": f"Bearer {token}"}
            )
        assert resp.status_code == 401


@pytest.mark.asyncio
async def test_token_fuer_eine_fremde_instanz_wird_abgelehnt():
    """RFC 8707: ein Token mit fremder aud ist hier wertlos.

    Ohne diese Prüfung könnte ein Betreiber, bei dem ein Benutzer ebenfalls
    ein Konto hat, dessen Token gegen *diese* Instanz verwenden."""
    async with seeded() as fx, mcp_app() as (_app, client):
        token, _ = oauth_tokens.mint_access_token(
            user=fx.planer,
            organization_id=fx.org_a.id,
            client_id="c",
            scopes=[scope_svc.SCOPE_READ],
            resource="https://eine-andere-instanz.invalid/mcp",
        )
        resp = await client.post(
            "/mcp", json=INIT, headers={**MCP_HEADERS, "Authorization": f"Bearer {token}"}
        )
        assert resp.status_code == 401


@pytest.mark.asyncio
async def test_token_version_bump_entwertet_mcp_tokens():
    """"Überall abmelden" muss auch MCP-Verbindungen treffen."""
    async with seeded() as fx:
        token, _ = oauth_tokens.mint_access_token(
            user=fx.planer,
            organization_id=fx.org_a.id,
            client_id="c",
            scopes=[scope_svc.SCOPE_READ],
        )
        async with AsyncSessionLocal() as db:
            assert await oauth_tokens.verify_access_token(db, token) is not None
            user = await db.get(type(fx.planer), fx.planer.id)
            user.token_version += 1
            await db.commit()
        async with AsyncSessionLocal() as db:
            assert await oauth_tokens.verify_access_token(db, token) is None


@pytest.mark.asyncio
async def test_entzogene_mitgliedschaft_entwertet_das_token_sofort():
    """Ein Token gilt für genau eine Organisation. Wird die Mitgliedschaft
    entzogen, muss es sterben — und zwar sofort, nicht erst beim Ablauf."""
    from app.models.organization import UserOrganization

    async with seeded() as fx:
        token, _ = oauth_tokens.mint_access_token(
            user=fx.planer,
            organization_id=fx.org_a.id,
            client_id="c",
            scopes=[scope_svc.SCOPE_READ],
        )
        async with AsyncSessionLocal() as db:
            from sqlalchemy import delete as _delete

            await db.execute(
                _delete(UserOrganization).where(
                    UserOrganization.user_id == fx.planer.id,
                    UserOrganization.organization_id == fx.org_a.id,
                )
            )
            await db.commit()
        async with AsyncSessionLocal() as db:
            assert await oauth_tokens.verify_access_token(db, token) is None


# ── Client-Registrierung ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_registrierung_lehnt_unsichere_redirect_uris_ab():
    """HTTP auf eine fremde Adresse würde den Autorisierungscode im Klartext
    übers Netz schicken. Loopback ist die einzige Ausnahme (RFC 8252)."""
    async with mcp_app() as (_app, client):
        for bad in (
            "http://angreifer.invalid/callback",
            "https://example.invalid/cb#fragment",
            "https://example.invalid/*",
            "ftp://example.invalid/cb",
        ):
            resp = await client.post(
                "/register",
                json={
                    "redirect_uris": [bad],
                    "client_name": "Böser Client",
                    "grant_types": ["authorization_code", "refresh_token"],
                    "response_types": ["code"],
                },
            )
            assert resp.status_code == 400, f"{bad} wurde akzeptiert"

        for good in ("https://gut.invalid/cb", "http://127.0.0.1:33418/cb",
                     "http://localhost:8080/cb"):
            resp = await client.post(
                "/register",
                json={
                    "redirect_uris": [good],
                    "client_name": "Guter Client",
                    "grant_types": ["authorization_code", "refresh_token"],
                    "response_types": ["code"],
                },
            )
            assert resp.status_code == 201, f"{good} wurde abgelehnt: {resp.text}"
            await purge_clients([resp.json()["client_id"]])


@pytest.mark.asyncio
async def test_dcr_laesst_sich_abschalten():
    """Wer den offenen Registrierungsendpunkt nicht will, schaltet ihn ab."""
    previous = settings.mcp_allow_dcr
    settings.mcp_allow_dcr = False
    try:
        async with mcp_app() as (_app, client):
            resp = await client.post(
                "/register",
                json={
                    "redirect_uris": ["https://gut.invalid/cb"],
                    "grant_types": ["authorization_code", "refresh_token"],
                    "response_types": ["code"],
                },
            )
            assert resp.status_code == 404
    finally:
        settings.mcp_allow_dcr = previous


# ── Autorisierung ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_authorize_lehnt_eine_fremde_resource_ab():
    """Ein Client darf sich hier kein Token für eine andere Instanz holen."""
    async with mcp_app() as (_app, client):
        reg = await _register(client)
        _verifier, challenge = pkce_pair()
        resp = await client.get(
            "/authorize",
            params={
                "client_id": reg["client_id"],
                "redirect_uri": reg["redirect_uris"][0],
                "response_type": "code",
                "code_challenge": challenge,
                "code_challenge_method": "S256",
                "resource": "https://fremde-instanz.invalid/mcp",
            },
        )
        # Der Fehler kommt als Redirect zurück zum Client (OAuth-Konvention).
        assert resp.status_code in (302, 307)
        params = parse_qs(urlparse(resp.headers["location"]).query)
        assert params["error"] == ["invalid_target"]
        await purge_clients([reg["client_id"]])


@pytest.mark.asyncio
async def test_nicht_registrierte_redirect_uri_fuehrt_zu_keinem_redirect():
    """Der wichtigste Einzelfall: eine nicht registrierte redirect_uri darf
    **nicht** angesteuert werden, auch nicht mit einer Fehlermeldung —
    sonst wäre der Endpunkt ein offener Redirector."""
    async with mcp_app() as (_app, client):
        reg = await _register(client)
        _verifier, challenge = pkce_pair()
        resp = await client.get(
            "/authorize",
            params={
                "client_id": reg["client_id"],
                "redirect_uri": "https://angreifer.invalid/steal",
                "response_type": "code",
                "code_challenge": challenge,
                "code_challenge_method": "S256",
            },
        )
        assert resp.status_code == 400
        assert "angreifer.invalid" not in resp.headers.get("location", "")
        await purge_clients([reg["client_id"]])


# ── Hilfen ───────────────────────────────────────────────────────────────


async def _register(client: AsyncClient, redirect_uri: str = "http://127.0.0.1:33418/cb") -> dict:
    resp = await client.post(
        "/register",
        json={
            "redirect_uris": [redirect_uri],
            "client_name": "Testclient",
            "grant_types": ["authorization_code", "refresh_token"],
            "response_types": ["code"],
        },
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


# ── Der vollständige Fluss ───────────────────────────────────────────────


@pytest.mark.asyncio
async def test_vollstaendiger_fluss_bis_zur_werkzeugliste():
    """Registrieren, autorisieren, zustimmen, Token tauschen, Sitzung öffnen.

    Der Durchstich. Schlägt er fehl, ist eine der Stationen kaputt und die
    Einzeltests sagen welche."""
    async with seeded() as fx, mcp_app() as (_app, client):
        reg, token = await fixtures.connect(client, fx.planer, fx.org_a)
        assert token["token_type"] == "Bearer"
        assert token["refresh_token"]
        assert token["expires_in"] == settings.mcp_access_token_ttl_minutes * 60

        session = await fixtures.mcp_session(client, token["access_token"])
        listing = await fixtures.call(client, token["access_token"], session, "tools/list")
        names = {t["name"] for t in listing["result"]["tools"]}
        assert "konvois_auflisten" in names
        await purge_clients([reg["client_id"]])


@pytest.mark.asyncio
async def test_ablehnen_liefert_access_denied_und_keinen_code():
    async with seeded() as fx, mcp_app() as (_app, client):
        reg = await fixtures.register_client(client)
        _verifier, challenge = pkce_pair()
        ticket = await fixtures.authorize(client, reg, challenge)
        assert await fixtures.consent(client, ticket, fx.planer, fx.org_a, approve=False) == ""
        await purge_clients([reg["client_id"]])


@pytest.mark.asyncio
async def test_falscher_code_verifier_wird_abgelehnt():
    """Ohne PKCE-Prüfung nützte ein abgefangener Code einem Angreifer sofort."""
    async with seeded() as fx, mcp_app() as (_app, client):
        reg = await fixtures.register_client(client)
        _verifier, challenge = pkce_pair()
        ticket = await fixtures.authorize(client, reg, challenge)
        code = await fixtures.consent(client, ticket, fx.planer, fx.org_a)

        anderer_verifier, _ = pkce_pair()
        result = await fixtures.exchange_code(client, reg, code, anderer_verifier)
        assert result["status"] == 400
        assert result["body"]["error"] == "invalid_grant"
        await purge_clients([reg["client_id"]])


@pytest.mark.asyncio
async def test_code_replay_toetet_die_token_familie():
    """Ein zweiter Einlöseversuch heißt: jemand hat den Code mitgelesen.

    Dann reicht es nicht, den zweiten Versuch abzulehnen — das aus dem
    ersten entstandene Refresh-Token muss mitsterben, sonst behält der
    Angreifer (oder der rechtmäßige Client, je nachdem wer zuerst war)
    dauerhaften Zugang."""
    async with seeded() as fx, mcp_app() as (_app, client):
        reg = await fixtures.register_client(client)
        verifier, challenge = pkce_pair()
        ticket = await fixtures.authorize(client, reg, challenge)
        code = await fixtures.consent(client, ticket, fx.planer, fx.org_a)

        first = await fixtures.exchange_code(client, reg, code, verifier)
        assert first["status"] == 200

        second = await fixtures.exchange_code(client, reg, code, verifier)
        assert second["status"] == 400

        # Das Refresh-Token aus dem ersten Tausch ist jetzt widerrufen.
        async with AsyncSessionLocal() as db:
            rows = (
                await db.execute(
                    select(OAuthRefreshToken).where(
                        OAuthRefreshToken.organization_id == fx.org_a.id
                    )
                )
            ).scalars().all()
            assert rows, "kein Refresh-Token angelegt"
            assert all(r.revoked for r in rows), "Familie nicht widerrufen"

        refresh = await _refresh(client, reg, first["body"]["refresh_token"])
        assert refresh["status"] == 400
        await purge_clients([reg["client_id"]])


@pytest.mark.asyncio
async def test_refresh_token_rotiert_und_erkennt_wiederverwendung():
    """Rotation allein genügt nicht — das alte Token muss beim erneuten
    Auftauchen die ganze Familie mitnehmen, sonst merkt niemand den Diebstahl."""
    async with seeded() as fx, mcp_app() as (_app, client):
        reg, token = await fixtures.connect(client, fx.planer, fx.org_a)
        altes_refresh = token["refresh_token"]

        erneuert = await _refresh(client, reg, altes_refresh)
        assert erneuert["status"] == 200
        neues_refresh = erneuert["body"]["refresh_token"]
        assert neues_refresh != altes_refresh, "Token wurde nicht rotiert"

        # Das alte Token noch einmal — das ist das Diebstahlsignal.
        wieder = await _refresh(client, reg, altes_refresh)
        assert wieder["status"] == 400

        # Und damit ist auch das frische Token tot.
        danach = await _refresh(client, reg, neues_refresh)
        assert danach["status"] == 400
        await purge_clients([reg["client_id"]])


@pytest.mark.asyncio
async def test_refresh_kann_scopes_nicht_ausweiten():
    """Ein Client darf sich über den Refresh nicht mehr holen, als ihm
    zugestimmt wurde."""
    async with seeded() as fx, mcp_app() as (_app, client):
        reg, token = await fixtures.connect(
            client, fx.planer, fx.org_a, scopes=[scope_svc.SCOPE_READ]
        )
        result = await _refresh(
            client, reg, token["refresh_token"], scope=scope_svc.SCOPE_WRITE
        )
        assert result["status"] == 400
        assert result["body"]["error"] == "invalid_scope"
        await purge_clients([reg["client_id"]])


@pytest.mark.asyncio
async def test_widerruf_trennt_die_verbindung():
    async with seeded() as fx, mcp_app() as (_app, client):
        reg, token = await fixtures.connect(client, fx.planer, fx.org_a)
        resp = await client.post(
            "/revoke",
            data={
                "token": token["refresh_token"],
                "client_id": reg["client_id"],
                "client_secret": reg.get("client_secret", ""),
            },
        )
        assert resp.status_code == 200
        assert (await _refresh(client, reg, token["refresh_token"]))["status"] == 400
        await purge_clients([reg["client_id"]])


async def _refresh(
    client: AsyncClient, reg: dict, refresh_token: str, scope: str | None = None
) -> dict:
    data = {
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
        "client_id": reg["client_id"],
        "client_secret": reg.get("client_secret", ""),
        "resource": f"{BASE_URL}/mcp",
    }
    if scope:
        data["scope"] = scope
    resp = await client.post("/token", data=data)
    return {"status": resp.status_code, "body": resp.json()}


@pytest.mark.asyncio
async def test_widerrufener_client_wird_nicht_mehr_aufgeloest():
    """Ein widerrufener Client darf keine Autorisierung mehr beginnen."""
    from app.models.oauth_client import OAuthClient
    from app.services.oauth_provider import ConvoyPlanOAuthProvider

    async with mcp_app() as (_app, client):
        reg = await _register(client)
        provider = ConvoyPlanOAuthProvider()
        assert await provider.get_client(reg["client_id"]) is not None

        async with AsyncSessionLocal() as db:
            row = await db.get(OAuthClient, reg["client_id"])
            row.revoked = True
            await db.commit()

        assert await provider.get_client(reg["client_id"]) is None
        await purge_clients([reg["client_id"]])


@pytest.mark.asyncio
async def test_abgelaufenes_client_secret_wird_nicht_mehr_aufgeloest():
    from datetime import datetime, timedelta, timezone

    from app.models.oauth_client import OAuthClient
    from app.services.oauth_provider import ConvoyPlanOAuthProvider

    async with mcp_app() as (_app, client):
        reg = await _register(client)
        async with AsyncSessionLocal() as db:
            row = await db.get(OAuthClient, reg["client_id"])
            row.client_secret_expires_at = datetime.now(timezone.utc) - timedelta(minutes=1)
            await db.commit()

        assert await ConvoyPlanOAuthProvider().get_client(reg["client_id"]) is None
        await purge_clients([reg["client_id"]])


@pytest.mark.asyncio
async def test_unbekannter_scope_wird_beim_autorisieren_abgelehnt():
    async with mcp_app() as (_app, client):
        reg = await _register(client)
        _verifier, challenge = pkce_pair()
        resp = await client.get(
            "/authorize",
            params={
                "client_id": reg["client_id"],
                "redirect_uri": reg["redirect_uris"][0],
                "response_type": "code",
                "code_challenge": challenge,
                "code_challenge_method": "S256",
                "scope": "convoy:read admin:everything",
            },
        )
        assert resp.status_code in (302, 307)
        params = parse_qs(urlparse(resp.headers["location"]).query)
        assert params["error"] == ["invalid_scope"]
        await purge_clients([reg["client_id"]])


@pytest.mark.asyncio
async def test_client_secret_liegt_verschluesselt_in_der_datenbank():
    """Ein Klartext-Secret in der Datenbank wäre ein Rückschritt gegenüber
    dem, was ApiKey seit jeher tut."""
    from app.models.oauth_client import OAuthClient

    async with mcp_app() as (_app, client):
        reg = await _register(client)
        secret = reg.get("client_secret")
        assert secret, "das SDK hat kein Secret ausgestellt — Test ist gegenstandslos"
        async with AsyncSessionLocal() as db:
            row = await db.get(OAuthClient, reg["client_id"])
            assert row.client_secret_encrypted
            assert secret not in row.client_secret_encrypted
        await purge_clients([reg["client_id"]])
