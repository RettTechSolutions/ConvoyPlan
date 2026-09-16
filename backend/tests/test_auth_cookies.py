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


# ── Der Slug aus dem Kopf ist unbesehene Eingabe ─────────────────────────
# Gefunden von CodeQL auf dieser PR: "Construction of a cookie using
# user-supplied input". Einschleusen ließ sich nichts — CPythons Morsel
# lehnt illegale Schlüssel ab —, aber es lehnt sie mit einer CookieError ab,
# und die kam am Abmelde-Endpunkt als 500 heraus.


@pytest.mark.parametrize(
    "boese",
    [
        "a; Path=/; HttpOnly",   # Cookie-Attribut anhängen
        "a=b",                   # Trennzeichen
        "a\nSet-Cookie: x=y",    # Header-Umbruch
        "GROSS",                 # Slugs sind klein
        "-vorne",                # Bindestrich am Rand
        "hinten-",
        "mit leer",
        "a" * 81,                # länger als ein Slug sein kann
        "",
    ],
)
def test_unbrauchbarer_slug_wird_nicht_als_slug_anerkannt(boese):
    assert cookies.ist_gueltiger_slug(boese) is False


@pytest.mark.parametrize("gut", ["a", "org-a", "feuerwehr-muenchen-1", "x1", "a" * 80])
def test_echte_slugs_werden_anerkannt(gut):
    assert cookies.ist_gueltiger_slug(gut) is True


def test_cookie_name_wirft_statt_still_etwas_anderes_zu_bauen():
    """Ein ungültiger Slug ist an dieser Stelle ein Programmierfehler. Still
    auf das globale Cookie auszuweichen wäre die schlechtere Antwort: dann
    setzte ein Tippfehler im Aufrufer die falsche Sitzung."""
    with pytest.raises(ValueError):
        cookies.cookie_name("a; Path=/")


def test_boeser_kopf_zaehlt_wie_kein_kopf():
    from tests.fake_request import fake_request

    req = fake_request(
        headers={"X-Org-Slug": "a; Path=/; HttpOnly"},
        cookies={"cp_session": "global", "cp_session__a": "org"},
    )
    assert cookies.angefragter_slug(req) is None
    # Fällt auf die globale Sitzung zurück — also auf genau das, was der
    # Aufrufer auch ohne den Kopf bekäme. Kein Zugewinn durch Unsinn.
    assert cookies.token_from_cookie(req) == "global"


def test_session_slugs_ueberspringt_was_kein_slug_ist():
    """Die Namen kommen aus dem Browser, nicht zwingend von diesem Server."""
    from tests.fake_request import fake_request

    req = fake_request(cookies={"cp_session__gut": "x", "cp_session__BOESE=y": "z"})
    assert cookies.session_slugs(req) == ["gut"]


async def test_abmelden_mit_praeparieretem_kopf_bricht_nicht():
    """Der eigentliche Fund: vorher 500, jetzt eine normale Antwort."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url=BASE) as client:
        client.cookies.set("cp_session", "global")
        resp = await client.post(
            "/api/auth/logout", headers={"X-Org-Slug": "a; Path=/; HttpOnly"}
        )
    assert resp.status_code == 200
    # Wie ohne Kopf: es wird alles abgemeldet, nicht selektiv nach Unsinn.
    assert any(
        c.startswith("cp_session=") for c in resp.headers.get_list("set-cookie")
    )


# ── Die Systemübersicht ──────────────────────────────────────────────────


async def test_systemuebersicht_per_cookie(monkeypatch):
    """Die Regression hinter der roten Leiste „Not authenticated".

    ``require_system_read`` las nach der Cookie-Umstellung weiter nur den
    ``Authorization``-Kopf — den das Portal seither nicht mehr schickt. Alle
    sieben lesenden Endpunkte der Systemübersicht antworteten damit dem
    angemeldeten Superadmin mit 401, und die Seite blieb leer.

    Geprüft wird über den ASGI-Stack statt über die Dependency allein, weil
    genau die Verdrahtung das Loch hatte: die Unit-Tests der Endpunkte
    überschreiben ``require_system_read`` und hätten es nie gesehen.
    """
    from app.api.routes import system_metrics as route

    monkeypatch.setattr(
        route.system_metrics, "live_snapshot", AsyncMock(return_value={"cpu": {}})
    )
    admin = _user(superadmin=True)
    db = _mock_db(admin)
    app.dependency_overrides[get_db] = _db_override(db)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url=BASE) as client:
            client.cookies.set(cookies.SESSION_COOKIE, _token(admin, superadmin=True))
            resp = await client.get("/api/admin/system/overview")
    finally:
        app.dependency_overrides.pop(get_db, None)

    assert resp.status_code == 200, resp.text
    assert resp.json() == {"cpu": {}}


async def test_systemuebersicht_ohne_sitzung_bleibt_401():
    """Der Weg über das Cookie darf die Tür nicht aufmachen."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url=BASE) as client:
        resp = await client.get("/api/admin/system/overview")
    assert resp.status_code == 401
