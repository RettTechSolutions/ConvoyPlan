"""Gemeinsame Hilfen für die MCP-Tests.

Diese Tests sind — anders als der Rest der Test-Suite — **datenbankgestützt**.
Das ist Absicht: geprüft werden der OAuth-Fluss, die Mandantentrennung und
die Wiederverwendungserkennung bei Tokens. Alles davon lebt in Zeilen und in
Nebenläufigkeit; mit Mocks würde man die Attrappe testen, nicht die Sache.

CI hält dafür bereits eine PostGIS-Instanz vor und spielt vor dem Testlauf
die Migrationen ein.
"""
import base64
import contextlib
import hashlib
import json
import uuid
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qs, urlparse

import jwt as _jwt
import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete

from app.api.routes import mcp_consent as mcp_consent_router
from app.config import settings
from app.database import AsyncSessionLocal, engine
from app.mcp import mount as mcp_mount
from app.models.convoy import Convoy, ConvoyVehicle
from app.models.oauth_client import OAuthClient
from app.models.oauth_code import OAuthCode
from app.models.oauth_refresh_token import OAuthRefreshToken
from app.models.organization import Organization, UserOrganization
from app.models.user import User
from app.models.vehicle import Vehicle

BASE_URL = "https://mcp-test.convoyplan.invalid"
MCP_HEADERS = {
    "Content-Type": "application/json",
    "Accept": "application/json, text/event-stream",
}
PROTOCOL_VERSION = "2025-06-18"
# Der erste Aufruf jeder MCP-Sitzung. Genügt, um zu prüfen, ob der Endpunkt
# überhaupt jemanden durchlässt — dafür braucht es keine fertige Sitzung.
INIT_REQUEST = {
    "jsonrpc": "2.0",
    "id": 1,
    "method": "initialize",
    "params": {
        "protocolVersion": PROTOCOL_VERSION,
        "capabilities": {},
        "clientInfo": {"name": "convoyplan-tests", "version": "0"},
    },
}


@pytest.fixture(autouse=True)
async def reset_db_engine():
    """Den Verbindungspool nach jedem Test schließen.

    ``app/database.py`` legt die Engine beim Import an, pytest-asyncio gibt
    jedem Test eine eigene Event-Loop (``asyncio_default_fixture_loop_scope
    = "function"``, siehe pyproject.toml). Eine gepoolte asyncpg-Verbindung
    gehört aber der Loop, die sie geöffnet hat — im nächsten Test scheitert
    sie mit "attached to a different loop". Andere Testmodule merken davon
    nichts, weil sie die Datenbank gar nicht anfassen."""
    yield
    await engine.dispose()


def pkce_pair() -> tuple[str, str]:
    """(verifier, challenge) für PKCE S256."""
    verifier = base64.urlsafe_b64encode(uuid.uuid4().bytes * 2).decode().rstrip("=")
    digest = hashlib.sha256(verifier.encode()).digest()
    return verifier, base64.urlsafe_b64encode(digest).decode().rstrip("=")


@contextlib.asynccontextmanager
async def mcp_app():
    """Eine FastAPI-App mit montiertem MCP-Server und laufendem Transport.

    Bewusst eine frische App statt ``app.main.app``: dort wird beim Import
    entschieden, ob MCP montiert wird, und das lässt sich pro Test nicht
    mehr umstellen, ohne Routen dauerhaft anzuhängen."""
    previous = settings.mcp_enabled, settings.app_base_url, settings.mcp_public_url
    settings.mcp_enabled = True
    settings.app_base_url = BASE_URL
    settings.mcp_public_url = ""
    try:
        app = FastAPI(lifespan=lambda _app: mcp_mount.lifespan_context())
        app.include_router(mcp_consent_router.router, prefix="/api")
        mcp_mount.mount(app)
        async with app.router.lifespan_context(app):
            # Ausdrücklich einschalten statt auf den Lifespan zu vertrauen:
            # der liest den Laufzeitschalter aus der Datenbank, und eine dort
            # liegengebliebene "mcp.enabled=false"-Zeile würde diese Tests
            # sonst still ohne Routen laufen lassen — mit Fehlern, die nach
            # allem Möglichen aussehen, nur nicht nach der Ursache.
            mcp_mount.aktivieren()
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url=BASE_URL
            ) as client:
                yield app, client
    finally:
        settings.mcp_enabled, settings.app_base_url, settings.mcp_public_url = previous
        mcp_mount.deaktivieren()
        mcp_mount._session_manager = None
        mcp_mount._app = None
        mcp_mount._routes = []


class Fixtures:
    """Die angelegten Zeilen, damit die Tests sie benennen können."""

    def __init__(self) -> None:
        self.org_a: Organization
        self.org_b: Organization
        self.planer: User
        self.beobachter: User
        self.convoy_a: Convoy
        self.convoy_b: Convoy
        self.vehicle_a: Vehicle


@contextlib.asynccontextmanager
async def seeded():
    """Zwei Organisationen mit je einem Konvoi, dazu zwei Benutzer.

    ``planer`` ist Planer in Organisation A **und** Mitglied in B — so lässt
    sich prüfen, dass ein Token für A trotzdem nichts aus B sieht. Die
    Mandantentrennung hängt am Token, nicht an der Kontoberechtigung."""
    marker = uuid.uuid4().hex[:8]
    fx = Fixtures()
    async with AsyncSessionLocal() as db:
        fx.planer = User(
            email=f"planer-{marker}@mcp.invalid", hashed_password="x", is_active=True
        )
        fx.beobachter = User(
            email=f"beob-{marker}@mcp.invalid", hashed_password="x", is_active=True
        )
        db.add_all([fx.planer, fx.beobachter])
        await db.flush()

        fx.org_a = Organization(
            name=f"Org A {marker}", slug=f"org-a-{marker}", owner_id=fx.planer.id
        )
        fx.org_b = Organization(
            name=f"Org B {marker}", slug=f"org-b-{marker}", owner_id=fx.planer.id
        )
        db.add_all([fx.org_a, fx.org_b])
        await db.flush()

        db.add_all(
            [
                UserOrganization(
                    user_id=fx.planer.id, organization_id=fx.org_a.id, role="planer"
                ),
                UserOrganization(
                    user_id=fx.planer.id, organization_id=fx.org_b.id, role="planer"
                ),
                UserOrganization(
                    user_id=fx.beobachter.id,
                    organization_id=fx.org_a.id,
                    role="beobachter",
                ),
            ]
        )

        fx.convoy_a = Convoy(
            name=f"Marschverband A {marker}",
            organization_id=fx.org_a.id,
            owner_id=fx.planer.id,
        )
        fx.convoy_b = Convoy(
            name=f"Marschverband B {marker}",
            organization_id=fx.org_b.id,
            owner_id=fx.planer.id,
        )
        fx.vehicle_a = Vehicle(
            name=f"ELW {marker}", callsign="Florian 1", org_id=fx.org_a.id,
            owner_id=fx.planer.id,
        )
        db.add_all([fx.convoy_a, fx.convoy_b, fx.vehicle_a])
        await db.flush()
        db.add(
            ConvoyVehicle(
                convoy_id=fx.convoy_a.id, vehicle_id=fx.vehicle_a.id,
                position=0, vehicle_status="planned",
            )
        )
        await db.commit()
        for obj in (fx.planer, fx.beobachter, fx.org_a, fx.org_b,
                    fx.convoy_a, fx.convoy_b, fx.vehicle_a):
            db.expunge(obj)

    try:
        yield fx
    finally:
        async with AsyncSessionLocal() as db:
            org_ids = [fx.org_a.id, fx.org_b.id]
            user_ids = [fx.planer.id, fx.beobachter.id]
            await db.execute(
                delete(OAuthRefreshToken).where(
                    OAuthRefreshToken.organization_id.in_(org_ids)
                )
            )
            await db.execute(
                delete(OAuthCode).where(OAuthCode.organization_id.in_(org_ids))
            )
            await db.execute(
                delete(ConvoyVehicle).where(
                    ConvoyVehicle.convoy_id.in_([fx.convoy_a.id, fx.convoy_b.id])
                )
            )
            await db.execute(delete(Vehicle).where(Vehicle.org_id.in_(org_ids)))
            await db.execute(delete(Convoy).where(Convoy.organization_id.in_(org_ids)))
            await db.execute(
                delete(UserOrganization).where(
                    UserOrganization.organization_id.in_(org_ids)
                )
            )
            await db.execute(delete(Organization).where(Organization.id.in_(org_ids)))
            await db.execute(delete(User).where(User.id.in_(user_ids)))
            await db.commit()


async def purge_clients(client_ids: list[str]) -> None:
    async with AsyncSessionLocal() as db:
        await db.execute(delete(OAuthClient).where(OAuthClient.client_id.in_(client_ids)))
        await db.commit()


def convoyplan_access_token(user: User, org: Organization) -> str:
    """Ein ganz normales ConvoyPlan-Token (typ="access") — für die Prüfung,
    dass es am MCP-Endpunkt nichts ausrichtet."""
    return _jwt.encode(
        {
            "sub": str(user.id),
            "exp": datetime.now(timezone.utc) + timedelta(hours=1),
            "typ": "access",
            "is_superadmin": False,
            "org_id": str(org.id),
            "org_slug": org.slug,
            "role": "planer",
            "tv": user.token_version,
        },
        settings.jwt_secret,
        algorithm=settings.jwt_algorithm,
    )


# ── Den vollständigen Autorisierungsfluss durchlaufen ────────────────────


async def register_client(
    client: AsyncClient,
    redirect_uri: str = "http://127.0.0.1:33418/cb",
    scope: str | None = None,
) -> dict:
    body = {
        "redirect_uris": [redirect_uri],
        "client_name": "Testclient",
        "grant_types": ["authorization_code", "refresh_token"],
        "response_types": ["code"],
    }
    if scope:
        body["scope"] = scope
    resp = await client.post("/register", json=body)
    assert resp.status_code == 201, resp.text
    return resp.json()


async def authorize(
    client: AsyncClient, reg: dict, challenge: str, scopes: list[str] | None = None
) -> str:
    """/authorize aufrufen und das Consent-Ticket aus der Weiterleitung holen."""
    params = {
        "client_id": reg["client_id"],
        "redirect_uri": reg["redirect_uris"][0],
        "response_type": "code",
        "code_challenge": challenge,
        "code_challenge_method": "S256",
        "resource": f"{BASE_URL}/mcp",
    }
    if scopes:
        params["scope"] = " ".join(scopes)
    resp = await client.get("/authorize", params=params)
    assert resp.status_code in (302, 307), resp.text
    location = resp.headers["location"]
    assert location.startswith(f"{BASE_URL}/oauth/consent"), location
    ticket = parse_qs(urlparse(location).query)["request"][0]
    return ticket


async def consent(
    client: AsyncClient,
    ticket: str,
    user: User,
    org: Organization,
    *,
    approve: bool = True,
    scopes: list[str] | None = None,
) -> str:
    """Auf dem Consent-Screen zustimmen und den Autorisierungscode holen.

    ``scopes`` ist die Auswahl des Menschen auf dem Bildschirm. ``None``
    heißt „nichts angekreuzt oder abgewählt" und erteilt das Angefragte."""
    bearer = convoyplan_access_token(user, org)
    resp = await client.post(
        "/api/mcp/consent",
        json={
            "request": ticket,
            "approve": approve,
            "organization_id": str(org.id) if approve else None,
            "scopes": scopes,
        },
        headers={"Authorization": f"Bearer {bearer}"},
    )
    assert resp.status_code == 200, resp.text
    redirect_url = resp.json()["redirect_url"]
    params = parse_qs(urlparse(redirect_url).query)
    # RFC 9207: der Absender gehört in jede Antwort, auch in die Absage.
    assert params["iss"] == [BASE_URL], params
    if not approve:
        assert params["error"] == ["access_denied"]
        return ""
    return params["code"][0]


async def exchange_code(
    client: AsyncClient, reg: dict, code: str, verifier: str
) -> dict:
    resp = await client.post(
        "/token",
        data={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": reg["redirect_uris"][0],
            "client_id": reg["client_id"],
            "client_secret": reg.get("client_secret", ""),
            "code_verifier": verifier,
            "resource": f"{BASE_URL}/mcp",
        },
    )
    return {"status": resp.status_code, "body": resp.json()}


async def connect(
    client: AsyncClient,
    user: User,
    org: Organization,
    scopes: list[str] | None = None,
    *,
    zustimmung: list[str] | None = None,
) -> tuple[dict, dict]:
    """Registrieren, autorisieren, zustimmen, Token holen — in einem Rutsch.

    ``scopes`` ist, was der Client verlangt; ``zustimmung`` das, was der
    Mensch auf dem Bildschirm ankreuzt. Ohne ``zustimmung`` bleibt es beim
    Angefragten.

    Gibt (Registrierung, Token-Antwort) zurück."""
    reg = await register_client(client, scope=" ".join(scopes) if scopes else None)
    verifier, challenge = pkce_pair()
    ticket = await authorize(client, reg, challenge, scopes)
    code = await consent(client, ticket, user, org, scopes=zustimmung)
    result = await exchange_code(client, reg, code, verifier)
    assert result["status"] == 200, result
    return reg, result["body"]


async def mcp_session(client: AsyncClient, access_token: str) -> str:
    """Eine MCP-Sitzung eröffnen und die Session-Id zurückgeben."""
    auth = {"Authorization": f"Bearer {access_token}"}
    resp = await client.post("/mcp", json=INIT_REQUEST, headers={**MCP_HEADERS, **auth})
    assert resp.status_code == 200, resp.text
    session_id = resp.headers["mcp-session-id"]
    await client.post(
        "/mcp",
        json={"jsonrpc": "2.0", "method": "notifications/initialized"},
        headers={**MCP_HEADERS, **auth, "mcp-session-id": session_id,
                 "MCP-Protocol-Version": PROTOCOL_VERSION},
    )
    return session_id


async def call(
    client: AsyncClient, access_token: str, session_id: str, method: str, params: dict | None = None
) -> dict:
    """Einen JSON-RPC-Aufruf in einer bestehenden Sitzung absetzen."""
    resp = await client.post(
        "/mcp",
        json={"jsonrpc": "2.0", "id": 99, "method": method, "params": params or {}},
        headers={
            **MCP_HEADERS,
            "Authorization": f"Bearer {access_token}",
            "mcp-session-id": session_id,
            "MCP-Protocol-Version": PROTOCOL_VERSION,
        },
    )
    assert resp.status_code == 200, resp.text
    for line in resp.text.splitlines():
        if line.startswith("data: "):
            return json.loads(line[6:])
    return resp.json()


def tool_payload(response: dict) -> dict:
    """Das strukturierte Ergebnis eines Tool-Aufrufs auspacken."""
    result = response.get("result", {})
    if result.get("structuredContent") is not None:
        return result["structuredContent"]
    content = result.get("content") or []
    if content and content[0].get("type") == "text":
        try:
            return json.loads(content[0]["text"])
        except json.JSONDecodeError:
            return {"text": content[0]["text"]}
    return result
