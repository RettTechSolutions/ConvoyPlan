"""Der Laufzeitschalter für den MCP-Server.

Der Kern dieser Datei ist **eine** Zusage: abgeschaltet gibt es die MCP-Routen
nicht. Nicht „sie antworten mit 404", sondern: es passt keine Route. Das war
der Grund, warum der Schalter bis hierher eine Umgebungsvariable war, und es
ist der Grund, warum er jetzt trotzdem einer sein darf.

Geprüft wird deshalb nicht nur der Statuscode — den liefert ein 404-Deckel
genauso —, sondern die Routentabelle der App selbst.

Seit dem OAuth-Client der Begleit-App (``services/app_client.py``) gilt das
für die Pfade des Authorization Servers (``/authorize``, ``/token``,
``/revoke``, AS-Metadaten) nur, solange auch der App-Client aus ist. Ist er
an, bleiben genau diese vier stehen — ``/mcp``, ``/register`` und die
Protected-Resource-Metadaten verschwinden weiterhin. Beides steht unten.
"""
import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.config import settings
from app.mcp import mount as mcp_mount
from app.services import mcp_config

pytestmark = pytest.mark.asyncio

BASE = "https://toggle-test.convoyplan.invalid"

# Die Pfade, die es bei abgeschaltetem MCP nie geben darf.
NUR_MCP = [
    "/mcp",
    "/.well-known/oauth-protected-resource/mcp",
    "/register",
]
# Die des Authorization Servers — bei abgeschaltetem MCP nur, solange der
# App-Client an ist.
AS_PFADE = [
    "/.well-known/oauth-authorization-server",
    "/authorize",
    "/token",
    "/revoke",
]
MCP_PFADE = NUR_MCP + AS_PFADE


def _frische_app() -> FastAPI:
    """Eine App mit vorbereitetem, aber nicht montiertem MCP-Server."""
    app = FastAPI()
    mcp_mount.mount(app)
    return app


def _pfade(app: FastAPI) -> set[str]:
    return {getattr(r, "path", None) for r in app.router.routes}


@pytest.fixture(autouse=True)
def basis_adresse():
    vorher = (settings.app_base_url, settings.mcp_public_url, settings.mcp_enabled,
              settings.app_oauth_enabled)
    settings.app_base_url = BASE
    settings.mcp_public_url = ""
    # Die ursprüngliche Zusage gilt ohne App-Client; was er ändert, prüfen
    # die Tests am Ende ausdrücklich.
    settings.app_oauth_enabled = False
    try:
        yield
    finally:
        (settings.app_base_url, settings.mcp_public_url,
         settings.mcp_enabled, settings.app_oauth_enabled) = vorher
        mcp_mount._app = None
        mcp_mount._routes = []
        mcp_mount._as_routes = []
        mcp_mount._session_manager = None


# ── Die Zusage ───────────────────────────────────────────────────────────


def test_vorbereiten_montiert_noch_nichts():
    """`mount()` baut, hängt aber nicht an. Sonst wäre der Startzustand
    immer „an", und der gespeicherte Schalter käme zu spät."""
    app = _frische_app()
    assert mcp_mount.ist_aktiv() is False
    assert _pfade(app).isdisjoint(MCP_PFADE)


def test_abgeschaltet_existiert_keine_einzige_mcp_route():
    app = _frische_app()
    mcp_mount.aktivieren()
    assert mcp_mount.ist_aktiv() is True
    assert set(MCP_PFADE) <= _pfade(app)

    mcp_mount.deaktivieren()
    assert mcp_mount.ist_aktiv() is False
    # Das ist die eigentliche Prüfung: die Pfade sind aus der Routentabelle
    # verschwunden. Ein Schalter, der nur 404 zurückgibt, bestünde sie nicht.
    assert _pfade(app).isdisjoint(MCP_PFADE)


async def test_abgeschaltet_antwortet_der_router_mit_404():
    """Die beobachtbare Seite derselben Sache."""
    app = _frische_app()
    mcp_mount.aktivieren()
    mcp_mount.deaktivieren()
    async with AsyncClient(transport=ASGITransport(app=app), base_url=BASE) as client:
        for pfad in MCP_PFADE:
            resp = await client.get(pfad)
            assert resp.status_code == 404, f"{pfad} antwortet {resp.status_code}"


async def test_eingeschaltet_verlangt_der_endpunkt_eine_anmeldung():
    """Gegenprobe: eingeschaltet ist die Route da — und schützt sich.

    Ohne diese Prüfung könnte `aktivieren()` irgendetwas anhängen und der
    Test oben wäre trotzdem grün."""
    app = _frische_app()
    mcp_mount.aktivieren()
    async with AsyncClient(transport=ASGITransport(app=app), base_url=BASE) as client:
        resp = await client.post("/mcp", json={"jsonrpc": "2.0", "method": "x"})
    assert resp.status_code == 401
    assert "www-authenticate" in resp.headers


# ── Idempotenz ───────────────────────────────────────────────────────────


def test_zweimal_einschalten_haengt_nicht_doppelt_an():
    app = _frische_app()
    assert mcp_mount.aktivieren() is True
    anzahl = len(app.router.routes)
    assert mcp_mount.aktivieren() is False
    assert len(app.router.routes) == anzahl


def test_zweimal_ausschalten_entfernt_nichts_fremdes():
    app = _frische_app()
    fremde = len(app.router.routes)
    mcp_mount.aktivieren()
    assert mcp_mount.deaktivieren() is True
    assert mcp_mount.deaktivieren() is False
    assert len(app.router.routes) == fremde


def test_ausschalten_laesst_die_uebrigen_routen_in_ruhe():
    """Die Routen werden über Objekt-Identität entfernt, nicht über den Pfad.

    Sonst nähme ein Ausschalten eine gleichnamige Route der App mit."""
    app = _frische_app()

    @app.get("/mcp-fremd")
    def _fremd():
        return {"ok": True}

    vorher = _pfade(app)
    mcp_mount.aktivieren()
    mcp_mount.deaktivieren()
    assert _pfade(app) == vorher


def test_openapi_wird_nach_dem_umschalten_neu_gebaut():
    """FastAPI hält das Dokument fest. Bei einem Schalter, dessen Zweck die
    Sichtbarkeit von Endpunkten ist, wäre ein alter Stand die falsche
    Auskunft."""
    app = _frische_app()
    app.openapi()
    assert app.openapi_schema is not None
    mcp_mount.aktivieren()
    assert app.openapi_schema is None


# ── Die gespeicherte Einstellung ─────────────────────────────────────────


async def test_datenbank_schlaegt_umgebungsvariable():
    from app.database import AsyncSessionLocal, engine
    from app.models.settings import SystemSetting
    from sqlalchemy import delete

    try:
        async with AsyncSessionLocal() as db:
            await db.execute(
                delete(SystemSetting).where(SystemSetting.key == mcp_config.MCP_ENABLED_KEY)
            )
            await db.commit()

            # Ohne Eintrag gilt die Umgebungsvariable.
            settings.mcp_enabled = True
            assert await mcp_config.is_mcp_enabled(db) is True
            settings.mcp_enabled = False
            assert await mcp_config.is_mcp_enabled(db) is False

            # Mit Eintrag gilt der Eintrag — in beide Richtungen.
            await mcp_config.set_mcp_enabled(db, True)
            assert await mcp_config.is_mcp_enabled(db) is True
            settings.mcp_enabled = True
            await mcp_config.set_mcp_enabled(db, False)
            assert await mcp_config.is_mcp_enabled(db) is False

            await db.execute(
                delete(SystemSetting).where(SystemSetting.key == mcp_config.MCP_ENABLED_KEY)
            )
            await db.commit()
    finally:
        await engine.dispose()


async def test_unsinniger_wert_in_der_datenbank_zaehlt_als_nicht_gesetzt():
    """Fail-safe: was nicht "true"/"false" ist, fällt auf die Umgebung
    zurück, statt als wahr durchzugehen."""
    from app.database import AsyncSessionLocal, engine
    from app.models.settings import SystemSetting
    from sqlalchemy import delete

    try:
        async with AsyncSessionLocal() as db:
            await db.execute(
                delete(SystemSetting).where(SystemSetting.key == mcp_config.MCP_ENABLED_KEY)
            )
            db.add(SystemSetting(key=mcp_config.MCP_ENABLED_KEY, value="vielleicht"))
            await db.commit()

            assert await mcp_config.get_mcp_enabled_setting(db) is None
            settings.mcp_enabled = False
            assert await mcp_config.is_mcp_enabled(db) is False

            await db.execute(
                delete(SystemSetting).where(SystemSetting.key == mcp_config.MCP_ENABLED_KEY)
            )
            await db.commit()
    finally:
        await engine.dispose()


# ── Mit dem App-Client ───────────────────────────────────────────────────


def test_mit_app_client_bleiben_nur_die_as_pfade():
    """MCP aus, App-Client an: ``/authorize``, ``/token``, ``/revoke`` und die
    AS-Metadaten stehen in der Tabelle — ``/mcp``, ``/register`` und die
    Protected-Resource-Metadaten nicht."""
    settings.app_oauth_enabled = True
    app = _frische_app()
    mcp_mount.aktivieren()
    mcp_mount.deaktivieren()
    pfade = _pfade(app)
    assert set(AS_PFADE) <= pfade
    assert pfade.isdisjoint(NUR_MCP)


def test_start_mit_mcp_aus_montiert_die_as_pfade_fuer_die_app():
    """Beim Start ist nichts zu deaktivieren — die Pfade der App müssen
    trotzdem hinein. ``zustand_anwenden`` ruft dafür immer ``_anwenden``."""
    settings.app_oauth_enabled = True
    app = _frische_app()
    mcp_mount._anwenden(False)
    assert set(AS_PFADE) <= _pfade(app)
    assert _pfade(app).isdisjoint(NUR_MCP)
    assert mcp_mount.ist_aktiv() is False


def test_anwenden_ist_idempotent():
    settings.app_oauth_enabled = True
    app = _frische_app()
    mcp_mount._anwenden(False)
    anzahl = len(app.router.routes)
    mcp_mount._anwenden(False)
    assert len(app.router.routes) == anzahl
    mcp_mount._anwenden(True)
    mcp_mount._anwenden(True)
    assert len(app.router.routes) == anzahl + len(mcp_mount._routes)
