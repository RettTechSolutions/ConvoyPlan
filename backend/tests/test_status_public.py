"""Öffentliche Statusseite: grobkörnige Aussage, keine Betriebsinterna."""
import pytest
from httpx import AsyncClient, ASGITransport

from app.api.routes import status as status_module
from app.database import get_db
from app.main import app


class _FakeDB:
    def __init__(self, ok: bool = True):
        self._ok = ok

    async def execute(self, *_args, **_kwargs):
        if not self._ok:
            raise RuntimeError("db down")
        return None


def _install(monkeypatch, *, db_ok=True, graphhopper="ok",
             overpass="ok", autobahn="ok", weather="ok", region_switch=False):
    """Alle Einzelprüfungen durch feste Werte ersetzen — kein Netz, keine DB."""
    app.dependency_overrides[get_db] = lambda: _FakeDB(db_ok)

    async def _gh_probe():
        return graphhopper, [1, 2, 3, 4]

    monkeypatch.setattr(status_module, "_graphhopper_probe", _gh_probe)

    async def _check(value):
        return {"status": value, "latency_ms": 42, "checked_at": None}

    monkeypatch.setattr(status_module.overpass_svc, "probe", lambda: _check(overpass))
    monkeypatch.setattr(status_module.autobahn_svc, "probe", lambda: _check(autobahn))
    monkeypatch.setattr(status_module.weather_svc, "probe", lambda: _check(weather))
    monkeypatch.setattr(status_module.region_switch, "laeuft", lambda: region_switch)

    # Der Kurzzeit-Cache würde sonst Ergebnisse zwischen den Tests verschleppen.
    status_module._public_cache = None


async def _get_public() -> dict:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/status/public")
    assert resp.status_code == 200
    return resp.json()


@pytest.fixture(autouse=True)
def _cleanup():
    yield
    app.dependency_overrides.clear()
    status_module._public_cache = None


@pytest.mark.asyncio
async def test_all_services_up_reports_operational(monkeypatch):
    _install(monkeypatch)
    body = await _get_public()

    assert body["overall"] == "operational"
    assert {c["key"] for c in body["components"]} == {
        "portal", "data", "planning", "tracking", "traffic", "weather"
    }
    assert all(c["state"] == "operational" for c in body["components"])


@pytest.mark.asyncio
async def test_response_exposes_no_operational_internals(monkeypatch):
    """Keine Latenzen, keine Anbieternamen, kein Kartenausschnitt, kein `core`."""
    _install(monkeypatch)
    body = await _get_public()

    assert set(body) == {"checked_at", "overall", "components"}
    for component in body["components"]:
        assert set(component) == {"key", "name", "description", "state", "reason"}

    serialized = str(body).lower()
    for leak in ("latency", "bbox", "graphhopper", "overpass", "autobahn",
                 "open-meteo", "postgres", "version", "core"):
        assert leak not in serialized


@pytest.mark.asyncio
async def test_offline_side_service_degrades_but_does_not_break_overall(monkeypatch):
    """Wetter ist keine Kernfunktion — der Ausfall schränkt ein, mehr nicht."""
    _install(monkeypatch, weather="error")
    body = await _get_public()

    assert body["overall"] == "degraded"
    states = {c["key"]: c["state"] for c in body["components"]}
    assert states["weather"] == "down"
    assert states["tracking"] == "operational"


@pytest.mark.asyncio
async def test_partial_traffic_outage_is_degraded(monkeypatch):
    """Eine von zwei Verkehrsquellen weg → eingeschränkt, nicht ausgefallen."""
    _install(monkeypatch, autobahn="error")
    body = await _get_public()

    states = {c["key"]: c["state"] for c in body["components"]}
    assert states["traffic"] == "degraded"


@pytest.mark.asyncio
async def test_both_traffic_sources_down_reports_down(monkeypatch):
    _install(monkeypatch, overpass="error", autobahn="error")
    body = await _get_public()

    states = {c["key"]: c["state"] for c in body["components"]}
    assert states["traffic"] == "down"
    # Verkehr ist keine Kernfunktion — die Instanz gilt weiter als eingeschränkt.
    assert body["overall"] == "degraded"


@pytest.mark.asyncio
async def test_database_outage_reports_down(monkeypatch):
    """Ohne Datenbank sind Kernfunktionen weg — das ist eine Störung."""
    _install(monkeypatch, db_ok=False)
    body = await _get_public()

    assert body["overall"] == "down"
    states = {c["key"]: c["state"] for c in body["components"]}
    assert states["data"] == "down"
    assert states["tracking"] == "down"
    assert states["portal"] == "operational"


@pytest.mark.asyncio
async def test_graphhopper_still_importing_is_degraded(monkeypatch):
    """Während der Kartenimport läuft, ist Planung eingeschränkt — nicht weg."""
    _install(monkeypatch, graphhopper="building")
    body = await _get_public()

    states = {c["key"]: c["state"] for c in body["components"]}
    assert states["planning"] == "degraded"
    assert body["overall"] == "degraded"


@pytest.mark.asyncio
async def test_unknown_probe_does_not_drag_down_overall(monkeypatch):
    """Noch nie geprüfte Zusatzdienste sind unbekannt, nicht ausgefallen."""
    _install(monkeypatch, weather="unknown")
    body = await _get_public()

    states = {c["key"]: c["state"] for c in body["components"]}
    assert states["weather"] == "unknown"
    assert body["overall"] == "operational"


@pytest.mark.asyncio
async def test_result_is_cached_between_requests(monkeypatch):
    """Die Seite pollt — die geprüften Dienste dürfen das nicht spüren."""
    _install(monkeypatch)
    calls = {"n": 0}

    async def _counting_probe():
        calls["n"] += 1
        return "ok", None

    monkeypatch.setattr(status_module, "_graphhopper_probe", _counting_probe)

    await _get_public()
    await _get_public()

    assert calls["n"] == 1


# ── Gründe ───────────────────────────────────────────────────────────────
# Eine Plakette „Nicht verfügbar" sagt nicht, ob man warten oder melden soll.
# Der Grund sagt es — in Funktionen, ohne Anbieter- oder Dienstnamen.

def _reasons(body: dict) -> dict:
    return {c["key"]: c["reason"] for c in body["components"]}


@pytest.mark.asyncio
async def test_operational_components_carry_no_reason(monkeypatch):
    _install(monkeypatch)
    body = await _get_public()

    assert all(r is None for r in _reasons(body).values())


@pytest.mark.asyncio
@pytest.mark.parametrize("graphhopper,expected", [
    ("offline", "nach einem Update neu aufgebaut"),
    ("building", "wird gerade geladen"),
])
async def test_routing_outage_explains_itself(monkeypatch, graphhopper, expected):
    _install(monkeypatch, graphhopper=graphhopper)
    reasons = _reasons(await _get_public())

    assert expected in reasons["planning"]
    assert reasons["data"] is None


@pytest.mark.asyncio
async def test_running_region_switch_is_named_as_cause(monkeypatch):
    """Während eines Regionswechsels ist der Ausfall angekündigt, nicht rätselhaft."""
    _install(monkeypatch, graphhopper="offline", region_switch=True)
    reasons = _reasons(await _get_public())

    assert "Kartenregion wird gerade gewechselt" in reasons["planning"]


@pytest.mark.asyncio
async def test_region_switch_without_outage_gives_no_reason(monkeypatch):
    _install(monkeypatch, region_switch=True)
    reasons = _reasons(await _get_public())

    assert reasons["planning"] is None


@pytest.mark.asyncio
async def test_traffic_reason_names_the_missing_part(monkeypatch):
    _install(monkeypatch, autobahn="error")
    reasons = _reasons(await _get_public())

    assert reasons["traffic"].startswith("Autobahnmeldungen fehlen")


@pytest.mark.asyncio
async def test_database_outage_explains_data_and_tracking(monkeypatch):
    _install(monkeypatch, db_ok=False)
    reasons = _reasons(await _get_public())

    assert "Datenbank" in reasons["data"]
    assert "Standortmeldungen" in reasons["tracking"]
    assert reasons["portal"] is None


@pytest.mark.asyncio
async def test_reasons_expose_no_operational_internals(monkeypatch):
    """Auch im Ausfall keine Anbieter- oder Dienstnamen — die Gründe am wenigsten."""
    _install(monkeypatch, graphhopper="offline", overpass="error",
             autobahn="error", weather="error")
    serialized = " ".join(r for r in _reasons(await _get_public()).values() if r).lower()

    for leak in ("graphhopper", "overpass", "open-meteo", "postgres", "docker", "container"):
        assert leak not in serialized
