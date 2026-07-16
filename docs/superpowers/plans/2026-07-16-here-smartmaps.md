# HERE SmartMaps mit Jahresdeckel — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Eine optionale HERE-SmartMaps-Kartenansicht (HERE Raster Tile API v3) in der Hauptkarte zur Routenberechnung (`plan/+page.svelte`), umschaltbar gegen die bestehende OSM-Basemap, mit einem serverseitigen Jahresdeckel (Default 250.000, Puffer unter dem 300k-Freikontingent) und stillem Fallback auf OSM-Kacheln bei erreichtem Deckel oder HERE-Fehler.

**Architektur:** Ein neuer Backend-Tile-Proxy (`GET /api/tiles/here/{z}/{x}/{y}`) hält den HERE-Key serverseitig, holt Kacheln von HERE und reicht sie same-origin durch. Ein neuer Service (`smartmaps.py`) zählt Anfragen in einem In-Memory-Zähler (Modul-globaler Dict-State, `asyncio.Lock`-geschützt) mit periodischem DB-Flush (alle 30s, in `system_settings`, analog zum bestehenden Geocoding-Kostendeckel) statt eines Sync-Commits pro Tile-Request. Frontend: `MapView.svelte` bekommt eine zweite Raster-Source, deren Sichtbarkeit per Prop umgeschaltet wird; der Toggle-Button lebt auf der Plan-Seite (analog zum bestehenden `.map-actions`/`.btn-map`-Muster).

**Tech Stack:** FastAPI, SQLAlchemy (async), httpx, pytest + pytest-asyncio (`asyncio_mode = "auto"`), Svelte 5 (Runes), MapLibre GL JS.

---

## Spec-Referenz

Vollständige Design-Entscheidungen: `docs/superpowers/specs/2026-07-16-here-smartmaps-design.md`.

## File Structure

| Datei | Änderung |
|---|---|
| `backend/app/config.py` | Neues Feld `here_smartmaps_yearly_limit` |
| `.env.example` | Doku für `HERE_SMARTMAPS_YEARLY_LIMIT` |
| `backend/app/services/smartmaps.py` | **Neu** — In-Memory-Zähler + Flush-Loop |
| `backend/tests/test_smartmaps.py` | **Neu** — Unit-Tests für den Service |
| `backend/app/main.py` | Flush-Loop in `_lifespan` starten, Router registrieren, Tag-Metadaten |
| `backend/app/api/routes/tiles.py` | **Neu** — `GET /tiles/here/{z}/{x}/{y}` |
| `backend/tests/test_tiles.py` | **Neu** — HTTP-Level-Tests der Route |
| `frontend/src/lib/components/MapView.svelte` | Zweite Raster-Source + Sichtbarkeits-Toggle |
| `frontend/src/routes/o/[slug]/plan/+page.svelte` | Toggle-Button + State + Prop-Weitergabe |

Keine neue Alembic-Migration — `system_settings` existiert bereits (siehe `backend/app/models/settings.py`).

---

## Task 1: Config-Feld für den Jahresdeckel

**Files:**
- Modify: `backend/app/config.py:154` (nach `here_monthly_limit`, vor `docs_api_key` in Zeile 156)
- Modify: `.env.example:123` (nach der `HERE_MONTHLY_LIMIT`-Doku)

- [ ] **Step 1: Config-Feld einfügen**

In `backend/app/config.py`, direkt nach Zeile 154 (`here_monthly_limit: int = 25000`), folgenden Block einfügen:

```python

    # Jahresdeckel für HERE SmartMaps (Raster Tile API v3) in der Hauptkarte:
    # maximal so viele Tile-Anfragen pro Kalenderjahr. Ist der Deckel erreicht,
    # liefert die Kachel-Proxy-Route für den Rest des Jahres OSM-Kacheln statt
    # HERE (kein Ausfall, keine Kosten). HERE stellt ein Freikontingent von
    # 300.000 Tile-Anfragen/Jahr — der Standard 250.000 lässt bewusst Puffer,
    # damit nie abgerechnet wird. 0 = kein App-Deckel (dann greift nur HEREs
    # eigenes Kontingent).
    here_smartmaps_yearly_limit: int = 250000
```

- [ ] **Step 2: `.env.example` dokumentieren**

In `.env.example`, direkt nach Zeile 123 (`# HERE_MONTHLY_LIMIT=25000`), folgenden Block einfügen:

```
#
# HERE SmartMaps (Kartenkacheln, optional, nur in der Hauptkarte zur
# Routenberechnung): nutzt denselben Key wie oben. Jahresdeckel analog zum
# Geocoding-Kostendeckel — HEREs Freikontingent liegt bei 300.000
# Tile-Anfragen/Jahr, der Standard 250.000 lässt Puffer. Bei erreichtem
# Deckel (oder HERE-Fehler) liefert die Kachel-Route automatisch OSM-Kacheln.
# 0 = kein App-Deckel.
# HERE_SMARTMAPS_YEARLY_LIMIT=250000
```

- [ ] **Step 3: Import-Check**

Run: `cd backend && python -c "from app.config import settings; print(settings.here_smartmaps_yearly_limit)"`
Expected: `250000`

- [ ] **Step 4: Commit**

```bash
git add backend/app/config.py .env.example
git commit -m "feat: Config-Feld für HERE-SmartMaps-Jahresdeckel"
```

---

## Task 2: Service `smartmaps.py` — In-Memory-Zähler mit periodischem Flush

**Files:**
- Create: `backend/app/services/smartmaps.py`
- Test: `backend/tests/test_smartmaps.py`

- [ ] **Step 1: Test-Datei mit fehlschlagenden Tests schreiben**

Erstelle `backend/tests/test_smartmaps.py`. Das Fake-DB-Muster ist wörtlich von `backend/tests/test_geocoding.py` übernommen (dort testet es `reserve_here_quota`), erweitert um eine `store`-Introspektion für die Flush-Assertions:

```python
import pytest

from app.services import smartmaps


class _FakeDB:
    """Minimaler AsyncSession-Ersatz über einem key→SystemSetting-Dict."""

    def __init__(self):
        self.store = {}

    async def execute(self, stmt):
        key = stmt.compile().params.get("key_1")
        row = self.store.get(key)

        class _Result:
            def scalar_one_or_none(self):
                return row

        return _Result()

    def add(self, obj):
        self.store[obj.key] = obj

    async def commit(self):
        pass


@pytest.fixture(autouse=True)
def _reset_state():
    smartmaps.reset()
    yield
    smartmaps.reset()


async def test_reserve_quota_disabled_when_limit_zero():
    db = _FakeDB()
    assert await smartmaps.reserve_tile_quota(db, "2026", 0) is True
    assert await smartmaps.reserve_tile_quota(db, "2026", 0) is True
    # Deckel deaktiviert -> kein Zählerstand wird geführt
    await smartmaps.flush_pending(db)
    assert db.store == {}


async def test_reserve_quota_counts_up_and_caps():
    db = _FakeDB()
    assert await smartmaps.reserve_tile_quota(db, "2026", 3) is True
    assert await smartmaps.reserve_tile_quota(db, "2026", 3) is True
    assert await smartmaps.reserve_tile_quota(db, "2026", 3) is True
    # Deckel erreicht -> vierte Reservierung schlägt fehl
    assert await smartmaps.reserve_tile_quota(db, "2026", 3) is False


async def test_flush_pending_writes_new_row():
    db = _FakeDB()
    await smartmaps.reserve_tile_quota(db, "2026", 100)
    await smartmaps.reserve_tile_quota(db, "2026", 100)
    await smartmaps.flush_pending(db)
    assert db.store["smartmaps.tile_usage.2026"].value == "2"
    # Nach dem Flush sind keine weiteren Anfragen mehr pending
    assert await smartmaps.reserve_tile_quota(db, "2026", 100) is True
    await smartmaps.flush_pending(db)
    assert db.store["smartmaps.tile_usage.2026"].value == "3"


async def test_flush_pending_accumulates_on_existing_row():
    from app.models.settings import SystemSetting

    db = _FakeDB()
    db.store["smartmaps.tile_usage.2026"] = SystemSetting(key="smartmaps.tile_usage.2026", value="10")
    # Zähler noch nicht im Speicher geladen -> lazy-load beim ersten reserve
    assert await smartmaps.reserve_tile_quota(db, "2026", 12) is True
    assert await smartmaps.reserve_tile_quota(db, "2026", 12) is True
    # Deckel (12) durch die vorhandenen 10 + 2 pending erreicht
    assert await smartmaps.reserve_tile_quota(db, "2026", 12) is False
    await smartmaps.flush_pending(db)
    assert db.store["smartmaps.tile_usage.2026"].value == "12"


async def test_flush_pending_noop_when_nothing_pending():
    db = _FakeDB()
    await smartmaps.flush_pending(db)
    assert db.store == {}
```

- [ ] **Step 2: Tests ausführen, um das Fehlschlagen zu bestätigen**

Run: `cd backend && pytest tests/test_smartmaps.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.services.smartmaps'` (oder `ImportError`)

- [ ] **Step 3: Service implementieren**

Erstelle `backend/app/services/smartmaps.py`:

```python
"""Jahresdeckel für HERE-SmartMaps-Kachelanfragen (Raster Tile API v3).

Kartenkacheln entstehen in Bürsten (20–50 Anfragen pro Kartenschwenk), im
Gegensatz zur Adresssuche (`geocoding.py`), die pro Anfrage synchron in
``system_settings`` schreibt. Ein Sync-Commit pro Tile wäre unnötige DB-Last,
deshalb zählt dieser Service in einem In-Memory-Zähler und flusht periodisch
(``smartmaps_flush_loop``, gestartet in ``app.main._lifespan``).

Limitierung: der Zähler ist pro Prozess und überlebt keinen Neustart ohne
vorherigen Flush. Das Backend läuft laut docker-compose.yml als Single-Process
(kein ``--workers``, keine ``deploy.replicas``) — für einen künftigen
Multi-Replica-Betrieb bräuchte es einen shared Store (Redis o.ä.), analog zur
in ``rate_limit.py`` dokumentierten Einschränkung.
"""
import asyncio
import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.settings import SystemSetting

logger = logging.getLogger(__name__)

_USAGE_KEY_PREFIX = "smartmaps.tile_usage"

# Jahr ("YYYY") -> zuletzt aus der DB gelesener Stand.
_flushed: dict[str, int] = {}
# Jahr -> seit dem letzten Flush reservierte, noch nicht geschriebene Anfragen.
_pending: dict[str, int] = {}
_lock = asyncio.Lock()


def usage_key(year: str) -> str:
    """system_settings-Schlüssel für den HERE-Tile-Zähler eines Jahres ("YYYY")."""
    return f"{_USAGE_KEY_PREFIX}.{year}"


async def _load_flushed(db: AsyncSession, year: str) -> int:
    row = (
        await db.execute(select(SystemSetting).where(SystemSetting.key == usage_key(year)))
    ).scalar_one_or_none()
    if row is None:
        return 0
    try:
        return int(row.value)
    except (TypeError, ValueError):
        return 0


async def reserve_tile_quota(db: AsyncSession, year: str, limit: int) -> bool:
    """Eine HERE-Tile-Anfrage im Jahresbudget verbuchen.

    Gibt ``True`` zurück und zählt hoch, wenn noch Budget frei ist; ``False``,
    wenn der Deckel erreicht ist (Aufrufer fällt dann auf OSM zurück).
    ``limit <= 0`` deaktiviert den Deckel (immer ``True``, kein Zähler).
    """
    if limit <= 0:
        return True

    async with _lock:
        if year not in _flushed:
            _flushed[year] = await _load_flushed(db, year)
        used = _flushed[year] + _pending.get(year, 0)
        if used >= limit:
            return False
        _pending[year] = _pending.get(year, 0) + 1
        return True


async def flush_pending(db: AsyncSession) -> None:
    """Alle seit dem letzten Aufruf reservierten Anfragen in die DB schreiben."""
    async with _lock:
        to_flush = {year: count for year, count in _pending.items() if count > 0}
        if not to_flush:
            return
        for year, count in to_flush.items():
            key = usage_key(year)
            row = (
                await db.execute(select(SystemSetting).where(SystemSetting.key == key))
            ).scalar_one_or_none()
            new_total = _flushed.get(year, 0) + count
            if row is not None:
                row.value = str(new_total)
            else:
                db.add(SystemSetting(key=key, value=str(new_total)))
            _flushed[year] = new_total
            _pending[year] = 0
        await db.commit()


async def smartmaps_flush_loop() -> None:
    """Background-Loop: schreibt alle 30s den In-Memory-Zähler in die DB.

    Gestartet in ``app.main._lifespan`` neben ``update_notify_loop`` (gleiches
    Muster: sleep-Loop, CancelledError durchreichen, sonst weiterlaufen).
    """
    from app.database import AsyncSessionLocal

    interval = 30
    while True:
        await asyncio.sleep(interval)
        try:
            async with AsyncSessionLocal() as db:
                await flush_pending(db)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("SmartMaps-Tile-Zähler-Flush fehlgeschlagen")


def reset() -> None:
    """Zähler zurücksetzen (nur für Tests)."""
    _flushed.clear()
    _pending.clear()
```

- [ ] **Step 4: Tests ausführen, um das Bestehen zu bestätigen**

Run: `cd backend && pytest tests/test_smartmaps.py -v`
Expected: PASS (5 Tests)

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/smartmaps.py backend/tests/test_smartmaps.py
git commit -m "feat: In-Memory-Jahreszähler für HERE-SmartMaps-Kacheln"
```

---

## Task 3: Flush-Loop in den App-Lifespan einhängen

**Files:**
- Modify: `backend/app/main.py:106-122` (`_lifespan`)

- [ ] **Step 1: Zweiten Background-Task starten und sauber beenden**

In `backend/app/main.py`, den bestehenden `_lifespan` wie folgt erweitern (neue/geänderte Zeilen markiert):

```python
@asynccontextmanager
async def _lifespan(_app: FastAPI):
    _verify_security_config()
    # Update-Benachrichtigung (Modus "notify"): prüft periodisch, ob im
    # aktiven Kanal ein Update verfügbar ist, und mailt die Superadmins.
    # Schläft vor dem ersten Check, belastet den Start also nicht.
    from app.services.update_notify import update_notify_loop
    notify_task = asyncio.create_task(update_notify_loop())
    # SmartMaps-Tile-Zähler: In-Memory-Jahresbudget wird alle 30s in die DB
    # geflusht, statt pro Tile-Request synchron zu schreiben (Tiles entstehen
    # in Bürsten von 20-50 Anfragen pro Kartenschwenk).
    from app.services.smartmaps import flush_pending, smartmaps_flush_loop
    smartmaps_task = asyncio.create_task(smartmaps_flush_loop())
    try:
        yield
    finally:
        # Sauberes Herunterfahren: Tasks abbrechen und auf ihr Ende warten.
        # CancelledError ist dabei der Normalfall; gather liefert ihn (statt
        # ihn zu werfen), sodass der Shutdown nie an ihm scheitert.
        notify_task.cancel()
        smartmaps_task.cancel()
        outcome = await asyncio.gather(notify_task, smartmaps_task, return_exceptions=True)
        logger.debug("Update-Notify-/SmartMaps-Flush-Task beendet: %r", outcome)
        # Letzter Flush, damit bei Redeploys kein Zählstand verloren geht.
        from app.database import AsyncSessionLocal
        async with AsyncSessionLocal() as db:
            await flush_pending(db)
```

- [ ] **Step 2: Backend startet fehlerfrei**

Run: `cd backend && python -c "from app.main import app; print('ok')"`
Expected: `ok` (kein Import-/Syntaxfehler)

- [ ] **Step 3: Commit**

```bash
git add backend/app/main.py
git commit -m "feat: SmartMaps-Flush-Loop in App-Lifespan starten"
```

---

## Task 4: Tile-Proxy-Route `GET /tiles/here/{z}/{x}/{y}`

**Files:**
- Create: `backend/app/api/routes/tiles.py`
- Modify: `backend/app/main.py` (Import, Tag-Metadaten, `include_router`)
- Test: `backend/tests/test_tiles.py`

- [ ] **Step 1: Test-Datei mit fehlschlagenden Tests schreiben**

Erstelle `backend/tests/test_tiles.py`. Das HTTP-Client-Muster (`ASGITransport` + `dependency_overrides`) ist von `backend/tests/test_demo.py` übernommen, das HERE/HTTP-Mocking-Muster von `backend/tests/test_geocoding.py`:

```python
import uuid
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
from httpx import ASGITransport, AsyncClient

from app.api.deps import get_current_user
from app.api.routes import tiles as tiles_route
from app.database import get_db
from app.main import app


def _user():
    u = MagicMock()
    u.id = uuid.uuid4()
    u.is_active = True
    u.is_superadmin = False
    return u


async def _db_override():
    yield MagicMock()


class _HereClient:
    """Mock-HTTP-Client für den HERE-Tile-Abruf (analog zu test_geocoding.py)."""

    payload: bytes = b"PNGDATA"
    raises: bool = False

    def __init__(self, *a, **k):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *e):
        return False

    async def get(self, url, params=None):
        if _HereClient.raises:
            raise httpx.ConnectError("boom")
        return httpx.Response(200, content=_HereClient.payload, request=httpx.Request("GET", url))


@pytest.fixture(autouse=True)
def _setup_overrides():
    app.dependency_overrides[get_current_user] = _user
    app.dependency_overrides[get_db] = _db_override
    yield
    app.dependency_overrides.clear()


async def test_tile_without_here_key_falls_back_to_osm(monkeypatch):
    monkeypatch.setattr(tiles_route.geo_svc, "resolve_here_key", AsyncMock(return_value=""))

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/tiles/here/5/16/10", follow_redirects=False)

    assert resp.status_code == 302
    assert resp.headers["location"] == "https://tile.openstreetmap.org/5/16/10.png"


async def test_tile_falls_back_to_osm_when_quota_exhausted(monkeypatch):
    monkeypatch.setattr(tiles_route.geo_svc, "resolve_here_key", AsyncMock(return_value="KEY"))
    monkeypatch.setattr(tiles_route.smartmaps_svc, "reserve_tile_quota", AsyncMock(return_value=False))
    monkeypatch.setattr(tiles_route.settings, "here_smartmaps_yearly_limit", 250000)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/tiles/here/5/16/10", follow_redirects=False)

    assert resp.status_code == 302
    assert resp.headers["location"] == "https://tile.openstreetmap.org/5/16/10.png"


async def test_tile_proxies_here_response(monkeypatch):
    monkeypatch.setattr(tiles_route.geo_svc, "resolve_here_key", AsyncMock(return_value="KEY"))
    monkeypatch.setattr(tiles_route.smartmaps_svc, "reserve_tile_quota", AsyncMock(return_value=True))
    monkeypatch.setattr(tiles_route.settings, "here_smartmaps_yearly_limit", 250000)
    _HereClient.raises = False
    _HereClient.payload = b"PNGDATA"
    monkeypatch.setattr(tiles_route.httpx, "AsyncClient", _HereClient)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/tiles/here/5/16/10", follow_redirects=False)

    assert resp.status_code == 200
    assert resp.content == b"PNGDATA"
    assert resp.headers["content-type"] == "image/png"


async def test_tile_falls_back_to_osm_on_here_error(monkeypatch):
    monkeypatch.setattr(tiles_route.geo_svc, "resolve_here_key", AsyncMock(return_value="KEY"))
    monkeypatch.setattr(tiles_route.smartmaps_svc, "reserve_tile_quota", AsyncMock(return_value=True))
    monkeypatch.setattr(tiles_route.settings, "here_smartmaps_yearly_limit", 250000)
    _HereClient.raises = True
    monkeypatch.setattr(tiles_route.httpx, "AsyncClient", _HereClient)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.get("/api/tiles/here/5/16/10", follow_redirects=False)

    assert resp.status_code == 302
    assert resp.headers["location"] == "https://tile.openstreetmap.org/5/16/10.png"
```

- [ ] **Step 2: Tests ausführen, um das Fehlschlagen zu bestätigen**

Run: `cd backend && pytest tests/test_tiles.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.api.routes.tiles'`

- [ ] **Step 3: Route implementieren**

Erstelle `backend/app/api/routes/tiles.py`:

```python
import logging
from datetime import datetime, timezone

import httpx
from fastapi import APIRouter, Depends, Response
from fastapi.responses import RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.config import settings
from app.database import get_db
from app.models.user import User
from app.services import geocoding as geo_svc
from app.services import smartmaps as smartmaps_svc

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/tiles", tags=["tiles"])

HERE_TILE_URL = "https://maps.hereapi.com/v3/base/mc/{z}/{x}/{y}/png8"
OSM_TILE_URL = "https://tile.openstreetmap.org/{z}/{x}/{y}.png"
_TIMEOUT = 8.0


@router.get("/here/{z}/{x}/{y}")
async def get_here_tile(
    z: int,
    x: int,
    y: int,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_user),
):
    """HERE-SmartMaps-Kachel (Raster Tile API v3), serverseitig proxied.

    Der HERE-Key bleibt serverseitig — das Frontend fragt nur diesen Proxy an.
    Ein Jahresdeckel (``HERE_SMARTMAPS_YEARLY_LIMIT``) verbucht jede Anfrage im
    In-Memory-Zähler aus ``smartmaps.py`` und fällt bei erreichtem Deckel —
    wie auch bei jedem HERE-Fehler — auf die OSM-Kachel zurück.
    """
    osm_url = OSM_TILE_URL.format(z=z, x=x, y=y)

    here_key = await geo_svc.resolve_here_key(db)
    if here_key and settings.here_smartmaps_yearly_limit > 0:
        year = datetime.now(timezone.utc).strftime("%Y")
        if not await smartmaps_svc.reserve_tile_quota(db, year, settings.here_smartmaps_yearly_limit):
            here_key = ""

    if not here_key:
        return RedirectResponse(url=osm_url, status_code=302)

    tile_url = HERE_TILE_URL.format(z=z, x=x, y=y)
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.get(tile_url, params={"style": "explore.day", "apiKey": here_key})
            resp.raise_for_status()
            return Response(content=resp.content, media_type="image/png")
    except Exception as exc:
        logger.warning("HERE-Tile-Abruf fehlgeschlagen, Fallback auf OSM: %s", exc)
        return RedirectResponse(url=osm_url, status_code=302)
```

- [ ] **Step 4: Router in `main.py` registrieren**

In `backend/app/main.py`, Zeile 18, `tiles` zum Import-Tupel hinzufügen:

```python
from app.api.routes import (
    tracking, weather, overpass, status, users, leitstellen, traffic, geocoding, tiles,
)
```

Tag-Metadaten (nach Zeile 72, dem `"traffic"`-Eintrag) ergänzen:

```python
    {"name": "tiles", "description": "Kartenkacheln (HERE SmartMaps, mit OSM-Fallback bei Jahresdeckel)."},
```

Router-Registrierung (direkt nach `app.include_router(geocoding.router, prefix="/api")`) ergänzen:

```python
app.include_router(tiles.router, prefix="/api")
```

- [ ] **Step 5: Tests ausführen, um das Bestehen zu bestätigen**

Run: `cd backend && pytest tests/test_tiles.py -v`
Expected: PASS (4 Tests)

- [ ] **Step 6: Vollen Backend-Testlauf gegen Regressionen prüfen**

Run: `cd backend && pytest tests/ -v --tb=short`
Expected: alle Tests PASS (keine Regressionen durch die neue Route/den neuen Service)

- [ ] **Step 7: Commit**

```bash
git add backend/app/api/routes/tiles.py backend/app/main.py backend/tests/test_tiles.py
git commit -m "feat: Tile-Proxy-Route für HERE SmartMaps mit OSM-Fallback"
```

---

## Task 5: `MapView.svelte` — zweite Raster-Source mit Sichtbarkeits-Toggle

**Files:**
- Modify: `frontend/src/lib/components/MapView.svelte:10-54` (Props), `:93-110` (Style/Sources), `:463-478` (neuer Effect)

- [ ] **Step 1: Neue Prop `hereTilesEnabled` ergänzen**

In `frontend/src/lib/components/MapView.svelte`, das `Props`-Interface (Zeile 10-35) um ein neues optionales Feld erweitern, direkt nach `headingUp` (Zeile 34):

```typescript
	/** Heading-up: rotate the map so the followed vehicle's heading points up. */
	headingUp?: boolean;
	/** Show the HERE SmartMaps base layer instead of OSM. */
	hereTilesEnabled?: boolean;
}
```

Und in der Destrukturierung (Zeile 37-54), nach `headingUp = false,`:

```typescript
	headingUp = false,
	hereTilesEnabled = false,
}: Props = $props();
```

- [ ] **Step 2: Zweite Source + Layer im Karten-Style ergänzen**

In `frontend/src/lib/components/MapView.svelte`, den `style`-Block der Karteninitialisierung (Zeile 95-106) um die HERE-Quelle und einen zunächst unsichtbaren Layer erweitern:

```javascript
			style: {
				version: 8,
				sources: {
					osm: {
						type: 'raster',
						tiles: ['https://tile.openstreetmap.org/{z}/{x}/{y}.png'],
						tileSize: 256,
						attribution: '© OpenStreetMap contributors',
					},
					'here-smartmaps': {
						type: 'raster',
						tiles: ['/api/tiles/here/{z}/{x}/{y}'],
						tileSize: 256,
						attribution: '© HERE',
					},
				},
				layers: [
					{ id: 'osm', type: 'raster', source: 'osm' },
					{
						id: 'here-smartmaps',
						type: 'raster',
						source: 'here-smartmaps',
						layout: { visibility: 'none' },
					},
				],
			},
```

- [ ] **Step 3: Sichtbarkeits-Effect ergänzen**

In `frontend/src/lib/components/MapView.svelte`, nach dem letzten bestehenden `$effect`-Block (Live-Verkehrslage-Layer, endet Zeile 478, vor dem schließenden `</script>`), folgenden neuen Effect ergänzen:

```javascript
	// Basemap-Umschaltung: OSM <-> HERE SmartMaps (beide Layer existieren
	// immer, nur die Sichtbarkeit wechselt — kein map.setStyle(), das würde
	// alle dynamisch hinzugefügten Sourcen/Layer oben zerstören).
	$effect(() => {
		if (!ready) return;
		map.setLayoutProperty('osm', 'visibility', hereTilesEnabled ? 'none' : 'visible');
		map.setLayoutProperty('here-smartmaps', 'visibility', hereTilesEnabled ? 'visible' : 'none');
	});
```

- [ ] **Step 4: Frontend-Typecheck**

Run: `cd frontend && npm run check`
Expected: keine neuen Fehler in `MapView.svelte`

- [ ] **Step 5: Commit**

```bash
git add frontend/src/lib/components/MapView.svelte
git commit -m "feat: HERE-SmartMaps-Layer in MapView mit Sichtbarkeits-Toggle"
```

---

## Task 6: Toggle-Button auf der Plan-Seite

**Files:**
- Modify: `frontend/src/routes/o/[slug]/plan/+page.svelte:59` (State), `:1163-1167` (Button), `:1868-1877` (Prop-Weitergabe)

- [ ] **Step 1: State-Variable ergänzen**

In `frontend/src/routes/o/[slug]/plan/+page.svelte`, nach Zeile 59 (`let showClosures = $state(false);`) ergänzen:

```typescript
	let hereTilesEnabled = $state(false);
```

- [ ] **Step 2: Toggle-Button in die bestehende `.map-actions`-Gruppe einfügen**

Die bestehende Sidebar-Button-Gruppe (Zeile 1163-1167) um einen vierten Button erweitern:

```svelte
<div class="map-actions" data-tour="map-actions">
	<button class="btn-map" class:active={$mapMode === 'set-start'} onclick={() => mapMode.set($mapMode === 'set-start' ? 'idle' : 'set-start')}>📍 Start</button>
	<button class="btn-map" class:active={$mapMode === 'set-end'} onclick={() => mapMode.set($mapMode === 'set-end' ? 'idle' : 'set-end')}>🏁 Ziel</button>
	<button class="btn-map" class:active={$mapMode === 'add-waypoint'} onclick={() => mapMode.set($mapMode === 'add-waypoint' ? 'idle' : 'add-waypoint')}>➕ Wegpunkt</button>
	<button class="btn-map" class:active={hereTilesEnabled} onclick={() => hereTilesEnabled = !hereTilesEnabled} title="HERE SmartMaps statt OpenStreetMap anzeigen">🗺️ SmartMaps</button>
</div>
```

- [ ] **Step 3: Prop an `MapView` weiterreichen**

Den bestehenden `<MapView ... />`-Aufruf (Zeile 1868-1877) um die neue Prop erweitern:

```svelte
	<MapView
		startPoint={selected?.start_point}
		endPoint={selected?.end_point}
		waypoints={selected?.waypoints ?? []}
		routeGeojson={routeGeojson}
		closuresGeojson={showClosures ? closures : null}
		flowGeojson={showFlow ? flow : null}
		onMapClick={handleMapClick}
		onMapMove={handleMapMove}
		hereTilesEnabled={hereTilesEnabled}
	/>
```

- [ ] **Step 4: Frontend-Typecheck**

Run: `cd frontend && npm run check`
Expected: keine neuen Fehler in `plan/+page.svelte`

- [ ] **Step 5: Manuell im Browser prüfen**

Run: `cd frontend && npm run dev`, Plan-Seite einer Organisation öffnen, „🗺️ SmartMaps"-Button klicken.
Expected: Button wird aktiv (grün hervorgehoben wie „Start"/„Ziel"/„Wegpunkt" bei Aktivierung), Kartenkacheln werden über `/api/tiles/here/{z}/{x}/{y}` nachgeladen (Network-Tab prüfen). Ohne konfigurierten `HERE_API_KEY`/`HERE_TRAFFIC_API_KEY` liefert jede Kachel-Anfrage einen 302-Redirect auf `tile.openstreetmap.org` — die Karte bleibt sichtbar, es ändert sich optisch nichts (erwartetes Fallback-Verhalten, siehe Spec).

- [ ] **Step 6: Commit**

```bash
git add frontend/src/routes/o/[slug]/plan/+page.svelte
git commit -m "feat: SmartMaps-Toggle-Button auf der Plan-Seite"
```

---

## Nicht im Scope (siehe Design-Spec)

- Vector-Tile-API, Rollout auf `LeitstellenOverviewMap.svelte`/`LeitstelleAreaPicker.svelte`, Admin-UI für den Tile-Verbrauch, Redis/shared-Store für Multi-Replica-Betrieb.
