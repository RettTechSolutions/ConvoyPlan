"""Kachel-Proxy mit Plattencache — die Karte lädt ihre Kacheln von der eigenen Instanz.

Bisher holte jeder Browser seine Kacheln direkt bei tile.openstreetmap.org. Damit
ging die IP-Adresse jedes Nutzers — auch jedes Fahrers am Tracking-Link — an die
OSM Foundation, und der AV-Vertrag hätte sie als Empfänger führen müssen. Über
den Proxy sieht der Kachelserver nur noch die Instanz.

Der Cache ist gemeinsam: Eine Kachel, die ein Nutzer geladen hat, holt der
nächste von der Platte. Das senkt die Last auf dem Kachelserver, und darum geht
es in dessen Nutzungsregeln (https://operations.osmfoundation.org/policies/tiles/).
Ein Vorabladen großer Mengen bleibt dort trotzdem unerwünscht; deshalb liefert
``prefetch_profile()`` für den OSM-Server ein deutlich kleineres Profil als für
einen eigenen oder kommerziellen Kachelserver.

Kachelserver, Cachegröße und Auffrischung stehen in ``app.config`` (``tile_*``).
"""

from __future__ import annotations

import asyncio
import itertools
import logging
import os
import time
from pathlib import Path
from urllib.parse import urlparse

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

MAX_ZOOM = 19
# Gleichzeitige Abrufe beim Kachelserver — bewusst wenige, egal wie viele
# Browser gerade laden. Die OSM-Regeln verlangen maßvolle Parallelität.
_UPSTREAM_PARALLEL = 4
_TIMEOUT_S = 10.0
# Nach so vielen neu geschriebenen Kacheln wird die Cachegröße geprüft.
_PRUNE_EVERY = 256

_semaphores: dict[int, asyncio.Semaphore] = {}
_inflight: dict[str, asyncio.Task] = {}
_schreibzaehler = itertools.count(1)


class TileUnavailable(Exception):
    """Weder im Cache noch vom Kachelserver zu bekommen."""


def _semaphore() -> asyncio.Semaphore:
    # Je Event-Loop eine eigene: eine Semaphore bindet sich an die Loop, in
    # der sie zuerst wartet (in Produktion gibt es genau eine).
    loop = asyncio.get_running_loop()
    sem = _semaphores.get(id(loop))
    if sem is None:
        sem = _semaphores[id(loop)] = asyncio.Semaphore(_UPSTREAM_PARALLEL)
    return sem


def is_osm_upstream(url: str | None = None) -> bool:
    host = urlparse(url or settings.tile_upstream_url).hostname or ""
    return host == "tile.openstreetmap.org" or host.endswith(".tile.openstreetmap.org")


def prefetch_profile() -> dict:
    """Wie viel die App entlang einer Route vorab laden darf.

    Beim öffentlichen OSM-Server nur die Übersichtszooms und wenige Kacheln —
    genug, dass im Funkloch die Route auf der Karte bleibt, ohne die
    Nutzungsregeln mit einem Massenabruf zu strapazieren. Mit eigenem oder
    kommerziellem Kachelserver das volle Profil."""
    if is_osm_upstream():
        return {"zooms": [12, 13, 14], "max_tiles": 1500}
    return {"zooms": [12, 13, 14, 15, 16], "max_tiles": 8000}


def valid(z: int, x: int, y: int) -> bool:
    return 0 <= z <= MAX_ZOOM and 0 <= x < 2**z and 0 <= y < 2**z


def cache_path(z: int, x: int, y: int) -> Path:
    return Path(settings.tile_cache_dir) / str(z) / str(x) / f"{y}.tile"


def media_type(data: bytes) -> str:
    """Bildtyp aus den ersten Bytes — ein kommerzieller Anbieter liefert unter
    Umständen JPEG oder WebP, auch wenn die URL auf .png endet."""
    if data.startswith(b"\x89PNG"):
        return "image/png"
    if data.startswith(b"\xff\xd8"):
        return "image/jpeg"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return "application/octet-stream"


def _user_agent() -> str:
    # Die OSM-Regeln verlangen einen eindeutigen User-Agent mit Kontakt.
    return f"ConvoyPlan/{settings.app_version} (+{settings.app_base_url})"


def _read_if_fresh(path: Path) -> tuple[bytes | None, bool]:
    """(Inhalt, frisch) — Inhalt None, wenn nicht im Cache."""
    try:
        stat = path.stat()
    except FileNotFoundError:
        return None, False
    fresh = time.time() - stat.st_mtime < settings.tile_cache_max_age_days * 86400
    return path.read_bytes(), fresh


def _write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(f".{os.getpid()}.tmp")
    tmp.write_bytes(data)
    os.replace(tmp, path)  # atomar: ein Leser sieht nie eine halbe Kachel


def prune(root: Path | None = None, max_bytes: int | None = None) -> int:
    """Älteste Kacheln löschen, bis der Cache unter 90 % der Obergrenze liegt.
    Gibt die Zahl der gelöschten Dateien zurück."""
    root = root or Path(settings.tile_cache_dir)
    max_bytes = max_bytes if max_bytes is not None else settings.tile_cache_max_mb * 1024 * 1024
    files = []
    total = 0
    for p in root.rglob("*.tile"):
        try:
            st = p.stat()
        except FileNotFoundError:
            continue
        files.append((st.st_mtime, st.st_size, p))
        total += st.st_size
    if total <= max_bytes:
        return 0
    target = max_bytes * 0.9
    removed = 0
    for _mtime, size, p in sorted(files):
        if total <= target:
            break
        try:
            p.unlink()
        except FileNotFoundError:
            continue
        total -= size
        removed += 1
    logger.info("Kachel-Cache verkleinert: %d Dateien gelöscht", removed)
    return removed


async def _fetch_upstream(z: int, x: int, y: int, client: httpx.AsyncClient | None) -> bytes:
    url = settings.tile_upstream_url.format(z=z, x=x, y=y)
    async with _semaphore():
        if client is not None:
            resp = await client.get(url)
        else:
            async with httpx.AsyncClient(
                timeout=_TIMEOUT_S, headers={"User-Agent": _user_agent()}
            ) as own:
                resp = await own.get(url)
    if resp.status_code != 200 or not resp.content:
        raise TileUnavailable(f"Kachelserver antwortet {resp.status_code} für {z}/{x}/{y}")
    return resp.content


async def get_tile(z: int, x: int, y: int, client: httpx.AsyncClient | None = None) -> bytes:
    """Kachel aus dem Cache oder vom Kachelserver.

    Ist die Kachel veraltet und der Kachelserver nicht erreichbar, kommt die
    alte Kachel — eine etwas ältere Karte ist im Einsatz besser als keine.

    Gleichzeitige Anfragen nach derselben Kachel lösen nur einen Abruf aus. Der
    läuft als eigener Task: Bricht der Browser ab, der ihn ausgelöst hat, laufen
    die Anfragen der anderen trotzdem weiter."""
    path = cache_path(z, x, y)
    cached, fresh = await asyncio.to_thread(_read_if_fresh, path)
    if cached is not None and fresh:
        return cached

    key = f"{z}/{x}/{y}"
    task = _inflight.get(key)
    if task is None or task.get_loop() is not asyncio.get_running_loop():
        task = asyncio.create_task(_load(z, x, y, path, cached, client))
        _inflight[key] = task
        task.add_done_callback(lambda t, k=key: _inflight.pop(k, None) if _inflight.get(k) is t else None)
    return await asyncio.shield(task)


async def _load(
    z: int, x: int, y: int, path: Path, cached: bytes | None, client: httpx.AsyncClient | None
) -> bytes:
    try:
        data = await _fetch_upstream(z, x, y, client)
    except (TileUnavailable, httpx.HTTPError) as exc:
        if cached is not None:
            logger.debug("Kachel %s/%s/%s veraltet ausgeliefert: %s", z, x, y, exc)
            return cached
        raise TileUnavailable(str(exc)) from exc
    await asyncio.to_thread(_write, path, data)
    if next(_schreibzaehler) % _PRUNE_EVERY == 0:
        await asyncio.to_thread(prune)
    return data
