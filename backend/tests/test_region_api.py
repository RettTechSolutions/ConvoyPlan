"""Tests fuer den Preview-Endpunkt des Regionswechsels (Task 4).

Verwendet das im Repo etablierte Testmuster (siehe test_admin.py): ein
ASGITransport-Client gegen die echte FastAPI-App, mit Dependency-Override
fuer `require_superadmin` statt echter Fixtures (die im Brief genannten
`client`/`superadmin_headers`/`db`-Fixtures existieren in conftest.py nicht).
"""
from unittest.mock import MagicMock

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app
from app.services import geofabrik

GB = 1024 ** 3
URL = "https://download.geofabrik.de/europe/dach-latest.osm.pbf"


def _superadmin():
    user = MagicMock()
    user.is_superadmin = True
    return user


def _make_app_with_superadmin():
    from app.api.deps import require_superadmin
    app.dependency_overrides[require_superadmin] = lambda: _superadmin()
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
