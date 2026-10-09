"""Meldungen selbst gehosteter Instanzen erreichen den Hersteller.

Festgehalten wird, was man keiner Oberfläche ansieht:

- Auf einer selbst gehosteten Instanz wird jede **neue** Meldung zur
  Weiterleitung vorgemerkt — auf dem Hosting-Server nicht, und ohne
  ``CENTRAL_URL`` auch nicht.
- Eine Meldung, die nicht zugestellt werden konnte, bleibt offen und wird nach
  14 Tagen aufgegeben, statt für immer Schlange zu stehen.
- Der Empfänger gibt es nur auf dem Hosting-Server, weist unbekannte Felder ab
  und legt eine wiederholt zugestellte Meldung nicht doppelt an.
- Der Dialog erfährt, ob der Hersteller mitliest.
"""

import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
from httpx import ASGITransport, AsyncClient

from app.config import settings
from app.database import get_db
from app.main import app
from app.models.feedback import FeedbackReport
from app.services import betriebsart
from app.services import feedback_weiterleitung as fw

JETZT = datetime(2026, 10, 9, 12, 0, tzinfo=timezone.utc)


@pytest.fixture
def selfhost(monkeypatch):
    monkeypatch.setattr(settings, "instance_mode", "selfhost")
    monkeypatch.setattr(settings, "central_url", "https://zentrale.example.org")
    monkeypatch.setattr(settings, "app_base_url", "https://ff-musterstadt.example.net")


@pytest.fixture
def hosting(monkeypatch):
    monkeypatch.setattr(settings, "instance_mode", "hosting")
    monkeypatch.setattr(settings, "central_url", "https://zentrale.example.org")
    monkeypatch.setattr(settings, "app_base_url", "https://zentrale.example.org")


# ── Betriebsart ──────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "wert,erwartet",
    [("hosting", "hosting"), ("HOSTING ", "hosting"), ("selfhost", "selfhost"), ("", "selfhost"), ("saas", "selfhost")],
)
def test_unbekannte_betriebsart_gilt_als_selfhost(monkeypatch, wert, erwartet):
    """Die zurückhaltende Seite: ein Tippfehler macht keine Instanz zum
    Hosting-Server, der fremde Meldungen annimmt."""
    monkeypatch.setattr(settings, "instance_mode", wert)
    assert betriebsart.aktuell() == erwartet


# ── Wohin weitergeleitet wird ────────────────────────────────────────────────


def test_selbst_gehostet_geht_an_die_zentrale(selfhost):
    assert fw.ziel() == "https://zentrale.example.org/api/feedback/eingang"


def test_hosting_server_leitet_nicht_weiter(hosting):
    assert fw.ziel() is None


def test_ohne_central_url_keine_weiterleitung(selfhost, monkeypatch):
    """Der Ausweg für eine Instanz ohne Weg nach außen."""
    monkeypatch.setattr(settings, "central_url", "")
    assert fw.ziel() is None


def test_nie_an_sich_selbst(selfhost, monkeypatch):
    """Steht INSTANCE_MODE auf dem Hosting-Server versehentlich auf selfhost,
    schickte er sich sonst jede Meldung selbst."""
    monkeypatch.setattr(settings, "app_base_url", "https://ZENTRALE.example.org/")
    assert fw.ziel() is None


# ── Melden merkt vor ─────────────────────────────────────────────────────────


async def _melden(monkeypatch) -> FeedbackReport:
    from app.api.routes import feedback as feedback_route

    user = MagicMock(id=uuid.uuid4(), email="m@example.org", full_name="M", is_demo=False)
    org = MagicMock(id=uuid.uuid4(), slug="ff", name="FF")
    org.name = "FF"
    app.dependency_overrides[feedback_route.melder] = lambda: feedback_route.Melder(user, org, "planer")

    gespeichert = {}
    db = AsyncMock()
    db.add = MagicMock(side_effect=lambda zeile: gespeichert.setdefault("zeile", zeile))

    async def _refresh(zeile):
        zeile.created_at = JETZT

    db.refresh.side_effect = _refresh

    async def _db():
        yield db

    app.dependency_overrides[get_db] = _db
    monkeypatch.setattr(feedback_route.audit, "record", AsyncMock())
    sofort = AsyncMock()
    monkeypatch.setattr(fw, "sofort_weiterleiten", sofort)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post(
                "/api/feedback",
                json={"kind": "bug", "title": "Route hängt", "description": "Die Route rechnet nicht neu."},
            )
    finally:
        app.dependency_overrides.clear()
    assert resp.status_code == 201
    zeile = gespeichert["zeile"]
    zeile._sofort = sofort
    return zeile


async def test_selbst_gehostet_wird_vorgemerkt_und_sofort_versucht(selfhost, monkeypatch):
    zeile = await _melden(monkeypatch)
    assert zeile.weiterleitung == fw.OFFEN
    zeile._sofort.assert_awaited_once_with(zeile.id)


async def test_auf_dem_hosting_server_nichts_vorgemerkt(hosting, monkeypatch):
    zeile = await _melden(monkeypatch)
    assert zeile.weiterleitung is None
    zeile._sofort.assert_not_awaited()


# ── Zustellen ────────────────────────────────────────────────────────────────


def _bericht(alter: timedelta = timedelta(minutes=5)) -> FeedbackReport:
    return FeedbackReport(
        id=uuid.uuid4(),
        kind="bug",
        title="Route hängt",
        description="Die Route rechnet nicht neu.",
        severity="hoch",
        org_slug="ff",
        org_name="FF",
        reporter_email="m@example.org",
        is_demo=False,
        weiterleitung=fw.OFFEN,
        created_at=JETZT - alter,
    )


def _db_mit(berichte):
    db = AsyncMock()
    ergebnis = MagicMock()
    ergebnis.scalars.return_value.all.return_value = berichte
    db.execute.return_value = ergebnis
    return db


def _client(handler):
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


async def test_zustellung_setzt_erledigt(selfhost, monkeypatch):
    monkeypatch.setattr("app.services.instance.get_or_create_instance_id", AsyncMock(return_value="inst-1"))
    bericht = _bericht()
    angekommen = []

    def handler(request):
        angekommen.append(request)
        return httpx.Response(201, json={})

    async with _client(handler) as client:
        n = await fw.weiterleiten_offene(_db_mit([bericht]), jetzt=JETZT, client=client)

    assert n == 1
    assert bericht.weiterleitung == fw.ERLEDIGT and bericht.weitergeleitet_at == JETZT
    assert str(angekommen[0].url) == "https://zentrale.example.org/api/feedback/eingang"


async def test_nutzlast_passt_zum_vertrag_des_empfaengers(selfhost):
    """Was gesendet wird, nimmt der Empfänger an — sonst stünde jede Meldung
    14 Tage in der Schlange und würde dann aufgegeben."""
    from app.schemas.feedback import FeedbackEingang

    FeedbackEingang.model_validate(await fw.nutzlast(_bericht(), "inst-1"))


async def test_nicht_erreichbar_bleibt_offen(selfhost, monkeypatch):
    monkeypatch.setattr("app.services.instance.get_or_create_instance_id", AsyncMock(return_value="inst-1"))
    bericht = _bericht()

    def handler(request):
        raise httpx.ConnectError("kein Netz")

    async with _client(handler) as client:
        n = await fw.weiterleiten_offene(_db_mit([bericht]), jetzt=JETZT, client=client)
    assert n == 0 and bericht.weiterleitung == fw.OFFEN


async def test_abgewiesen_bleibt_offen(selfhost, monkeypatch):
    """Ein 404 heißt meist: der Empfänger ist (noch) nicht so weit. Kein Grund aufzugeben."""
    monkeypatch.setattr("app.services.instance.get_or_create_instance_id", AsyncMock(return_value="inst-1"))
    bericht = _bericht()
    async with _client(lambda r: httpx.Response(404)) as client:
        await fw.weiterleiten_offene(_db_mit([bericht]), jetzt=JETZT, client=client)
    assert bericht.weiterleitung == fw.OFFEN


async def test_nach_vierzehn_tagen_aufgegeben(selfhost, monkeypatch):
    monkeypatch.setattr("app.services.instance.get_or_create_instance_id", AsyncMock(return_value="inst-1"))
    bericht = _bericht(alter=timedelta(days=15))
    gesendet = []
    async with _client(lambda r: gesendet.append(r) or httpx.Response(201)) as client:
        await fw.weiterleiten_offene(_db_mit([bericht]), jetzt=JETZT, client=client)
    assert bericht.weiterleitung == fw.AUFGEGEBEN and not gesendet


# ── Empfangen (Hosting-Server) ───────────────────────────────────────────────


def _eingang(**mehr):
    return {
        "instanz": "inst-1",
        "instanz_url": "https://ff-musterstadt.example.net",
        "id": str(uuid.uuid4()),
        "kind": "bug",
        "title": "Route hängt",
        "description": "Die Route rechnet nicht neu.",
        "severity": "hoch",
        **mehr,
    }


async def _post_eingang(db, koerper):
    async def _db():
        yield db

    app.dependency_overrides[get_db] = _db
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            return await client.post("/api/feedback/eingang", json=koerper)
    finally:
        app.dependency_overrides.clear()


async def test_empfang_nur_auf_dem_hosting_server(selfhost):
    resp = await _post_eingang(AsyncMock(), _eingang())
    assert resp.status_code == 404


async def test_empfang_legt_an_mit_herkunft(hosting, monkeypatch):
    from app.api.routes import feedback as feedback_route

    monkeypatch.setattr(feedback_route.audit, "record", AsyncMock())
    db = _db_mit([])
    db.execute.return_value.scalar_one_or_none.return_value = None
    gespeichert = {}
    db.add = MagicMock(side_effect=lambda z: gespeichert.setdefault("z", z))

    async def _refresh(z):
        z.created_at = JETZT

    db.refresh.side_effect = _refresh
    koerper = _eingang()
    resp = await _post_eingang(db, koerper)
    assert resp.status_code == 201
    z = gespeichert["z"]
    assert z.herkunft_instanz == "inst-1" and str(z.herkunft_id) == koerper["id"]
    assert z.herkunft_url == "https://ff-musterstadt.example.net"
    # Keine Kennungen der fremden Instanz in Fremdschlüsseln dieser hier.
    assert z.org_id is None and z.user_id is None
    assert z.status == "neu" and z.weiterleitung is None


async def test_wiederholte_zustellung_ergibt_keine_dublette(hosting):
    vorhanden = FeedbackReport(id=uuid.uuid4(), kind="bug", created_at=JETZT)
    db = AsyncMock()
    db.add = MagicMock()
    db.execute.return_value = MagicMock(scalar_one_or_none=MagicMock(return_value=vorhanden))
    resp = await _post_eingang(db, _eingang())
    assert resp.status_code == 200 and resp.json()["id"] == str(vorhanden.id)
    db.add.assert_not_called()


async def test_unbekannte_felder_werden_abgewiesen(hosting):
    resp = await _post_eingang(AsyncMock(), _eingang(org_id=str(uuid.uuid4())))
    assert resp.status_code == 422


# ── Was der Dialog erfährt ───────────────────────────────────────────────────


@pytest.mark.parametrize("modus,erwartet", [("selfhost", True), ("hosting", False)])
async def test_dialog_erfaehrt_ob_der_hersteller_mitliest(monkeypatch, modus, erwartet):
    monkeypatch.setattr(settings, "instance_mode", modus)
    monkeypatch.setattr(settings, "central_url", "https://zentrale.example.org")
    monkeypatch.setattr(settings, "app_base_url", "https://ff.example.net")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/feedback/empfaenger")
    assert resp.status_code == 200 and resp.json() == {"hersteller": erwartet}
