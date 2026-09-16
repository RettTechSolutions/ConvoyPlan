"""Wer an den MCP-Zustimmungsbildschirm kommt — und wann es ihn gibt.

Zwei Fehler haben diesen Bildschirm auf einer produktiven Instanz vollständig
unbenutzbar gemacht, jeder für sich allein schon.

Der erste: ``_require_enabled`` las ``settings.mcp_enabled``, also die
Umgebungsvariable. Den Laufzeitschalter im Portal gibt es später, und der
Consent-Router hat den Wechsel auf die Datenbank nicht mitbekommen — er hängt
fest in ``main.py``, außerhalb von ``mcp_mount.mount``. Auf einer Instanz mit
``MCP_ENABLED=false`` und dem Schalter auf „an" zeigte das Portal einen
aktiven MCP-Server, während der Bildschirm mit 404 antwortete.

Der zweite: die Seite liegt unter ``/oauth/consent``, außerhalb jeder
Organisation, und schickt deshalb keinen ``X-Org-Slug`` mit. Die Anfrage fiel
auf die *globale* Sitzung zurück — die bekommt nur, wer sich ohne ``org_slug``
anmeldet, also ein Superadmin. Jedes gewöhnliche Mitglied stand mit gültiger
Anmeldung vor einem 401.

Beide Male half kein Blick in die Logs: der Client meldete nur, dass die
Anmeldung fehlschlug.
"""
import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import ASGITransport, AsyncClient
from mcp.server.auth.provider import AuthorizationParams

from app.api import cookies
from app.api.routes.auth import create_token
from app.config import settings
from app.database import get_db
from app.main import app
from app.models.oauth_client import OAuthClient
from app.models.organization import Organization, UserOrganization
from app.models.settings import SystemSetting
from app.models.user import User
from app.services import mcp_config, oauth_provider

pytestmark = pytest.mark.asyncio

BASE = "http://test"
REDIRECT = "http://127.0.0.1:41234/callback"
CLIENT_ID = "client-abc"


# ── Hilfen ───────────────────────────────────────────────────────────────


def _user(superadmin: bool = False) -> MagicMock:
    u = MagicMock(spec=User)
    u.id = uuid.uuid4()
    u.email = "planer@example.com"
    u.is_active = True
    u.is_superadmin = superadmin
    u.token_version = 0
    return u


def _org(slug: str = "test-org", name: str = "Test Org") -> MagicMock:
    o = MagicMock(spec=Organization)
    o.id = uuid.uuid4()
    o.slug = slug
    o.name = name
    return o


def _client() -> MagicMock:
    c = MagicMock(spec=OAuthClient)
    c.client_id = CLIENT_ID
    c.client_name = "Ein KI-Programm"
    c.revoked = False
    c.redirect_uris = [REDIRECT]
    return c


def _setting(wert: str | None) -> MagicMock | None:
    if wert is None:
        return None
    s = MagicMock(spec=SystemSetting)
    s.key = mcp_config.MCP_ENABLED_KEY
    s.value = wert
    return s


def _db(*, user=None, schalter=None, mitgliedschaften=(), client=None) -> AsyncMock:
    """Eine Datenbank, die nach der *gefragten* Tabelle antwortet.

    Bewusst nicht über eine Liste von Rückgaben in Aufrufreihenfolge: die
    Reihenfolge hängt hier daran, wann FastAPI welche Dependency auflöst, und
    ein Test, der bei jeder Umstellung kippt, prüft am Ende die Reihenfolge
    statt das Verhalten."""
    db = AsyncMock()

    async def execute(stmt, *a, **k):
        entity = stmt.column_descriptions[0]["entity"]
        r = MagicMock()
        if entity is SystemSetting:
            r.scalar_one_or_none.return_value = schalter
        elif entity is User:
            r.scalar_one_or_none.return_value = user
        elif entity is Organization:
            r.all.return_value = list(mitgliedschaften)
        else:
            r.scalar_one_or_none.return_value = None
            r.all.return_value = []
        return r

    db.execute = AsyncMock(side_effect=execute)
    db.get = AsyncMock(return_value=client)
    return db


def _db_override(db):
    async def _override():
        yield db

    return _override


def _ticket() -> str:
    return oauth_provider.encode_authorize_request(
        CLIENT_ID,
        AuthorizationParams(
            state="xyz",
            scopes=["convoy:read"],
            code_challenge="c" * 43,
            redirect_uri=REDIRECT,
            redirect_uri_provided_explicitly=True,
            resource=None,
        ),
    )


def _org_token(user, org, role="planer") -> str:
    return create_token(
        str(user.id), False, org_id=str(org.id), org_slug=org.slug, role=role
    )


async def _consent_abrufen(db, *, cookies_: dict, headers: dict | None = None):
    app.dependency_overrides[get_db] = _db_override(db)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url=BASE) as c:
            for name, wert in cookies_.items():
                c.cookies.set(name, wert)
            return await c.get(
                "/api/mcp/consent", params={"request": _ticket()}, headers=headers or {}
            )
    finally:
        app.dependency_overrides.pop(get_db, None)


# ── Der Schalter: die Datenbank entscheidet, nicht die .env ──────────────


async def test_portal_an_und_env_aus_ergibt_einen_erreichbaren_bildschirm(monkeypatch):
    """Der Fall aus der Produktion. Vorher: 404, für alle."""
    monkeypatch.setattr(settings, "mcp_enabled", False)
    user, org = _user(), _org()
    resp = await _consent_abrufen(
        _db(
            user=user,
            schalter=_setting("true"),
            mitgliedschaften=[(org, "planer")],
            client=_client(),
        ),
        cookies_={"cp_session__test-org": _org_token(user, org)},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["client_id"] == CLIENT_ID


async def test_portal_aus_schlaegt_env_an(monkeypatch):
    """Die Gegenrichtung zählt genauso: wer im Portal abschaltet, will keinen
    Zugang mehr, auch wenn in der .env noch true steht."""
    monkeypatch.setattr(settings, "mcp_enabled", True)
    user, org = _user(), _org()
    resp = await _consent_abrufen(
        _db(user=user, schalter=_setting("false"), client=_client()),
        cookies_={"cp_session__test-org": _org_token(user, org)},
    )
    assert resp.status_code == 404


async def test_ohne_eintrag_in_der_datenbank_entscheidet_die_env(monkeypatch):
    monkeypatch.setattr(settings, "mcp_enabled", False)
    user, org = _user(), _org()
    resp = await _consent_abrufen(
        _db(user=user, schalter=None, client=_client()),
        cookies_={"cp_session__test-org": _org_token(user, org)},
    )
    assert resp.status_code == 404


# ── Die Person: der Bildschirm gehört nicht einer Organisation ──────────


@pytest.fixture(autouse=True)
def mcp_an(monkeypatch):
    """Der Schalter ist an, geprüft wird die Anmeldung.

    Autouse und damit für das ganze Modul; die drei Tests oben setzen ihn
    danach selbst und gewinnen, weil ihr monkeypatch später läuft."""
    monkeypatch.setattr(settings, "mcp_enabled", True)


async def test_ein_gewoehnliches_mitglied_kommt_durch():
    """Ohne X-Org-Slug, weil die Seite außerhalb von /o/<slug>/ liegt."""
    user, org = _user(), _org()
    resp = await _consent_abrufen(
        _db(user=user, mitgliedschaften=[(org, "planer")], client=_client()),
        cookies_={"cp_session__test-org": _org_token(user, org)},
    )
    assert resp.status_code == 200, resp.text
    assert [o["slug"] for o in resp.json()["organizations"]] == ["test-org"]


async def test_mehrere_organisationen_derselben_person_sind_eindeutig():
    """Zwei Sitzungen, ein Mensch — da gibt es nichts zu raten. Und beide
    Organisationen stehen zur Auswahl, nicht nur die des Cookies."""
    user = _user()
    a, b = _org("org-a", "A"), _org("org-b", "B")
    resp = await _consent_abrufen(
        _db(
            user=user,
            mitgliedschaften=[(a, "planer"), (b, "admin")],
            client=_client(),
        ),
        cookies_={
            "cp_session__org-a": _org_token(user, a),
            "cp_session__org-b": _org_token(user, b, "admin"),
        },
    )
    assert resp.status_code == 200, resp.text
    assert {o["slug"] for o in resp.json()["organizations"]} == {"org-a", "org-b"}


async def test_zwei_verschiedene_personen_werden_nicht_geraten():
    """Der Grund, warum nicht einfach die erste Sitzung gilt: sonst erteilte
    der eine Zugriff, während der andere zugesehen hat."""
    eine, andere = _user(), _user()
    a, b = _org("org-a"), _org("org-b")
    resp = await _consent_abrufen(
        _db(user=eine, mitgliedschaften=[(a, "planer")], client=_client()),
        cookies_={
            "cp_session__org-a": _org_token(eine, a),
            "cp_session__org-b": _org_token(andere, b),
        },
    )
    assert resp.status_code == 409
    assert "mehrere Konten" in resp.json()["detail"]


async def test_ohne_jede_sitzung_bleibt_es_bei_401():
    resp = await _consent_abrufen(_db(client=_client()), cookies_={})
    assert resp.status_code == 401


async def test_die_globale_sitzung_gilt_weiterhin():
    """Der Weg, der vorher als einziger funktionierte, darf nicht wegfallen."""
    sa = _user(superadmin=True)
    resp = await _consent_abrufen(
        _db(user=sa, mitgliedschaften=[], client=_client()),
        cookies_={"cp_session": create_token(str(sa.id), True)},
    )
    assert resp.status_code == 200, resp.text


async def test_ein_abgelaufenes_globales_cookie_verdeckt_keine_org_sitzung():
    """Sonst sperrt ein Superadmin-Cookie von vorletzter Woche jeden aus, der
    denselben Browser benutzt."""
    user, org = _user(), _org()
    resp = await _consent_abrufen(
        _db(user=user, mitgliedschaften=[(org, "planer")], client=_client()),
        cookies_={
            "cp_session": "weder-gueltig-noch-entschluesselbar",
            "cp_session__test-org": _org_token(user, org),
        },
    )
    assert resp.status_code == 200, resp.text


async def test_der_org_slug_kopf_wirkt_weiterhin():
    """Wer ihn doch schickt, bekommt genau diese Sitzung — der neue Weg ist
    der Rückfall, nicht der Ersatz."""
    user, org = _user(), _org()
    resp = await _consent_abrufen(
        _db(user=user, mitgliedschaften=[(org, "planer")], client=_client()),
        cookies_={"cp_session__test-org": _org_token(user, org)},
        headers={cookies.ORG_SLUG_HEADER: "test-org"},
    )
    assert resp.status_code == 200, resp.text


# ── Der CSRF-Schutz gilt auf dem neuen Weg genauso ───────────────────────


async def test_zustimmen_ohne_csrf_kopf_wird_abgewiesen():
    """Die Zustimmung ist der eine Klick, der Zugriff erzeugt. Ein fremder
    Ursprung darf ihn nicht auslösen können, auch nicht über den neuen
    Sitzungsweg."""
    user, org = _user(), _org()
    db = _db(user=user, mitgliedschaften=[(org, "planer")], client=_client())
    app.dependency_overrides[get_db] = _db_override(db)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url=BASE) as c:
            c.cookies.set("cp_session__test-org", _org_token(user, org))
            resp = await c.post(
                "/api/mcp/consent",
                json={
                    "request": _ticket(),
                    "approve": True,
                    "organization_id": str(org.id),
                },
            )
    finally:
        app.dependency_overrides.pop(get_db, None)

    assert resp.status_code == 403
    assert cookies.CSRF_HEADER in resp.json()["detail"]


async def test_zustimmen_mit_csrf_kopf_erzeugt_einen_code():
    user, org = _user(), _org()
    mitglied = MagicMock(spec=UserOrganization)
    mitglied.role = "planer"
    db = _db(user=user, mitgliedschaften=[(org, "planer")], client=_client())

    # Die Mitgliedschaftsabfrage der POST-Strecke fragt UserOrganization ab.
    echtes_execute = db.execute.side_effect

    async def execute(stmt, *a, **k):
        if stmt.column_descriptions[0]["entity"] is UserOrganization:
            r = MagicMock()
            r.scalar_one_or_none.return_value = mitglied
            return r
        return await echtes_execute(stmt, *a, **k)

    db.execute = AsyncMock(side_effect=execute)

    app.dependency_overrides[get_db] = _db_override(db)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url=BASE) as c:
            c.cookies.set("cp_session__test-org", _org_token(user, org))
            resp = await c.post(
                "/api/mcp/consent",
                json={
                    "request": _ticket(),
                    "approve": True,
                    "organization_id": str(org.id),
                },
                headers={cookies.CSRF_HEADER: cookies.CSRF_VALUE},
            )
    finally:
        app.dependency_overrides.pop(get_db, None)

    assert resp.status_code == 200, resp.text
    assert resp.json()["redirect_url"].startswith(REDIRECT)
    assert "code=" in resp.json()["redirect_url"]
