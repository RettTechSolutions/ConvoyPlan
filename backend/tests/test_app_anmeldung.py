"""Anmeldung der Begleit-App über den Browser (OAuth 2.1 + PKCE, RFC 8252).

Der ganze Weg mit echter Datenbank und echtem SDK: ``/authorize`` →
``/oauth/app`` → Code → ``/token`` → REST-API → Refresh. Und durchgehend mit
**abgeschaltetem MCP**, denn genau das ist die Zusage: der App-Client hängt
weder am MCP-Schalter noch an der MCP-Richtlinie der Organisation.

Dazu das, was ein MCP-Client an derselben Stelle nicht mehr darf, seit
``/token`` auch ohne MCP montiert ist — und was ein App-Token an der
REST-API nicht darf, wenn es für etwas anderes ausgestellt wurde.
"""
import base64
import contextlib
import hashlib
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qs, urlparse

import bcrypt
import jwt as _jwt
import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, select

from app.api import cookies
from app.api.routes import app_oauth as app_oauth_router
from app.api.routes import auth as auth_router
from app.api.routes import version as version_router
from app.api.routes.auth import create_token
from app.config import settings
from app.database import AsyncSessionLocal, engine
from app.mcp import mount as mcp_mount
from app.models.oauth_client import OAuthClient
from app.models.oauth_refresh_token import OAuthRefreshToken
from app.models.organization import Organization, UserOrganization
from app.models.user import User
from app.services import app_client, mcp_config, oauth_provider, oauth_tokens

BASE = "https://app-oauth-test.convoyplan.invalid"
CSRF = {cookies.CSRF_HEADER: cookies.CSRF_VALUE}


# ── Regeln ohne Datenbank ────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("sitzung", "anfrage", "frisch"),
    [
        (100, 100, True),    # in derselben Sekunde angemeldet
        (160, 100, True),    # nach der Anfrage
        (40, 100, False),    # vorher — eine bestehende Sitzung
        (None, 100, False),  # Sitzung von vor dieser Änderung (ohne iat)
        (160, None, False),
    ],
)
def test_frisch_angemeldet(sitzung, anfrage, frisch):
    assert app_client.frisch_angemeldet(sitzung, anfrage) is frisch


def test_tickets_von_app_und_mcp_sind_nicht_austauschbar():
    """Ein Ticket der App geht nicht auf dem MCP-Zustimmungsschirm durch und
    umgekehrt — sonst ließe sich die Zustimmung der einen Strecke mit der
    anderen umgehen."""
    from mcp.server.auth.provider import AuthorizationParams

    params = AuthorizationParams(
        state="s", scopes=None, code_challenge="c" * 43,
        redirect_uri=app_client.REDIRECT_URI, redirect_uri_provided_explicitly=True,
        resource=None,
    )
    app_ticket = oauth_provider.encode_app_request(params, "org")
    mcp_ticket = oauth_provider.encode_authorize_request("irgendwer", params)
    assert oauth_provider.decode_authorize_request(app_ticket) is None
    assert oauth_provider.decode_app_request(mcp_ticket) is None
    assert oauth_provider.decode_app_request(app_ticket)["org_slug"] == "org"


# ── Durch die App ────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
async def reset_db_engine():
    yield
    await engine.dispose()


@pytest.fixture(autouse=True)
def mcp_aus(monkeypatch):
    """MCP abgeschaltet — unabhängig von dem, was in der Datenbank steht."""
    async def _aus(_db):
        return False

    monkeypatch.setattr(mcp_config, "is_mcp_enabled", _aus)


@contextlib.asynccontextmanager
async def app_umgebung():
    vorher = settings.app_base_url, settings.mcp_public_url, settings.app_oauth_enabled
    settings.app_base_url = BASE
    settings.mcp_public_url = ""
    settings.app_oauth_enabled = True
    try:
        app = FastAPI(lifespan=lambda _app: mcp_mount.lifespan_context())
        app.include_router(app_oauth_router.router, prefix="/api")
        app.include_router(auth_router.router, prefix="/api")
        app.include_router(version_router.router, prefix="/api")
        mcp_mount.mount(app)
        async with app.router.lifespan_context(app):
            mcp_mount._anwenden(False)
            async with AsyncClient(transport=ASGITransport(app=app), base_url=BASE) as client:
                yield client
    finally:
        settings.app_base_url, settings.mcp_public_url, settings.app_oauth_enabled = vorher
        mcp_mount._session_manager = None
        mcp_mount._app = None
        mcp_mount._routes = []
        mcp_mount._as_routes = []


@pytest.fixture
async def konto():
    marker = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        user = User(
            email=f"app-oauth-{marker}@test.invalid",
            hashed_password=bcrypt.hashpw(b"x", bcrypt.gensalt(4)).decode(),
        )
        db.add(user)
        await db.flush()
        org = Organization(name="App-Test", slug=f"app-oauth-{marker}", owner_id=user.id)
        fremd = Organization(name="Fremd", slug=f"app-oauth-fremd-{marker}", owner_id=user.id)
        db.add_all([org, fremd])
        await db.flush()
        db.add(UserOrganization(user_id=user.id, organization_id=org.id, role="planer"))
        await db.commit()
        await db.refresh(user)
    yield {"user": user, "org": org, "fremd": fremd}
    async with AsyncSessionLocal() as db:
        await db.execute(delete(OAuthRefreshToken).where(OAuthRefreshToken.user_id == user.id))
        await db.execute(delete(UserOrganization).where(UserOrganization.user_id == user.id))
        await db.execute(delete(Organization).where(Organization.id.in_([org.id, fremd.id])))
        await db.execute(delete(User).where(User.id == user.id))
        await db.commit()


def pkce() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(48)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
    return verifier, challenge


async def authorize(client: AsyncClient, org_slug: str | None, challenge: str, **extra) -> str:
    """``/authorize`` wie die App es aufruft; gibt das Ticket aus der Weiterleitung."""
    params = {
        "client_id": app_client.CLIENT_ID,
        "redirect_uri": app_client.REDIRECT_URI,
        "response_type": "code",
        "code_challenge": challenge,
        "code_challenge_method": "S256",
        "state": "zustand-123",
        **extra,
    }
    if org_slug is not None:
        params["org_slug"] = org_slug
    r = await client.get("/authorize", params=params)
    assert r.status_code == 302, r.text
    ort = r.headers["location"]
    assert ort.startswith(f"{BASE}/oauth/app?request="), ort
    return parse_qs(urlparse(ort).query)["request"][0]


def sitzung(client: AsyncClient, user: User, org: Organization, *, iat: datetime | None = None) -> None:
    """Die Org-Sitzung, die die Anmeldeseite als Cookie setzt."""
    if iat is None:
        token = create_token(str(user.id), False, str(org.id), org.slug, "planer", user.token_version)
    else:
        token = _jwt.encode(
            {
                "sub": str(user.id), "iat": iat, "exp": iat + timedelta(days=7), "typ": "access",
                "is_superadmin": False, "org_id": str(org.id), "org_slug": org.slug,
                "role": "planer", "tv": user.token_version,
            },
            settings.jwt_secret, algorithm=settings.jwt_algorithm,
        )
    client.cookies.set(cookies.cookie_name(org.slug), token)


async def entscheiden(client: AsyncClient, ticket: str, **body):
    return await client.post("/api/oauth/app/anfrage", json={"request": ticket, **body}, headers=CSRF)


def rueckgabe(url: str) -> dict:
    assert url.startswith(app_client.REDIRECT_URI + "?"), url
    params = {k: v[0] for k, v in parse_qs(urlparse(url).query).items()}
    assert params["state"] == "zustand-123"
    assert params["iss"] == oauth_tokens.issuer_url()
    return params


async def token_tausch(client: AsyncClient, code: str, verifier: str):
    return await client.post(
        "/token",
        data={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": app_client.REDIRECT_URI,
            "client_id": app_client.CLIENT_ID,
            "code_verifier": verifier,
        },
    )


async def refresh(client: AsyncClient, refresh_token: str):
    return await client.post(
        "/token",
        data={"grant_type": "refresh_token", "refresh_token": refresh_token, "client_id": app_client.CLIENT_ID},
    )


async def anmelden(client: AsyncClient, konto: dict) -> dict:
    """Der ganze Weg bis zu den Tokens, mit frischer Anmeldung."""
    verifier, challenge = pkce()
    ticket = await authorize(client, konto["org"].slug, challenge)
    sitzung(client, konto["user"], konto["org"])
    r = await entscheiden(client, ticket)
    assert r.status_code == 200, r.text
    code = rueckgabe(r.json()["redirect_url"])["code"]
    client.cookies.clear()
    t = await token_tausch(client, code, verifier)
    assert t.status_code == 200, t.text
    return t.json()


async def test_der_ganze_weg_ohne_mcp(konto):
    async with app_umgebung() as client:
        tokens = await anmelden(client, konto)

        assert tokens["expires_in"] == settings.app_oauth_access_token_ttl_minutes * 60
        assert tokens["refresh_token"]

        claims = _jwt.decode(
            tokens["access_token"], settings.jwt_secret, algorithms=[settings.jwt_algorithm],
            audience=app_client.api_resource_url(),
        )
        assert claims["typ"] == "access"
        assert claims["org_slug"] == konto["org"].slug
        assert claims["client_id"] == app_client.CLIENT_ID

        # Die REST-API nimmt es an …
        me = await client.get("/api/auth/me", headers={"Authorization": f"Bearer {tokens['access_token']}"})
        assert me.status_code == 200, me.text
        assert me.json()["org_slug"] == konto["org"].slug

        # … der MCP-Endpunkt nicht (dort gilt nur typ="mcp").
        async with AsyncSessionLocal() as db:
            assert await oauth_tokens.verify_access_token(db, tokens["access_token"]) is None

    async with AsyncSessionLocal() as db:
        row = (
            await db.execute(select(OAuthRefreshToken).where(OAuthRefreshToken.user_id == konto["user"].id))
        ).scalar_one()
        laufzeit = row.expires_at - datetime.now(timezone.utc)
        assert timedelta(days=89) < laufzeit <= timedelta(days=90)
        assert row.token_version == konto["user"].token_version


async def test_refresh_rotiert_und_erkennt_wiederverwendung(konto):
    async with app_umgebung() as client:
        tokens = await anmelden(client, konto)
        neu = await refresh(client, tokens["refresh_token"])
        assert neu.status_code == 200, neu.text
        assert neu.json()["refresh_token"] != tokens["refresh_token"]

        # Das alte noch einmal: jemand hat mitgelesen — die Familie stirbt.
        alt = await refresh(client, tokens["refresh_token"])
        assert alt.status_code == 400
        auch_neu = await refresh(client, neu.json()["refresh_token"])
        assert auch_neu.status_code == 400


async def test_passwortwechsel_beendet_die_kette(konto):
    async with app_umgebung() as client:
        tokens = await anmelden(client, konto)
        async with AsyncSessionLocal() as db:
            (await db.get(User, konto["user"].id)).token_version += 1
            await db.commit()
        r = await refresh(client, tokens["refresh_token"])
        assert r.status_code == 400
        assert r.json()["error"] == "invalid_grant"
        # Das Access-Token ist ebenfalls tot (tv im Token).
        me = await client.get("/api/auth/me", headers={"Authorization": f"Bearer {tokens['access_token']}"})
        assert me.status_code == 401


async def test_rausschmiss_beendet_die_kette(konto):
    async with app_umgebung() as client:
        tokens = await anmelden(client, konto)
        async with AsyncSessionLocal() as db:
            await db.execute(delete(UserOrganization).where(UserOrganization.user_id == konto["user"].id))
            await db.commit()
        r = await refresh(client, tokens["refresh_token"])
        assert r.status_code == 400
        assert r.json()["error"] == "invalid_grant"


async def test_fremde_organisation_endet_mit_access_denied(konto):
    async with app_umgebung() as client:
        _verifier, challenge = pkce()
        ticket = await authorize(client, konto["fremd"].slug, challenge)
        # Angemeldet in der fremden Organisation (Cookie dieses Slugs), aber
        # ohne Mitgliedschaft — eine andere wird nicht angeboten.
        sitzung(client, konto["user"], konto["fremd"])
        r = await entscheiden(client, ticket)
        assert r.status_code == 200, r.text
        assert rueckgabe(r.json()["redirect_url"])["error"] == "access_denied"


async def test_aeltere_sitzung_verlangt_einen_klick(konto):
    async with app_umgebung() as client:
        verifier, challenge = pkce()
        ticket = await authorize(client, konto["org"].slug, challenge)
        sitzung(client, konto["user"], konto["org"],
                iat=datetime.now(timezone.utc) - timedelta(hours=2))

        r = await entscheiden(client, ticket)
        assert r.status_code == 409
        assert r.json()["detail"]["bestaetigen"] is True
        assert r.json()["detail"]["email"] == konto["user"].email

        r = await entscheiden(client, ticket, bestaetigt=True)
        assert r.status_code == 200
        code = rueckgabe(r.json()["redirect_url"])["code"]
        client.cookies.clear()
        assert (await token_tausch(client, code, verifier)).status_code == 200


async def test_ohne_sitzung_401_und_nur_das_cookie_der_organisation_zaehlt(konto):
    async with app_umgebung() as client:
        _verifier, challenge = pkce()
        ticket = await authorize(client, konto["org"].slug, challenge)
        assert (await entscheiden(client, ticket)).status_code == 401
        # Eine Sitzung in einer anderen Organisation reicht nicht.
        sitzung(client, konto["user"], konto["fremd"])
        assert (await entscheiden(client, ticket)).status_code == 401


async def test_ohne_csrf_kopf_kein_code(konto):
    async with app_umgebung() as client:
        _verifier, challenge = pkce()
        ticket = await authorize(client, konto["org"].slug, challenge)
        sitzung(client, konto["user"], konto["org"])
        r = await client.post("/api/oauth/app/anfrage", json={"request": ticket})
        assert r.status_code == 403


async def test_abbrechen(konto):
    async with app_umgebung() as client:
        _verifier, challenge = pkce()
        ticket = await authorize(client, konto["org"].slug, challenge)
        r = await entscheiden(client, ticket, abbrechen=True)
        assert rueckgabe(r.json()["redirect_url"])["error"] == "access_denied"


async def test_falscher_verifier_kein_token(konto):
    async with app_umgebung() as client:
        _verifier, challenge = pkce()
        ticket = await authorize(client, konto["org"].slug, challenge)
        sitzung(client, konto["user"], konto["org"])
        code = rueckgabe((await entscheiden(client, ticket)).json()["redirect_url"])["code"]
        client.cookies.clear()
        r = await token_tausch(client, code, "falscher-verifier-" + "x" * 30)
        assert r.status_code == 400


async def test_authorize_ohne_org_oder_mit_fremder_uri(konto):
    async with app_umgebung() as client:
        _verifier, challenge = pkce()
        params = {
            "client_id": app_client.CLIENT_ID, "redirect_uri": app_client.REDIRECT_URI,
            "response_type": "code", "code_challenge": challenge, "code_challenge_method": "S256",
            "state": "zustand-123",
        }
        ohne_org = await client.get("/authorize", params=params)
        assert ohne_org.status_code == 302
        assert "error=invalid_request" in ohne_org.headers["location"]
        assert ohne_org.headers["location"].startswith(app_client.REDIRECT_URI)

        fremd = await client.get(
            "/authorize",
            params={**params, "org_slug": konto["org"].slug, "redirect_uri": "de.boese.app:/oauth"},
        )
        # Nicht registrierte Zieladresse: keine Weiterleitung, direkte Absage.
        assert fremd.status_code == 400

        andere_resource = await client.get(
            "/authorize",
            params={**params, "org_slug": konto["org"].slug, "resource": f"{BASE}/mcp"},
        )
        assert "error=invalid_target" in andere_resource.headers["location"]


async def test_abgeschaltet_gibt_es_den_client_nicht(konto):
    async with app_umgebung() as client:
        settings.app_oauth_enabled = False
        _verifier, challenge = pkce()
        r = await client.get(
            "/authorize",
            params={
                "client_id": app_client.CLIENT_ID, "redirect_uri": app_client.REDIRECT_URI,
                "response_type": "code", "code_challenge": challenge, "org_slug": konto["org"].slug,
            },
        )
        assert r.status_code == 400
        version = await client.get("/api/version")
        assert version.json()["app_oauth"] is None
        # MCP und App aus: die AS-Routen gibt es dann gar nicht mehr.
        mcp_mount._anwenden(False)
        meta = await client.get("/.well-known/oauth-authorization-server")
        assert meta.status_code == 404


async def test_auskunft_und_metadaten_ohne_mcp(konto):
    async with app_umgebung() as client:
        version = (await client.get("/api/version")).json()
        assert version["app_oauth"] == {
            "client_id": app_client.CLIENT_ID,
            "redirect_uri": app_client.REDIRECT_URI,
            "authorization_endpoint": f"{BASE}/authorize",
            "token_endpoint": f"{BASE}/token",
        }
        meta = (await client.get("/.well-known/oauth-authorization-server")).json()
        assert meta["authorization_endpoint"] == f"{BASE}/authorize"
        assert meta["token_endpoint"] == f"{BASE}/token"
        assert meta["revocation_endpoint"] == f"{BASE}/revoke"
        # Daran erkennt die App den Browser-Weg (Convoyplan-Companion#89).
        assert meta["convoyplan_app_client_id"] == app_client.CLIENT_ID
        assert "S256" in meta["code_challenge_methods_supported"]
        # Nichts ankündigen, was es ohne MCP nicht gibt.
        assert "registration_endpoint" not in meta
        assert "scopes_supported" not in meta
        assert (await client.post("/register", json={})).status_code == 404


async def test_mcp_client_kommt_ohne_mcp_nicht_an_token(konto):
    """``/token`` ist jetzt auch ohne MCP montiert — eine MCP-Verbindung darf
    dort trotzdem nichts mehr tauschen."""
    client_id = f"mcp-test-{uuid.uuid4().hex[:8]}"
    async with AsyncSessionLocal() as db:
        db.add(OAuthClient(client_id=client_id, client_name="MCP", redirect_uris=["http://127.0.0.1/cb"],
                           grant_types=["authorization_code", "refresh_token"]))
        await db.flush()
        roh = await oauth_tokens.mint_refresh_token(
            db, family_id=uuid.uuid4(), client_id=client_id, user_id=konto["user"].id,
            organization_id=konto["org"].id, scopes=["convoy:read"], resource=None,
        )
        await db.commit()
    try:
        async with app_umgebung() as client:
            r = await client.post(
                "/token", data={"grant_type": "refresh_token", "refresh_token": roh, "client_id": client_id}
            )
            assert r.status_code == 400
            assert r.json()["error"] == "invalid_grant"
    finally:
        async with AsyncSessionLocal() as db:
            await db.execute(delete(OAuthClient).where(OAuthClient.client_id == client_id))
            await db.commit()


async def test_rest_api_lehnt_fremde_audience_ab(konto):
    """Ein typ="access"-Token mit einer anderen Audience als der REST-API
    dieser Instanz gilt hier nicht — die Prüfung steht ausdrücklich in
    ``deps._decode_token``, weil PyJWT sie dort nicht selbst macht."""
    async with app_umgebung() as client:
        user, org = konto["user"], konto["org"]
        def token(aud: str | None) -> str:
            claims = {
                "sub": str(user.id), "exp": datetime.now(timezone.utc) + timedelta(minutes=5),
                "typ": "access", "org_id": str(org.id), "org_slug": org.slug, "role": "planer",
                "tv": user.token_version,
            }
            if aud is not None:
                claims["aud"] = aud
            return _jwt.encode(claims, settings.jwt_secret, algorithm=settings.jwt_algorithm)

        for aud, erwartet in ((None, 200), (app_client.api_resource_url(), 200), (f"{BASE}/mcp", 401),
                              ("https://andere-instanz.example/api", 401)):
            r = await client.get("/api/auth/me", headers={"Authorization": f"Bearer {token(aud)}"})
            assert r.status_code == erwartet, (aud, r.text)
