"""Der Türsteher vor /docs, /redoc und /openapi.json.

Der Kern dieser Suite ist ``test_query_parameter_is_ignored``: Der API-Key war
früher als ``?key=…`` erlaubt und landete damit in Access-Logs, Browser-History
und potenziell im ``Referer``. Der Weg ist zu, und ein Test hält ihn zu — sonst
schleicht er sich beim nächsten „aber es ist doch bequem" zurück.
"""

from datetime import datetime, timedelta, timezone

import jwt as _jwt
import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.api import docs_ui
from app.config import settings
from app.services import rate_limit

KEY = "docs-key-under-test"


@pytest.fixture
def docs_app(monkeypatch) -> FastAPI:
    """Eine nackte App mit nur den Docs-Routen — ohne Datenbank, Middleware und
    den Rest von ``app.main``. Die Routen dort werden beim Import montiert,
    abhängig von Einstellungen, die ein Test nicht mehr ändern kann."""
    monkeypatch.setattr(settings, "docs_api_key", KEY)
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    docs_ui.register(app)
    return app


def _client(app: FastAPI) -> AsyncClient:
    # https, weil das Sitzungs-Cookie in Produktion Secure gesetzt wird und ein
    # http-Client es sonst gar nicht erst zurueckschickt.
    return AsyncClient(transport=ASGITransport(app=app), base_url="https://test")


@pytest.mark.asyncio
@pytest.mark.parametrize("path", ["/docs", "/redoc", "/openapi.json"])
async def test_query_parameter_is_ignored(docs_app, path):
    """Der korrekte Key im Query-String öffnet nichts mehr."""
    async with _client(docs_app) as client:
        resp = await client.get(path, params={"key": KEY})

    assert resp.status_code == 401
    # Und er hinterlässt auch keine Sitzung, die den nächsten Aufruf öffnet.
    assert docs_ui.COOKIE_NAME not in resp.cookies


@pytest.mark.asyncio
@pytest.mark.parametrize("path", ["/docs", "/redoc", "/openapi.json"])
async def test_api_key_header_still_works(docs_app, path):
    async with _client(docs_app) as client:
        resp = await client.get(path, headers={"X-API-Key": KEY})

    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_wrong_api_key_header_is_rejected(docs_app):
    async with _client(docs_app) as client:
        resp = await client.get("/docs", headers={"X-API-Key": KEY + "x"})

    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_docs_without_credentials_serves_the_login_form(docs_app):
    """401 — aber mit dem Formular im Rumpf, damit der Browser-Einstieg
    ohne Umweg funktioniert."""
    async with _client(docs_app) as client:
        resp = await client.get("/docs")

    assert resp.status_code == 401
    assert 'action="/docs/session"' in resp.text
    assert "swagger" not in resp.text.lower()


@pytest.mark.asyncio
async def test_login_page_is_reachable(docs_app):
    async with _client(docs_app) as client:
        resp = await client.get("/docs/login")

    assert resp.status_code == 200
    assert 'name="key"' in resp.text
    assert 'type="password"' in resp.text


@pytest.mark.asyncio
async def test_session_sets_cookie_and_redirects(docs_app):
    async with _client(docs_app) as client:
        resp = await client.post("/docs/session", data={"key": KEY})

        assert resp.status_code == 303
        assert resp.headers["location"] == "/docs"
        set_cookie = resp.headers["set-cookie"]
        assert docs_ui.COOKIE_NAME in set_cookie
        assert "HttpOnly" in set_cookie
        # Der Key selbst darf den Server nicht wieder verlassen.
        assert KEY not in set_cookie

        # Die Sitzung trägt den Folgeaufruf.
        follow_up = await client.get("/docs")

    assert follow_up.status_code == 200
    assert "swagger" in follow_up.text.lower()


@pytest.mark.asyncio
async def test_session_rejects_a_wrong_key(docs_app):
    async with _client(docs_app) as client:
        resp = await client.post("/docs/session", data={"key": "falsch"})

        assert resp.status_code == 401
        assert "set-cookie" not in resp.headers
        assert 'action="/docs/session"' in resp.text

        assert (await client.get("/docs")).status_code == 401


@pytest.mark.asyncio
async def test_forged_cookie_is_rejected(docs_app):
    """Das Cookie ist mit JWT_SECRET signiert; ein selbstgebautes zählt nicht."""
    forged = _jwt.encode(
        {"docs": True, "exp": datetime.now(timezone.utc) + timedelta(hours=1)},
        "ein-anderes-geheimnis",
        algorithm=settings.jwt_algorithm,
    )
    async with _client(docs_app) as client:
        client.cookies.set(docs_ui.COOKIE_NAME, forged)
        resp = await client.get("/docs")

    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_expired_cookie_is_rejected(docs_app):
    expired = _jwt.encode(
        {"docs": True, "exp": datetime.now(timezone.utc) - timedelta(minutes=1)},
        settings.jwt_secret,
        algorithm=settings.jwt_algorithm,
    )
    async with _client(docs_app) as client:
        client.cookies.set(docs_ui.COOKIE_NAME, expired)
        resp = await client.get("/docs")

    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_session_is_rate_limited(docs_app, monkeypatch):
    """Ohne Begrenzung wäre das Formular ein offener Brute-Force-Pfad auf einen
    Wert, den niemand rotiert. Gleiche Parameter wie beim Login."""
    monkeypatch.setattr(settings, "rate_limit_enabled", True)
    rate_limit.reset()

    async with _client(docs_app) as client:
        for _ in range(10):
            assert (await client.post("/docs/session", data={"key": "falsch"})).status_code == 401

        blocked = await client.post("/docs/session", data={"key": "falsch"})
        assert blocked.status_code == 429
        assert "Retry-After" in blocked.headers

        # Auch der richtige Key kommt jetzt nicht mehr durch.
        assert (await client.post("/docs/session", data={"key": KEY})).status_code == 429

    rate_limit.reset()


@pytest.mark.asyncio
async def test_docs_are_open_when_no_key_is_configured(monkeypatch):
    """Ohne DOCS_API_KEY (Dev, oder ENABLE_DOCS=true) gibt es nichts zu bewachen —
    dann darf auch das Anmeldeformular nicht so tun, als gäbe es das."""
    monkeypatch.setattr(settings, "docs_api_key", "")
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    docs_ui.register(app)

    async with _client(app) as client:
        assert (await client.get("/docs")).status_code == 200
        assert (await client.get("/openapi.json")).status_code == 200

        login = await client.get("/docs/login")
        assert login.status_code == 303
        assert login.headers["location"] == "/docs"

        assert (await client.post("/docs/session", data={"key": "egal"})).status_code == 404


def test_docs_enabled_follows_the_configuration(monkeypatch):
    monkeypatch.setattr(settings, "app_env", "production")
    monkeypatch.setattr(settings, "enable_docs", False)
    monkeypatch.setattr(settings, "docs_api_key", "")
    assert docs_ui.docs_enabled() is False

    monkeypatch.setattr(settings, "docs_api_key", KEY)
    assert docs_ui.docs_enabled() is True

    monkeypatch.setattr(settings, "docs_api_key", "")
    monkeypatch.setattr(settings, "enable_docs", True)
    assert docs_ui.docs_enabled() is True
