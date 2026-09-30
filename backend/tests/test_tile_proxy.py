"""Kachel-Proxy: Cache, Auffrischung, Ausfälle, Grenzen — ohne einen echten Abruf.

Der Kachelserver ist hier ein ``httpx.MockTransport``, der jede Anfrage zählt.
Damit lässt sich prüfen, worauf es gegenüber dem OSM-Server ankommt: dass eine
Kachel nur einmal geholt wird, egal wie viele Browser sie gleichzeitig wollen.
"""

import asyncio
import os
import time

import httpx
import pytest
from httpx import ASGITransport, AsyncClient

from app.config import settings
from app.services import rate_limit, tile_proxy

PNG = b"\x89PNG\r\n\x1a\n" + b"kachel"
JPEG = b"\xff\xd8\xff\xe0" + b"kachel"


class Kachelserver:
    """Zählt Abrufe, antwortet mit PNG oder mit einem Fehlercode."""

    def __init__(self, status: int = 200, body: bytes = PNG, delay: float = 0.0):
        self.status, self.body, self.delay = status, body, delay
        self.abrufe: list[httpx.Request] = []

    async def handler(self, request: httpx.Request) -> httpx.Response:
        self.abrufe.append(request)
        if self.delay:
            await asyncio.sleep(self.delay)
        return httpx.Response(self.status, content=self.body if self.status == 200 else b"")


@pytest.fixture
def cache(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "tile_cache_dir", str(tmp_path))
    monkeypatch.setattr(settings, "tile_upstream_url", "https://tile.openstreetmap.org/{z}/{x}/{y}.png")
    return tmp_path


@pytest.fixture
def server(monkeypatch):
    """Ersetzt den HTTP-Client des Proxys durch einen mit Mock-Transport —
    Kopfzeilen wie der User-Agent bleiben dabei die des Proxys."""
    srv = Kachelserver()
    echt = httpx.AsyncClient

    def client_mit_mock(*args, **kwargs):
        return echt(*args, transport=httpx.MockTransport(srv.handler), **kwargs)

    monkeypatch.setattr(tile_proxy.httpx, "AsyncClient", client_mit_mock)
    return srv


# ── Grundlagen ────────────────────────────────────────────────────────────────

@pytest.mark.parametrize(("z", "x", "y", "ok"), [
    (0, 0, 0, True), (19, 2**19 - 1, 2**19 - 1, True),
    (20, 0, 0, False), (-1, 0, 0, False), (3, 8, 0, False), (3, 0, -1, False),
])
def test_nur_gueltige_kacheln(z, x, y, ok):
    assert tile_proxy.valid(z, x, y) is ok


def test_vorabladen_klein_beim_osm_server(monkeypatch):
    monkeypatch.setattr(settings, "tile_upstream_url", "https://tile.openstreetmap.org/{z}/{x}/{y}.png")
    assert tile_proxy.prefetch_profile() == {"zooms": [12, 13, 14], "max_tiles": 1500}


def test_vorabladen_voll_mit_eigenem_kachelserver(monkeypatch):
    monkeypatch.setattr(settings, "tile_upstream_url", "https://kacheln.example.de/{z}/{x}/{y}.png")
    assert tile_proxy.prefetch_profile()["max_tiles"] == 8000


def test_bildtyp_aus_den_bytes():
    assert tile_proxy.media_type(PNG) == "image/png"
    assert tile_proxy.media_type(JPEG) == "image/jpeg"
    assert tile_proxy.media_type(b"RIFF\x00\x00\x00\x00WEBPVP8 ") == "image/webp"


# ── Cache ─────────────────────────────────────────────────────────────────────

async def test_einmal_holen_danach_von_der_platte(cache, server):
    assert await tile_proxy.get_tile(12, 2200, 1343) == PNG
    assert await tile_proxy.get_tile(12, 2200, 1343) == PNG
    assert len(server.abrufe) == 1
    assert (cache / "12" / "2200" / "1343.tile").read_bytes() == PNG


async def test_user_agent_nennt_die_instanz(cache, server, monkeypatch):
    monkeypatch.setattr(settings, "app_base_url", "https://convoy.example.de")
    await tile_proxy.get_tile(1, 0, 0)
    ua = server.abrufe[0].headers["user-agent"]
    assert ua == f"ConvoyPlan/{settings.app_version} (+https://convoy.example.de)"


async def test_gleichzeitige_anfragen_ein_abruf(cache, server):
    server.delay = 0.05
    ergebnisse = await asyncio.gather(*(tile_proxy.get_tile(5, 3, 4) for _ in range(20)))
    assert all(r == PNG for r in ergebnisse)
    assert len(server.abrufe) == 1


async def test_veraltete_kachel_wird_aufgefrischt(cache, server):
    await tile_proxy.get_tile(3, 1, 1)
    alt = time.time() - (settings.tile_cache_max_age_days + 1) * 86400
    os.utime(tile_proxy.cache_path(3, 1, 1), (alt, alt))
    await tile_proxy.get_tile(3, 1, 1)
    assert len(server.abrufe) == 2


async def test_bei_ausfall_die_alte_kachel(cache, server):
    await tile_proxy.get_tile(3, 2, 2)
    alt = time.time() - (settings.tile_cache_max_age_days + 1) * 86400
    os.utime(tile_proxy.cache_path(3, 2, 2), (alt, alt))
    server.status = 503
    assert await tile_proxy.get_tile(3, 2, 2) == PNG


async def test_ohne_cache_und_mit_ausfall_keine_kachel(cache, server):
    server.status = 429
    with pytest.raises(tile_proxy.TileUnavailable):
        await tile_proxy.get_tile(4, 1, 1)
    assert not tile_proxy.cache_path(4, 1, 1).exists()


def test_cache_wird_auf_die_obergrenze_verkleinert(tmp_path):
    for i in range(10):
        p = tmp_path / "10" / str(i) / "0.tile"
        p.parent.mkdir(parents=True)
        p.write_bytes(b"x" * 100)
        os.utime(p, (1000 + i, 1000 + i))  # 0 ist die älteste
    geloescht = tile_proxy.prune(tmp_path, max_bytes=500)
    uebrig = sorted(int(p.parent.name) for p in tmp_path.rglob("*.tile"))
    assert geloescht == 6
    assert uebrig == [6, 7, 8, 9]  # 400 Bytes ≤ 90 % von 500, die jüngsten bleiben


def test_unter_der_obergrenze_bleibt_alles(tmp_path):
    p = tmp_path / "1" / "0" / "0.tile"
    p.parent.mkdir(parents=True)
    p.write_bytes(b"x" * 100)
    assert tile_proxy.prune(tmp_path, max_bytes=500) == 0


# ── HTTP ──────────────────────────────────────────────────────────────────────

@pytest.fixture
async def http(cache, server):
    from app.main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield client


async def test_http_kachel_mit_cache_kopf(http, server):
    r = await http.get("/api/tiles/12/2200/1343.png")
    assert r.status_code == 200
    assert r.headers["content-type"] == "image/png"
    assert "max-age=604800" in r.headers["cache-control"]
    assert r.content == PNG


async def test_http_ohne_anmeldung(http):
    """Der Tracking-Link hat keine Anmeldung — die Kacheln müssen trotzdem kommen."""
    r = await http.get("/api/tiles/1/0/0.png")
    assert r.status_code == 200


async def test_http_unsinnige_kachel_404(http, server):
    r = await http.get("/api/tiles/25/0/0.png")
    assert r.status_code == 404
    assert server.abrufe == []


async def test_http_kachelserver_aus_502(http, server):
    server.status = 503
    r = await http.get("/api/tiles/6/1/1.png")
    assert r.status_code == 502
    assert r.headers["cache-control"] == "no-store"


async def test_http_konfiguration(http, monkeypatch):
    r = await http.get("/api/tiles/config")
    assert r.json() == {
        "url": "/api/tiles/{z}/{x}/{y}.png",
        "prefetch": {"zooms": [12, 13, 14], "max_tiles": 1500},
    }


async def test_http_rate_limit(http, monkeypatch):
    monkeypatch.setattr(settings, "rate_limit_enabled", True)
    monkeypatch.setattr(settings, "tile_rate_limit_per_minute", 3)
    rate_limit.reset()
    codes = [(await http.get(f"/api/tiles/2/{i % 4}/0.png")).status_code for i in range(4)]
    assert codes == [200, 200, 200, 429]


async def test_abbruch_eines_anfragers_trifft_die_anderen_nicht(cache, server):
    """Der Browser, der den Abruf ausgelöst hat, bricht ab — die anderen
    bekommen ihre Kachel trotzdem, und sie wird trotzdem gespeichert."""
    server.delay = 0.05
    erster = asyncio.create_task(tile_proxy.get_tile(7, 5, 5))
    await asyncio.sleep(0.01)
    zweiter = asyncio.create_task(tile_proxy.get_tile(7, 5, 5))
    await asyncio.sleep(0.005)
    erster.cancel()
    assert await zweiter == PNG
    assert len(server.abrufe) == 1
    await asyncio.sleep(0.01)
    assert tile_proxy.cache_path(7, 5, 5).read_bytes() == PNG
