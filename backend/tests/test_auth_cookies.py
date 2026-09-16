"""Die Sitzung im HttpOnly-Cookie: Setzen, Auswählen, CSRF, Abmelden.

Geprüft wird vor allem, was schiefgehen kann. Dass eine Anmeldung ein Cookie
setzt, sieht man beim ersten Klick; dass ein Cookie ohne CSRF-Kopf *nicht*
schreiben darf und dass ein ``X-Org-Slug`` nicht auf eine fremde Sitzung
zeigen kann, sieht man erst, wenn es zu spät ist.
"""
import uuid
from unittest.mock import AsyncMock, MagicMock

import bcrypt
import pytest
from httpx import ASGITransport, AsyncClient

from app.api import cookies
from app.config import settings
from app.database import get_db
from app.main import app
from app.models.organization import Organization, UserOrganization
from app.models.user import User

pytestmark = pytest.mark.asyncio

BASE = "http://test"


# ── Hilfen ───────────────────────────────────────────────────────────────


def _user(email="test@example.com", pw="secret", superadmin=False):
    u = MagicMock(spec=User)
    u.id = uuid.uuid4()
    u.email = email
    u.is_active = True
    u.is_superadmin = superadmin
    u.mfa_enabled = False
    u.mfa_secret = None
    u.token_version = 0
    u.hashed_password = bcrypt.hashpw(pw.encode(), bcrypt.gensalt()).decode()
    return u


def _org(slug="test-org", name="Test Org"):
    o = MagicMock(spec=Organization)
    o.id = uuid.uuid4()
    o.slug = slug
    o.name = name
    return o


def _membership(role="planer"):
    m = MagicMock(spec=UserOrganization)
    m.role = role
    return m


def _mock_db(*execute_returns, get_returns=None) -> AsyncMock:
    db = AsyncMock()
    ergebnisse = []
    for val in execute_returns:
        r = MagicMock()
        r.scalar_one_or_none.return_value = val
        ergebnisse.append(r)
    db.execute.side_effect = ergebnisse
    if get_returns is not None:
        db.get.side_effect = list(get_returns)
    return db


def _db_override(db: AsyncMock):
    async def _override():
        yield db
    return _override


async def _login_org(db):
    app.dependency_overrides[get_db] = _db_override(db)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url=BASE) as client:
            return await client.post(
                "/api/auth/login",
                json={"email": "test@example.com", "password": "secret",
                      "org_slug": "test-org"},
            )
    finally:
        app.dependency_overrides.pop(get_db, None)


# ── Das Cookie ───────────────────────────────────────────────────────────


async def test_org_login_setzt_httponly_cookie():
    resp = await _login_org(_mock_db(_user(), _org(), _membership()))
    assert resp.status_code == 200

    roh = resp.headers.get_list("set-cookie")
    treffer = [c for c in roh if c.startswith("cp_session__test-org=")]
    assert treffer, roh
    keks = treffer[0]
    assert "HttpOnly" in keks
    assert "SameSite=lax" in keks.replace("samesite", "SameSite")
    assert "Path=/" in keks
    # Der Wert ist dasselbe Token, das auch im Rumpf steht — der Rumpf bleibt
    # für API-Clients erhalten, das Portal rührt ihn nicht mehr an.
    assert resp.cookies["cp_session__test-org"] == resp.json()["access_token"]


async def test_superadmin_login_setzt_das_globale_cookie():
    db = _mock_db(_user(superadmin=True))
    app.dependency_overrides[get_db] = _db_override(db)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url=BASE) as client:
            resp = await client.post(
                "/api/auth/login",
                json={"email": "test@example.com", "password": "secret"},
            )
    finally:
        app.dependency_overrides.pop(get_db, None)

    assert resp.status_code == 200
    assert "cp_session" in resp.cookies
    assert "cp_session__" not in "".join(resp.headers.get_list("set-cookie"))


def test_secure_flag_haengt_an_der_basis_adresse():
    """Nicht am Schema der Anfrage.

    Hinter dem Reverse Proxy spricht das Backend unverschlüsselt und uvicorn
    läuft ohne ``--proxy-headers``; ``request.url.scheme`` wäre in Produktion
    also immer ``http`` und das Sitzungs-Cookie nie ``Secure``. Genau der
    Fehler, der die ganze Umstellung wieder aufheben würde."""
    vorher = settings.app_base_url
    try:
        settings.app_base_url = "https://web.convoyplan.de"
        assert cookies.cookie_secure() is True
        settings.app_base_url = "http://localhost:5173"
        assert cookies.cookie_secure() is False
    finally:
        settings.app_base_url = vorher


# ── Auswahl über X-Org-Slug ──────────────────────────────────────────────


def test_cookie_name_je_organisation():
    assert cookies.cookie_name(None) == "cp_session"
    assert cookies.cookie_name("feuerwehr-a") == "cp_session__feuerwehr-a"


def test_ohne_slug_gilt_die_globale_sitzung():
    """Es wird nicht geraten: schickt der Browser mehrere
    Organisationssitzungen und nennt niemand eine, gibt es keine Anmeldung.
    Eine geratene ist schlimmer als gar keine."""
    from tests.fake_request import fake_request

    req = fake_request(cookies={"cp_session__a": "tok-a", "cp_session__b": "tok-b"})
    assert cookies.token_from_cookie(req) is None

    req2 = fake_request(
        headers={"X-Org-Slug": "b"},
        cookies={"cp_session__a": "tok-a", "cp_session__b": "tok-b"},
    )
    assert cookies.token_from_cookie(req2) == "tok-b"


def test_fremder_slug_findet_keine_sitzung():
    from tests.fake_request import fake_request

    req = fake_request(
        headers={"X-Org-Slug": "fremd"}, cookies={"cp_session__eigen": "tok"}
    )
    assert cookies.token_from_cookie(req) is None


def test_session_slugs_listet_nur_echte_organisationssitzungen():
    from tests.fake_request import fake_request

    req = fake_request(
        cookies={
            "cp_session": "global",
            "cp_session__a": "x",
            "cp_session__b": "y",
            # Kein Slug hinter dem Trenner — kein Eintrag.
            "cp_session__": "z",
            "etwas_anderes": "q",
        }
    )
    assert sorted(cookies.session_slugs(req)) == ["a", "b"]


# ── CSRF ─────────────────────────────────────────────────────────────────


def _token(user, org=None, role=None, superadmin=False):
    from app.api.routes.auth import create_token

    return create_token(
        str(user.id), superadmin,
        str(org.id) if org else None, org.slug if org else None,
        role, user.token_version,
    )


# ``/api/auth/stream-ticket`` ist für diese drei Prüfungen der passende
# Endpunkt: POST, verlangt eine Anmeldung, und was er danach tut, ist eine
# Zeile. Damit steht im Ergebnis die Anmeldung und nicht die Fachlogik.


async def test_schreiben_per_cookie_ohne_csrf_kopf_wird_abgelehnt():
    """Der Kern des Cookie-Risikos: der Browser schickt es von sich aus mit,
    auch wenn eine fremde Seite die Anfrage ausgelöst hat."""
    user, org = _user(), _org()
    db = _mock_db(user)
    app.dependency_overrides[get_db] = _db_override(db)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url=BASE) as client:
            client.cookies.set("cp_session__test-org", _token(user, org, "planer"))
            resp = await client.post(
                "/api/auth/stream-ticket", headers={"X-Org-Slug": "test-org"}
            )
    finally:
        app.dependency_overrides.pop(get_db, None)

    assert resp.status_code == 403
    assert "X-Requested-With" in resp.json()["detail"]


async def test_schreiben_per_cookie_mit_csrf_kopf_geht_durch():
    user, org = _user(), _org()
    db = _mock_db(user)
    app.dependency_overrides[get_db] = _db_override(db)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url=BASE) as client:
            client.cookies.set("cp_session__test-org", _token(user, org, "planer"))
            resp = await client.post(
                "/api/auth/stream-ticket",
                headers={"X-Org-Slug": "test-org", "X-Requested-With": "ConvoyPlan"},
            )
    finally:
        app.dependency_overrides.pop(get_db, None)

    assert resp.status_code == 200, resp.text
    assert resp.json()["ticket"]


async def test_falscher_csrf_wert_reicht_nicht():
    """Der Header muss den vereinbarten Wert tragen — sonst genügte es, ihn
    irgendwie zu setzen, und ein Wert, den jeder raten kann, ist keiner."""
    user, org = _user(), _org()
    db = _mock_db(user)
    app.dependency_overrides[get_db] = _db_override(db)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url=BASE) as client:
            client.cookies.set("cp_session__test-org", _token(user, org, "planer"))
            resp = await client.post(
                "/api/auth/stream-ticket",
                headers={"X-Org-Slug": "test-org", "X-Requested-With": "XMLHttpRequest"},
            )
    finally:
        app.dependency_overrides.pop(get_db, None)

    assert resp.status_code == 403


async def test_lesen_per_cookie_braucht_keinen_csrf_kopf():
    """Ein GET verändert nichts — der Schutz gilt den ändernden Methoden."""
    user, org = _user(), _org()
    db = _mock_db(user, _membership("planer"), get_returns=[org])
    app.dependency_overrides[get_db] = _db_override(db)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url=BASE) as client:
            client.cookies.set("cp_session__test-org", _token(user, org, "planer"))
            resp = await client.get("/api/auth/me", headers={"X-Org-Slug": "test-org"})
    finally:
        app.dependency_overrides.pop(get_db, None)

    assert resp.status_code == 200, resp.text


async def test_bearer_braucht_keinen_csrf_kopf():
    """Wer einen Authorization-Header setzen kann, ist kein fremder Ursprung —
    der Weg für Skripte und API-Clients bleibt unverändert."""
    user, org = _user(), _org()
    db = _mock_db(user)
    app.dependency_overrides[get_db] = _db_override(db)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url=BASE) as client:
            resp = await client.post(
                "/api/auth/stream-ticket",
                headers={"Authorization": f"Bearer {_token(user, org, 'planer')}"},
            )
    finally:
        app.dependency_overrides.pop(get_db, None)

    assert resp.status_code == 200, resp.text


# ── /me ──────────────────────────────────────────────────────────────────


async def test_me_ohne_sitzung_ist_401():
    async with AsyncClient(transport=ASGITransport(app=app), base_url=BASE) as client:
        resp = await client.get("/api/auth/me")
    assert resp.status_code == 401


async def test_me_liefert_die_rolle_aus_der_datenbank():
    """Nicht die aus dem Token.

    Das Token trägt die Rolle vom Anmeldezeitpunkt und gilt sieben Tage. Wer
    zwischendurch herabgestuft wird, soll das beim nächsten Laden merken und
    nicht eine Woche später."""
    user, org = _user(), _org()
    # Token sagt "admin", die Mitgliedschaft sagt inzwischen "beobachter".
    token = _token(user, org, "admin")
    db = _mock_db(user, _membership("beobachter"), get_returns=[org])
    app.dependency_overrides[get_db] = _db_override(db)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url=BASE) as client:
            client.cookies.set("cp_session__test-org", token)
            resp = await client.get("/api/auth/me", headers={"X-Org-Slug": "test-org"})
    finally:
        app.dependency_overrides.pop(get_db, None)

    assert resp.status_code == 200, resp.text
    daten = resp.json()
    assert daten["role"] == "beobachter"
    assert daten["org_slug"] == "test-org"
    assert daten["org_name"] == "Test Org"
    assert daten["email"] == user.email


async def test_me_lehnt_ab_wenn_die_mitgliedschaft_weg_ist():
    user, org = _user(), _org()
    db = _mock_db(user, None, get_returns=[org])
    app.dependency_overrides[get_db] = _db_override(db)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url=BASE) as client:
            client.cookies.set("cp_session__test-org", _token(user, org, "planer"))
            resp = await client.get("/api/auth/me", headers={"X-Org-Slug": "test-org"})
    finally:
        app.dependency_overrides.pop(get_db, None)

    assert resp.status_code == 403


# ── Abmelden ─────────────────────────────────────────────────────────────


async def test_logout_loescht_alle_sitzungen():
    """Ohne nähere Angabe heißt „abmelden", dass danach niemand mehr
    angemeldet ist — ein Rest, der irgendwo weiterlebt, wäre die
    Überraschung, die man hier nicht will."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url=BASE) as client:
        client.cookies.set("cp_session", "global")
        client.cookies.set("cp_session__a", "tok-a")
        client.cookies.set("cp_session__b", "tok-b")
        resp = await client.post("/api/auth/logout")

    assert resp.status_code == 200
    geloescht = "".join(resp.headers.get_list("set-cookie"))
    for name in ("cp_session=", "cp_session__a=", "cp_session__b="):
        assert name in geloescht, geloescht


async def test_logout_mit_slug_trifft_nur_diese_organisation():
    async with AsyncClient(transport=ASGITransport(app=app), base_url=BASE) as client:
        client.cookies.set("cp_session__a", "tok-a")
        client.cookies.set("cp_session__b", "tok-b")
        resp = await client.post("/api/auth/logout", headers={"X-Org-Slug": "a"})

    gesetzt = resp.headers.get_list("set-cookie")
    assert any(c.startswith("cp_session__a=") for c in gesetzt), gesetzt
    assert not any(c.startswith("cp_session__b=") for c in gesetzt), gesetzt


async def test_logout_braucht_keine_gueltige_sitzung():
    """Ein Abmelden, das an einem abgelaufenen Token scheitert, ließe das
    Cookie stehen."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url=BASE) as client:
        client.cookies.set("cp_session", "laengst-abgelaufener-mist")
        resp = await client.post("/api/auth/logout")
    assert resp.status_code == 200
