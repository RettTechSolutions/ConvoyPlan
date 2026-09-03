"""Tests fuer Preview (Task 4) sowie Ausloesen/Status/Abbruch/Liste (Task 5)
des Regionswechsels.

Verwendet das im Repo etablierte Testmuster (siehe test_admin.py): ein
ASGITransport-Client gegen die echte FastAPI-App, mit Dependency-Override
fuer `require_superadmin` statt echter Fixtures (die im Brief genannten
`client`/`superadmin_headers`/`db`-Fixtures existieren in conftest.py nicht).
Die DB ist eine AsyncSession — auch hier Dependency-Override von `get_db`
gegen einen AsyncMock statt eines synchronen `db.query(...)`.
"""
import os
from unittest.mock import AsyncMock, MagicMock, mock_open, patch

import pytest
from httpx import ASGITransport, AsyncClient

from app.api.routes import admin
from app.database import get_db
from app.main import app
from app.services import geofabrik, region_switch

GB = 1024 ** 3
URL = "https://download.geofabrik.de/europe/dach-latest.osm.pbf"


def _superadmin():
    user = MagicMock()
    user.is_superadmin = True
    user.id = "11111111-1111-1111-1111-111111111111"
    user.email = "admin@example.org"
    return user


def _make_app_with_superadmin():
    from app.api.deps import require_superadmin
    app.dependency_overrides[require_superadmin] = lambda: _superadmin()
    return app


def _make_app_with_superadmin_and_db():
    """Wie _make_app_with_superadmin(), zusaetzlich mit einem AsyncMock als
    AsyncSession fuer Endpunkte, die audit.record() (und damit db.commit())
    aufrufen."""
    _make_app_with_superadmin()
    db = AsyncMock()

    async def _db_override():
        yield db

    app.dependency_overrides[get_db] = _db_override
    return app


def _async_size(bytes_value: int):
    """Ersetzt geofabrik.head_size_bytes (jetzt async, Fix-Runde 1) durch
    eine feste Groesse, ohne echtes Netzwerk anzufragen."""
    async def _fake(url):
        return bytes_value
    return _fake


@pytest.fixture(autouse=True)
def _clear_overrides():
    yield
    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_preview_returns_verdict_and_numbers(monkeypatch):
    monkeypatch.setattr(geofabrik, "head_size_bytes", _async_size(int(5.5 * GB)))
    test_app = _make_app_with_superadmin()
    transport = ASGITransport(app=test_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/api/admin/region/preview",
            json={"url": URL},
            headers={"Authorization": "Bearer x"},
        )
    assert resp.status_code == 200
    body = resp.json()
    assert body["extract_bytes"] == int(5.5 * GB)
    assert body["verdict"] in {"ok", "knapp", "reicht nicht"}
    assert body["reason"]
    # Getrennt ausgewiesen, damit das Panel den Effekt des verkleinerbaren
    # GraphHopper-Heaps waehrend des Imports separat zeigen kann (Korrektur 3).
    assert "ram_reclaimable_bytes" in body
    assert "ram_available_bytes" in body


@pytest.mark.asyncio
async def test_preview_rejects_foreign_host():
    test_app = _make_app_with_superadmin()
    transport = ASGITransport(app=test_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/api/admin/region/preview",
            json={"url": "https://evil.example/x-latest.osm.pbf"},
            headers={"Authorization": "Bearer x"},
        )
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_preview_requires_superadmin():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post("/api/admin/region/preview", json={"url": URL})
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_preview_credits_reclaimable_heap_of_running_graphhopper(monkeypatch):
    """Regressionstest fuer Korrektur 3: ~8 GB frei + ~10 GB Bedarf fuer DACH
    duerfen NICHT als 'reicht nicht' fuer die aktuell laufende Region gelten,
    weil der laufende GraphHopper-Heap waehrend des Imports verkleinert wird
    und diesen Speicher zurueckgibt."""
    from app.services import host_metrics
    from app.config import settings

    monkeypatch.setattr(geofabrik, "head_size_bytes", _async_size(int(5.79 * GB)))
    monkeypatch.setattr(settings, "java_opts", "-Xmx8g -Xms1g -XX:+UseG1GC")

    mem = MagicMock()
    mem.available_bytes = int(8 * GB)
    monkeypatch.setattr(host_metrics, "read_memory", lambda: mem)

    disk = MagicMock()
    disk.free_bytes = int(100 * GB)
    monkeypatch.setattr(host_metrics, "disk_usage", lambda paths: [disk])

    test_app = _make_app_with_superadmin()
    transport = ASGITransport(app=test_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/api/admin/region/preview",
            json={"url": URL},
            headers={"Authorization": "Bearer x"},
        )
    assert resp.status_code == 200
    body = resp.json()
    assert body["ram_reclaimable_bytes"] == int(8 * GB)
    assert body["verdict"] != "reicht nicht"


@pytest.mark.asyncio
async def test_preview_disk_shortage_overrides_ok_ram(monkeypatch):
    """Testluecke aus Fix-Runde 1: bisher zielten alle Faelle auf RAM. Hier
    reicht der RAM klar, aber die Platte ist knapp — das Gesamturteil muss
    trotzdem 'reicht nicht' sein (worst-of-both, siehe preview())."""
    from app.services import host_metrics

    # Kleines Extract (Bayern-Groessenordnung) => RAM-Bedarf trivial klein.
    monkeypatch.setattr(geofabrik, "head_size_bytes", _async_size(int(0.79 * GB)))

    mem = MagicMock()
    mem.available_bytes = int(64 * GB)
    monkeypatch.setattr(host_metrics, "read_memory", lambda: mem)

    # Platte fast voll: deutlich weniger frei als extract+graph benoetigen.
    disk = MagicMock()
    disk.free_bytes = int(0.1 * GB)
    monkeypatch.setattr(host_metrics, "disk_usage", lambda paths: [disk])

    test_app = _make_app_with_superadmin()
    transport = ASGITransport(app=test_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/api/admin/region/preview",
            json={"url": URL},
            headers={"Authorization": "Bearer x"},
        )
    assert resp.status_code == 200
    body = resp.json()
    assert body["verdict"] == "reicht nicht"
    assert "Platte" in body["reason"] or "platte" in body["reason"].lower()


@pytest.mark.asyncio
async def test_preview_returns_503_when_geofabrik_unreachable(monkeypatch):
    """Important 2 aus Fix-Runde 1: ein Verbindungsfehler beim HEAD-Request
    darf nicht als nackter 500 durchschlagen, sondern muss als 503 mit
    sprechender Meldung ankommen."""
    async def _boom(url):
        raise ConnectionError(
            "Geofabrik ist gerade nicht erreichbar. Bitte spaeter erneut "
            "versuchen."
        )

    monkeypatch.setattr(geofabrik, "head_size_bytes", _boom)

    test_app = _make_app_with_superadmin()
    transport = ASGITransport(app=test_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/api/admin/region/preview",
            json={"url": URL},
            headers={"Authorization": "Bearer x"},
        )
    assert resp.status_code == 503
    assert "erreichbar" in resp.json()["detail"]


def test_reclaimable_heap_bytes_falls_back_to_zero_when_unparsable(monkeypatch):
    """Testluecke aus Fix-Runde 1: der 0-Fallback bei fehlendem/unparsbarem
    -Xmx ist eine bewusste (konservative) Entscheidung und war ungetestet."""
    from app.config import settings
    from app.api.routes.region import _reclaimable_heap_bytes

    monkeypatch.setattr(settings, "java_opts", "-Xms1g -XX:+UseG1GC")  # kein -Xmx
    assert _reclaimable_heap_bytes() == 0

    monkeypatch.setattr(settings, "java_opts", "-Xmx8x -Xms1g")  # unbekannte Einheit
    assert _reclaimable_heap_bytes() == 0

    monkeypatch.setattr(settings, "java_opts", "")  # leer
    assert _reclaimable_heap_bytes() == 0


# ── Task 5: Auslösen, Status, Abbruch, Liste, aktuelle Region ────────────────


@pytest.mark.asyncio
async def test_switch_returns_202_and_records_audit(monkeypatch):
    monkeypatch.setattr(geofabrik, "head_size_bytes", _async_size(int(1 * GB)))
    monkeypatch.setattr(os.path, "exists", lambda p: False)
    monkeypatch.setattr(region_switch, "is_busy", lambda: False)
    monkeypatch.setattr(region_switch, "write_request", lambda *a, **k: None)

    test_app = _make_app_with_superadmin_and_db()
    audit_mock = AsyncMock()
    with patch("app.api.routes.region.audit.record", new=audit_mock):
        transport = ASGITransport(app=test_app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                "/api/admin/region",
                json={"url": URL},
                headers={"Authorization": "Bearer x"},
            )
    assert resp.status_code == 202
    assert resp.json() == {"status": "requested"}

    audit_mock.assert_awaited_once()
    args, kwargs = audit_mock.call_args
    assert args[1] == "region.switch_requested"
    assert kwargs["target_type"] == "region"
    assert kwargs["detail"]["url"] == URL


@pytest.mark.asyncio
async def test_switch_conflicts_with_running_update(monkeypatch):
    # head_size_bytes gemockt: die Konfliktprüfung läuft jetzt (Fix-Runde 1)
    # NACH dem HEAD-Request, nicht mehr davor — ohne Mock würde dieser Test
    # einen echten Netzwerkaufruf gegen Geofabrik auslösen.
    monkeypatch.setattr(geofabrik, "head_size_bytes", _async_size(int(1 * GB)))
    monkeypatch.setattr(os.path, "exists", lambda p: p == admin.TRIGGER_FILE)
    test_app = _make_app_with_superadmin_and_db()
    transport = ASGITransport(app=test_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/api/admin/region",
            json={"url": URL},
            headers={"Authorization": "Bearer x"},
        )
    assert resp.status_code == 409


@pytest.mark.asyncio
async def test_switch_conflicts_with_running_region_switch(monkeypatch):
    monkeypatch.setattr(geofabrik, "head_size_bytes", _async_size(int(1 * GB)))
    monkeypatch.setattr(os.path, "exists", lambda p: False)
    monkeypatch.setattr(region_switch, "is_busy", lambda: True)
    test_app = _make_app_with_superadmin_and_db()
    transport = ASGITransport(app=test_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/api/admin/region",
            json={"url": URL},
            headers={"Authorization": "Bearer x"},
        )
    assert resp.status_code == 409


@pytest.mark.asyncio
async def test_switch_requires_superadmin():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post("/api/admin/region", json={"url": URL})
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_update_trigger_conflicts_with_running_region_switch(monkeypatch):
    """Spiegelbildliche Sperre: laeuft ein Regionswechsel, darf trigger-update
    nicht gleichzeitig anlaufen (beide teilen sich /update_status)."""
    monkeypatch.setattr(admin.os.path, "exists", lambda p: False)
    monkeypatch.setattr(region_switch, "is_busy", lambda: True)
    test_app = _make_app_with_superadmin()
    transport = ASGITransport(app=test_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/api/admin/trigger-update", headers={"Authorization": "Bearer x"}
        )
    assert resp.status_code == 409


@pytest.mark.asyncio
async def test_status_returns_updater_status(monkeypatch):
    monkeypatch.setattr(
        region_switch, "read_status", lambda: {"phase": "importing", "percent": 42}
    )
    test_app = _make_app_with_superadmin()
    transport = ASGITransport(app=test_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(
            "/api/admin/region/status", headers={"Authorization": "Bearer x"}
        )
    assert resp.status_code == 200
    assert resp.json() == {"phase": "importing", "percent": 42}


@pytest.mark.asyncio
async def test_cancel_returns_409_when_not_busy(monkeypatch):
    monkeypatch.setattr(region_switch, "is_busy", lambda: False)
    test_app = _make_app_with_superadmin()
    transport = ASGITransport(app=test_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/api/admin/region/cancel", headers={"Authorization": "Bearer x"}
        )
    assert resp.status_code == 409


@pytest.mark.asyncio
async def test_cancel_signals_updater_when_busy(monkeypatch):
    monkeypatch.setattr(region_switch, "is_busy", lambda: True)
    cancel_mock = MagicMock()
    monkeypatch.setattr(region_switch, "request_cancel", cancel_mock)
    test_app = _make_app_with_superadmin()
    transport = ASGITransport(app=test_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            "/api/admin/region/cancel", headers={"Authorization": "Bearer x"}
        )
    assert resp.status_code == 202
    assert resp.json() == {"status": "cancelling"}
    cancel_mock.assert_called_once()


@pytest.mark.asyncio
async def test_current_region_reads_region_file(tmp_path, monkeypatch):
    from app.api.routes import region as region_routes

    monkeypatch.setattr(region_routes, "OSM_PATH", str(tmp_path))
    (tmp_path / ".region").write_text(
        "OSM_DOWNLOAD_URL=https://download.geofabrik.de/europe/germany/berlin-latest.osm.pbf\n"
        "OSM_FILENAME=berlin-latest.osm.pbf\n"
        "JAVA_OPTS=-Xmx3g -Xms1g -XX:+UseG1GC\n"
    )
    test_app = _make_app_with_superadmin()
    transport = ASGITransport(app=test_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(
            "/api/admin/region", headers={"Authorization": "Bearer x"}
        )
    assert resp.status_code == 200
    body = resp.json()
    assert body["url"].endswith("berlin-latest.osm.pbf")
    assert body["filename"] == "berlin-latest.osm.pbf"
    assert body["java_opts"] == "-Xmx3g -Xms1g -XX:+UseG1GC"


@pytest.mark.asyncio
async def test_current_region_falls_back_to_default_without_region_file(
    tmp_path, monkeypatch
):
    from app.api.routes import region as region_routes

    # tmp_path existiert, aber ".region" darin nicht — Zustand direkt nach
    # der Installation, bevor je ein Wechsel stattgefunden hat.
    monkeypatch.setattr(region_routes, "OSM_PATH", str(tmp_path))
    test_app = _make_app_with_superadmin()
    transport = ASGITransport(app=test_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(
            "/api/admin/region", headers={"Authorization": "Bearer x"}
        )
    assert resp.status_code == 200
    body = resp.json()
    assert "dach" in body["url"]
    assert body["filename"] == "dach-latest.osm.pbf"


@pytest.mark.asyncio
async def test_list_regions_returns_entries_with_path(monkeypatch):
    async def _fake_list_regions():
        return [
            geofabrik.RegionEntry(
                id="act",
                name="Australian Capital Territory",
                path="Australia-Oceania › Australia › Australian Capital Territory",
                url="https://download.geofabrik.de/australia-oceania/australia/act-latest.osm.pbf",
                size_bytes=None,
            )
        ]

    monkeypatch.setattr(geofabrik, "list_regions", _fake_list_regions)
    test_app = _make_app_with_superadmin()
    transport = ASGITransport(app=test_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(
            "/api/admin/regions", headers={"Authorization": "Bearer x"}
        )
    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 1
    assert body[0]["id"] == "act"
    assert body[0]["path"] == "Australia-Oceania › Australia › Australian Capital Territory"
    # Nur die urls.pbf-Variante, niemals pbf-internal/history (anderer Host).
    assert body[0]["url"].startswith("https://download.geofabrik.de/")


@pytest.mark.asyncio
async def test_list_regions_returns_503_when_geofabrik_unreachable(monkeypatch):
    async def _boom():
        raise ConnectionError(
            "Geofabrik-Index ist gerade nicht abrufbar. Bitte spaeter erneut "
            "versuchen."
        )

    monkeypatch.setattr(geofabrik, "list_regions", _boom)
    test_app = _make_app_with_superadmin()
    transport = ASGITransport(app=test_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get(
            "/api/admin/regions", headers={"Authorization": "Bearer x"}
        )
    assert resp.status_code == 503


@pytest.mark.asyncio
async def test_list_regions_requires_superadmin():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/admin/regions")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_geofabrik_list_regions_builds_path_from_parent_chain_and_uses_pbf_only(
    monkeypatch,
):
    """Regressionstest fuer die Falle aus dem Brief: der Index enthaelt neben
    urls.pbf auch pbf-internal/history auf einem anderen Host — nur urls.pbf
    darf verwendet werden, sonst scheitert die Region erst beim Ausloesen an
    der Allowlist."""
    monkeypatch.setattr(geofabrik, "_region_index_cache", None)

    features = [
        {
            "properties": {
                "id": "australia-oceania",
                "name": "Australia and Oceania",
                "urls": {"pbf": "https://download.geofabrik.de/australia-oceania-latest.osm.pbf"},
            }
        },
        {
            "properties": {
                "id": "australia",
                "name": "Australia",
                "parent": "australia-oceania",
                "urls": {"pbf": "https://download.geofabrik.de/australia-oceania/australia-latest.osm.pbf"},
            }
        },
        {
            "properties": {
                "id": "act",
                "name": "Australian Capital Territory",
                "parent": "australia",
                "urls": {
                    "pbf": "https://download.geofabrik.de/australia-oceania/australia/act-latest.osm.pbf",
                    "pbf-internal": "https://osm-internal.download.geofabrik.de/australia-oceania/australia/act-latest-internal.osm.pbf",
                    "history": "https://osm-internal.download.geofabrik.de/australia-oceania/australia/act-internal.osh.pbf",
                },
            }
        },
    ]

    class _FakeResponse:
        def raise_for_status(self):
            pass

        def json(self):
            return {"type": "FeatureCollection", "features": features}

    class _FakeAsyncClient:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def get(self, url):
            return _FakeResponse()

    monkeypatch.setattr(geofabrik.httpx, "AsyncClient", _FakeAsyncClient)

    entries = await geofabrik.list_regions()
    by_id = {e.id: e for e in entries}
    assert by_id["act"].path == "Australia and Oceania › Australia › Australian Capital Territory"
    assert by_id["act"].url == "https://download.geofabrik.de/australia-oceania/australia/act-latest.osm.pbf"
    assert "osm-internal" not in by_id["act"].url


# ── Fix-Runde 1: TOCTOU geschlossen, Audit auch bei Ablehnung ───────────────


@pytest.mark.asyncio
async def test_switch_returns_409_when_write_request_races(monkeypatch):
    """Der eigentliche TOCTOU-Schutz: selbst wenn der Vorab-Check (is_busy())
    im schmalen Fenster zwischen Prüfung und Schreiben von einer zweiten,
    fast gleichzeitigen Anfrage bestanden wird, muss das exklusive Anlegen
    der Anforderungsdatei die zweite Anfrage mit 409 abweisen — simuliert
    hier direkt über FileExistsError aus region_switch.write_request()."""
    monkeypatch.setattr(geofabrik, "head_size_bytes", _async_size(int(1 * GB)))
    monkeypatch.setattr(os.path, "exists", lambda p: False)
    monkeypatch.setattr(region_switch, "is_busy", lambda: False)

    def _boom(*a, **k):
        raise FileExistsError(17, "File exists")

    monkeypatch.setattr(region_switch, "write_request", _boom)

    test_app = _make_app_with_superadmin_and_db()
    audit_mock = AsyncMock()
    with patch("app.api.routes.region.audit.record", new=audit_mock):
        transport = ASGITransport(app=test_app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                "/api/admin/region",
                json={"url": URL},
                headers={"Authorization": "Bearer x"},
            )
    assert resp.status_code == 409
    audit_mock.assert_awaited_once()
    args, kwargs = audit_mock.call_args
    assert args[1] == "region.switch_rejected"
    assert kwargs["detail"]["url"] == URL


@pytest.mark.asyncio
async def test_switch_records_audit_on_invalid_url(monkeypatch):
    """Kleinigkeit aus Fix-Runde 1: auch abgelehnte Versuche (400) müssen in
    der Audit-Spur landen, nicht nur der Erfolgsfall."""
    test_app = _make_app_with_superadmin_and_db()
    audit_mock = AsyncMock()
    with patch("app.api.routes.region.audit.record", new=audit_mock):
        transport = ASGITransport(app=test_app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                "/api/admin/region",
                json={"url": "https://evil.example/x-latest.osm.pbf"},
                headers={"Authorization": "Bearer x"},
            )
    assert resp.status_code == 400
    audit_mock.assert_awaited_once()
    args, kwargs = audit_mock.call_args
    assert args[1] == "region.switch_rejected"


@pytest.mark.asyncio
async def test_switch_records_audit_on_geofabrik_unreachable(monkeypatch):
    """Kleinigkeit aus Fix-Runde 1: auch der 503-Pfad (Geofabrik nicht
    erreichbar) muss auditiert werden."""
    async def _boom(url):
        raise ConnectionError("Geofabrik ist gerade nicht erreichbar.")

    monkeypatch.setattr(geofabrik, "head_size_bytes", _boom)

    test_app = _make_app_with_superadmin_and_db()
    audit_mock = AsyncMock()
    with patch("app.api.routes.region.audit.record", new=audit_mock):
        transport = ASGITransport(app=test_app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                "/api/admin/region",
                json={"url": URL},
                headers={"Authorization": "Bearer x"},
            )
    assert resp.status_code == 503
    audit_mock.assert_awaited_once()
    args, kwargs = audit_mock.call_args
    assert args[1] == "region.switch_rejected"


@pytest.mark.asyncio
async def test_switch_records_audit_on_conflict(monkeypatch):
    """Kleinigkeit aus Fix-Runde 1: auch der 409-Pfad (bereits laufender
    Regionswechsel/Update) muss auditiert werden."""
    monkeypatch.setattr(geofabrik, "head_size_bytes", _async_size(int(1 * GB)))
    monkeypatch.setattr(os.path, "exists", lambda p: False)
    monkeypatch.setattr(region_switch, "is_busy", lambda: True)

    test_app = _make_app_with_superadmin_and_db()
    audit_mock = AsyncMock()
    with patch("app.api.routes.region.audit.record", new=audit_mock):
        transport = ASGITransport(app=test_app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                "/api/admin/region",
                json={"url": URL},
                headers={"Authorization": "Bearer x"},
            )
    assert resp.status_code == 409
    audit_mock.assert_awaited_once()
    args, kwargs = audit_mock.call_args
    assert args[1] == "region.switch_rejected"


@pytest.mark.asyncio
async def test_trigger_update_409_when_exclusive_create_races(monkeypatch):
    """Spiegelbild zu test_switch_returns_409_when_write_request_races: auch
    TRIGGER_FILE wird jetzt exklusiv angelegt ("x"-Modus). Der Vorab-Check
    (os.path.exists) wird hier bewusst bestanden (False), damit ausschliesslich
    das exklusive Anlegen selbst die Race abfängt."""
    monkeypatch.setattr(admin.os.path, "exists", lambda p: False)
    monkeypatch.setattr(region_switch, "is_busy", lambda: False)

    log_mock = mock_open()

    def _open_side_effect(path, mode="r", *a, **k):
        if path == admin.TRIGGER_FILE and mode == "x":
            raise FileExistsError(17, "File exists", path)
        return log_mock(path, mode, *a, **k)

    test_app = _make_app_with_superadmin()
    with patch("builtins.open", side_effect=_open_side_effect), patch("os.makedirs"):
        transport = ASGITransport(app=test_app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                "/api/admin/trigger-update", headers={"Authorization": "Bearer x"}
            )
    assert resp.status_code == 409


@pytest.mark.asyncio
async def test_geofabrik_list_regions_skips_entry_without_pbf_url(monkeypatch):
    """Testet den Skip-Zweig direkt in geofabrik.list_regions(): ein Eintrag
    ganz ohne urls.pbf (z. B. eine reine SHP-Region) wird aus der Liste
    entfernt statt mit einer fehlenden oder fremden URL zu erscheinen."""
    monkeypatch.setattr(geofabrik, "_region_index_cache", None)

    features = [
        {
            "properties": {
                "id": "shp-only",
                "name": "Nur-SHP-Region",
                "urls": {"shp": "https://download.geofabrik.de/shp-only-latest-free.shp.zip"},
            }
        },
        {
            "properties": {
                "id": "dach",
                "name": "DACH",
                "urls": {"pbf": "https://download.geofabrik.de/europe/dach-latest.osm.pbf"},
            }
        },
    ]

    class _FakeResponse:
        def raise_for_status(self):
            pass

        def json(self):
            return {"type": "FeatureCollection", "features": features}

    class _FakeAsyncClient:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def get(self, url):
            return _FakeResponse()

    monkeypatch.setattr(geofabrik.httpx, "AsyncClient", _FakeAsyncClient)

    entries = await geofabrik.list_regions()
    ids = {e.id for e in entries}
    assert ids == {"dach"}
    assert "shp-only" not in ids
