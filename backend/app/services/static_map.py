"""Eine Übersichtskarte der Route als Bild — für den Ausdruck (Roadbook).

Gerendert wird hier, im Backend, und nicht als Bildschirmfoto der MapLibre-Karte
im Browser: das PDF soll dieselbe Karte zeigen, egal wer es wo herunterlädt, und
ohne dass ein Browserfenster offen sein muss (auch über die API).

Die Kacheln kommen von ``settings.roadbook_tile_url`` (Standard: dieselben
OSM-Kacheln wie im Frontend). Fällt der Kachelserver aus, entsteht trotzdem ein
Bild — die Route auf neutralem Grund mit einem Hinweis. Ein Roadbook ohne
Kartenhintergrund ist brauchbar, eines, das gar nicht entsteht, nicht.

Die Rechnung (Zoomstufe, Ausschnitt, benötigte Kacheln) ist von der
Netzwerkabfrage getrennt, damit ``tests/test_roadbook.py`` sie ohne Netz prüft.
"""
from __future__ import annotations

import asyncio
import logging
import math
from collections import OrderedDict
from dataclasses import dataclass
from io import BytesIO
from typing import Awaitable, Callable

import httpx
from PIL import Image, ImageDraw, ImageFont

from app.config import settings

logger = logging.getLogger(__name__)

TILE_SIZE = 256
MAX_ZOOM = 17
# Obergrenze je Karte. Bei 1600×1050 px sind es regulär 35–48 Kacheln; die
# Grenze fängt nur einen Fehler in der Rechnung ab, bevor er zum Massenabruf
# beim Kachelserver wird (OSM Tile Usage Policy).
MAX_TILES = 64
# OSM erlaubt höchstens zwei parallele Verbindungen je Anwendung.
_CONCURRENCY = 2
_TILE_TIMEOUT_S = 10.0

ROUTE_COLOR = (37, 99, 235)
CASING_COLOR = (255, 255, 255)
START_COLOR = (22, 163, 74)
END_COLOR = (220, 38, 38)
WAYPOINT_COLOR = (26, 39, 68)
STOP_COLOR = (217, 119, 6)
FALLBACK_BG = (236, 239, 244)

_FONT_BOLD = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"

TileFetcher = Callable[[int, int, int], Awaitable[bytes | None]]


@dataclass(frozen=True)
class Marker:
    lon: float
    lat: float
    label: str
    color: tuple[int, int, int]


@dataclass(frozen=True)
class View:
    zoom: int
    # Weltpixel der linken oberen Bildecke bei ``zoom``.
    origin_x: float
    origin_y: float
    width: int
    height: int

    def project(self, lon: float, lat: float) -> tuple[float, float]:
        x, y = world_px(lon, lat, self.zoom)
        return x - self.origin_x, y - self.origin_y

    def tiles(self) -> list[tuple[int, int]]:
        """Tile (x, y) indices covering the view — y outside the world skipped."""
        n = 2 ** self.zoom
        x0 = math.floor(self.origin_x / TILE_SIZE)
        x1 = math.floor((self.origin_x + self.width - 1) / TILE_SIZE)
        y0 = math.floor(self.origin_y / TILE_SIZE)
        y1 = math.floor((self.origin_y + self.height - 1) / TILE_SIZE)
        return [
            (tx, ty)
            for ty in range(y0, y1 + 1)
            if 0 <= ty < n
            for tx in range(x0, x1 + 1)
        ]


def world_px(lon: float, lat: float, zoom: int) -> tuple[float, float]:
    """Web-Mercator world pixel coordinates at ``zoom``."""
    lat = max(-85.0511, min(85.0511, lat))
    scale = TILE_SIZE * 2 ** zoom
    x = (lon + 180.0) / 360.0 * scale
    s = math.sin(math.radians(lat))
    y = (0.5 - math.log((1 + s) / (1 - s)) / (4 * math.pi)) * scale
    return x, y


def fit_view(
    points: list[tuple[float, float]],
    width: int,
    height: int,
    padding: float = 0.06,
) -> View:
    """Largest zoom at which all ``(lon, lat)`` points fit, with a margin.

    Die Zoomstufe sinkt außerdem, bis der Ausschnitt mit ``MAX_TILES`` auskommt
    — bei normalen Bildgrößen greift das nie.
    """
    if not points:
        raise ValueError("no points to fit")
    lons = [p[0] for p in points]
    lats = [p[1] for p in points]
    usable_w = width * (1 - 2 * padding)
    usable_h = height * (1 - 2 * padding)

    zoom = MAX_ZOOM
    while zoom > 0:
        x0, y1 = world_px(min(lons), min(lats), zoom)
        x1, y0 = world_px(max(lons), max(lats), zoom)
        if x1 - x0 <= usable_w and y1 - y0 <= usable_h:
            break
        zoom -= 1

    while True:
        x0, y1 = world_px(min(lons), min(lats), zoom)
        x1, y0 = world_px(max(lons), max(lats), zoom)
        cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
        view = View(zoom, cx - width / 2, cy - height / 2, width, height)
        if len(view.tiles()) <= MAX_TILES or zoom == 0:
            return view
        zoom -= 1


# ── Kacheln ──────────────────────────────────────────────────────────────────

# Kleiner Prozess-Cache: wer dasselbe Roadbook zweimal druckt, lädt die Kacheln
# nicht zweimal (auch das verlangt die OSM-Policy). ~20 KB je Kachel.
_CACHE_MAX = 512
_cache: OrderedDict[tuple[str, int, int, int], bytes] = OrderedDict()


def _cache_get(key: tuple[str, int, int, int]) -> bytes | None:
    data = _cache.get(key)
    if data is not None:
        _cache.move_to_end(key)
    return data


def _cache_put(key: tuple[str, int, int, int], data: bytes) -> None:
    _cache[key] = data
    _cache.move_to_end(key)
    while len(_cache) > _CACHE_MAX:
        _cache.popitem(last=False)


def http_tile_fetcher(client: httpx.AsyncClient, url_template: str) -> TileFetcher:
    sem = asyncio.Semaphore(_CONCURRENCY)

    async def fetch(z: int, x: int, y: int) -> bytes | None:
        key = (url_template, z, x, y)
        if (hit := _cache_get(key)) is not None:
            return hit
        async with sem:
            try:
                resp = await client.get(url_template.format(z=z, x=x, y=y))
            except httpx.HTTPError as exc:
                logger.info("Roadbook tile %s/%s/%s failed: %s", z, x, y, exc)
                return None
        if resp.status_code != 200:
            logger.info("Roadbook tile %s/%s/%s: HTTP %s", z, x, y, resp.status_code)
            return None
        _cache_put(key, resp.content)
        return resp.content

    return fetch


async def _fetch_tiles(view: View, fetch: TileFetcher) -> list[tuple[int, int, bytes]]:
    """Fetch the view's tiles; failed ones are simply missing."""
    n = 2 ** view.zoom
    tiles = view.tiles()
    results = await asyncio.gather(
        *(fetch(view.zoom, tx % n, ty) for tx, ty in tiles), return_exceptions=True
    )
    return [(tx, ty, data) for (tx, ty), data in zip(tiles, results) if isinstance(data, bytes)]


# ── Zeichnen ─────────────────────────────────────────────────────────────────


def _font(size: int) -> ImageFont.ImageFont | ImageFont.FreeTypeFont:
    try:
        return ImageFont.truetype(_FONT_BOLD, size)
    except OSError:
        return ImageFont.load_default(size=size)


def _draw_marker(draw: ImageDraw.ImageDraw, x: float, y: float, m: Marker, radius: int) -> None:
    draw.ellipse((x - radius - 3, y - radius - 3, x + radius + 3, y + radius + 3), fill=(255, 255, 255))
    draw.ellipse((x - radius, y - radius, x + radius, y + radius), fill=m.color)
    font = _font(int(radius * (1.15 if len(m.label) < 2 else 0.9)))
    draw.text((x, y), m.label, fill=(255, 255, 255), font=font, anchor="mm")


def _draw_note(img: Image.Image, text: str, corner: str) -> None:
    draw = ImageDraw.Draw(img)
    font = _font(max(12, img.width // 90))
    left, top, right, bottom = draw.textbbox((0, 0), text, font=font)
    pad = 6
    w, h = right - left + 2 * pad, bottom - top + 2 * pad
    x = img.width - w if corner == "br" else 0
    y = img.height - h if corner in ("br", "bl") else 0
    draw.rectangle((x, y, x + w, y + h), fill=(255, 255, 255))
    draw.text((x + pad - left, y + pad - top), text, fill=(60, 60, 60), font=font)


async def render_route_map(
    coords: list[list[float]] | list[tuple[float, float]],
    markers: list[Marker],
    width: int = 1600,
    height: int = 1050,
    fetch: TileFetcher | None = None,
) -> bytes:
    """Render the route (``[lon, lat]`` pairs) with markers as a JPEG.

    Geladen wird im Event-Loop, gezeichnet im Thread: Zusammensetzen, Linie und
    JPEG sind reine CPU-Arbeit und hielten sonst jede andere Anfrage auf.
    """
    route = [(float(c[0]), float(c[1])) for c in coords]
    view = fit_view(route + [(m.lon, m.lat) for m in markers], width, height)

    template = settings.roadbook_tile_url
    tiles: list[tuple[int, int, bytes]] = []
    if fetch is not None:
        tiles = await _fetch_tiles(view, fetch)
    elif template:
        headers = {"User-Agent": f"ConvoyPlan/{settings.app_version} (Roadbook)"}
        async with httpx.AsyncClient(timeout=_TILE_TIMEOUT_S, headers=headers) as client:
            tiles = await _fetch_tiles(view, http_tile_fetcher(client, template))
    return await asyncio.to_thread(_draw, view, tiles, route, markers)


def _draw(
    view: View,
    tiles: list[tuple[int, int, bytes]],
    route: list[tuple[float, float]],
    markers: list[Marker],
) -> bytes:
    img = Image.new("RGB", (view.width, view.height), FALLBACK_BG)
    has_tiles = False
    for tx, ty, data in tiles:
        try:
            tile = Image.open(BytesIO(data)).convert("RGB")
        except Exception:
            continue
        img.paste(tile, (round(tx * TILE_SIZE - view.origin_x), round(ty * TILE_SIZE - view.origin_y)))
        has_tiles = True

    draw = ImageDraw.Draw(img)
    line = [view.project(lon, lat) for lon, lat in route]
    stroke = max(4, view.width // 200)
    if len(line) >= 2:
        draw.line(line, fill=CASING_COLOR, width=stroke + 6, joint="curve")
        draw.line(line, fill=ROUTE_COLOR, width=stroke, joint="curve")
    radius = max(10, view.width // 80)
    for m in markers:
        x, y = view.project(m.lon, m.lat)
        _draw_marker(draw, x, y, m, radius)

    if has_tiles:
        _draw_note(img, "© OpenStreetMap-Mitwirkende", "br")
    else:
        _draw_note(img, "Kartenhintergrund nicht verfügbar", "tl")

    out = BytesIO()
    img.save(out, format="JPEG", quality=85, optimize=True)
    return out.getvalue()
