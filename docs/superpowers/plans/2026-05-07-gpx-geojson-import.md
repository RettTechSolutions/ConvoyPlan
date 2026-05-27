# GPX/GeoJSON Import Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `POST /api/convoys/{id}/import/gpx` and `POST /api/convoys/{id}/import/geojson` endpoints that populate a convoy's waypoints and/or route from uploaded files.

**Architecture:** New `services/importer.py` handles parsing (pure functions, easy to test). A shared `_apply_import` helper in `routing.py` handles DB writes. Two thin endpoint functions delegate to both. Frontend adds an upload section to the existing Export tab.

**Tech Stack:** FastAPI UploadFile, gpxpy (already installed), stdlib json, SQLAlchemy async, shapely/geoalchemy2, Svelte 5.

---

## File Map

| File | Change |
|---|---|
| `backend/app/services/importer.py` | **Create** — `parse_gpx`, `parse_geojson`, `ImportResult` |
| `backend/tests/test_import.py` | **Create** — unit tests for parser + `_apply_import` |
| `backend/app/api/routes/routing.py` | **Modify** — add `_apply_import`, `import_gpx`, `import_geojson` |
| `frontend/src/lib/api/client.ts` | **Modify** — export `uploadFile` helper |
| `frontend/src/lib/api/index.ts` | **Modify** — add `importFile` to `convoysApi` |
| `frontend/src/routes/plan/+page.svelte` | **Modify** — import UI in Export tab |

---

## Task 1: `importer.py` service + unit tests (TDD)

**Files:**
- Create: `backend/app/services/importer.py`
- Create: `backend/tests/test_import.py`

### Step 1: Write the failing tests

Create `backend/tests/test_import.py`:

```python
import json
import uuid
import pytest
from unittest.mock import AsyncMock, MagicMock


# ── importer service tests (pure functions, no DB) ──────────────────────────

def test_parse_gpx_waypoints_and_track():
    from app.services.importer import parse_gpx
    content = b"""<?xml version="1.0"?>
<gpx version="1.1" xmlns="http://www.topografix.com/GPX/1/1">
  <wpt lat="48.1" lon="11.5"><name>Start</name><desc>Startpunkt</desc></wpt>
  <wpt lat="48.2" lon="11.6"><name>Ziel</name></wpt>
  <trk><trkseg>
    <trkpt lat="48.1" lon="11.5"/>
    <trkpt lat="48.15" lon="11.55"/>
    <trkpt lat="48.2" lon="11.6"/>
  </trkseg></trk>
</gpx>"""
    result = parse_gpx(content)
    assert len(result.waypoints) == 2
    assert result.waypoints[0] == {"name": "Start", "lat": 48.1, "lon": 11.5, "notes": "Startpunkt"}
    assert result.waypoints[1] == {"name": "Ziel", "lat": 48.2, "lon": 11.6, "notes": None}
    assert result.route_coords == [(11.5, 48.1), (11.55, 48.15), (11.6, 48.2)]


def test_parse_gpx_waypoints_only():
    from app.services.importer import parse_gpx
    content = b"""<?xml version="1.0"?>
<gpx version="1.1" xmlns="http://www.topografix.com/GPX/1/1">
  <wpt lat="48.1" lon="11.5"><name>A</name></wpt>
</gpx>"""
    result = parse_gpx(content)
    assert len(result.waypoints) == 1
    assert result.route_coords is None


def test_parse_gpx_track_only():
    from app.services.importer import parse_gpx
    content = b"""<?xml version="1.0"?>
<gpx version="1.1" xmlns="http://www.topografix.com/GPX/1/1">
  <trk><trkseg>
    <trkpt lat="48.1" lon="11.5"/>
    <trkpt lat="48.2" lon="11.6"/>
  </trkseg></trk>
</gpx>"""
    result = parse_gpx(content)
    assert result.waypoints == []
    assert len(result.route_coords) == 2


def test_parse_gpx_fallback_name():
    from app.services.importer import parse_gpx
    content = b"""<?xml version="1.0"?>
<gpx version="1.1" xmlns="http://www.topografix.com/GPX/1/1">
  <wpt lat="48.1" lon="11.5"></wpt>
</gpx>"""
    result = parse_gpx(content)
    assert result.waypoints[0]["name"] == "Waypoint 1"


def test_parse_gpx_invalid_raises():
    from app.services.importer import parse_gpx
    with pytest.raises(ValueError, match="Invalid GPX"):
        parse_gpx(b"not xml at all")


def test_parse_gpx_empty_raises():
    from app.services.importer import parse_gpx
    content = b"""<?xml version="1.0"?>
<gpx version="1.1" xmlns="http://www.topografix.com/GPX/1/1"></gpx>"""
    with pytest.raises(ValueError, match="No importable data"):
        parse_gpx(content)


def test_parse_geojson_feature_collection():
    from app.services.importer import parse_geojson
    data = {
        "type": "FeatureCollection",
        "features": [
            {"type": "Feature", "geometry": {"type": "Point", "coordinates": [11.5, 48.1]},
             "properties": {"name": "Alpha", "description": "Desc"}},
            {"type": "Feature", "geometry": {"type": "Point", "coordinates": [11.6, 48.2]},
             "properties": {"name": "Beta"}},
            {"type": "Feature", "geometry": {"type": "LineString",
             "coordinates": [[11.5, 48.1], [11.6, 48.2]]}, "properties": {}},
        ],
    }
    result = parse_geojson(json.dumps(data).encode())
    assert len(result.waypoints) == 2
    assert result.waypoints[0] == {"name": "Alpha", "lat": 48.1, "lon": 11.5, "notes": "Desc"}
    assert result.waypoints[1]["notes"] is None
    assert result.route_coords == [(11.5, 48.1), (11.6, 48.2)]


def test_parse_geojson_points_only():
    from app.services.importer import parse_geojson
    data = {"type": "FeatureCollection", "features": [
        {"type": "Feature", "geometry": {"type": "Point", "coordinates": [11.5, 48.1]},
         "properties": {"name": "X"}},
    ]}
    result = parse_geojson(json.dumps(data).encode())
    assert len(result.waypoints) == 1
    assert result.route_coords is None


def test_parse_geojson_fallback_name():
    from app.services.importer import parse_geojson
    data = {"type": "FeatureCollection", "features": [
        {"type": "Feature", "geometry": {"type": "Point", "coordinates": [11.5, 48.1]},
         "properties": {}},
    ]}
    result = parse_geojson(json.dumps(data).encode())
    assert result.waypoints[0]["name"] == "Waypoint 1"


def test_parse_geojson_invalid_raises():
    from app.services.importer import parse_geojson
    with pytest.raises(ValueError, match="Invalid GeoJSON"):
        parse_geojson(b"not json {{{")


def test_parse_geojson_empty_raises():
    from app.services.importer import parse_geojson
    data = {"type": "FeatureCollection", "features": []}
    with pytest.raises(ValueError, match="No importable data"):
        parse_geojson(json.dumps(data).encode())
```

### Step 2: Run tests — expect ImportError

```bash
cd /Users/working_chris/GitHub/MarschPlan/backend
python3 -m pytest tests/test_import.py -v 2>&1 | head -20
```

Expected: `ModuleNotFoundError: No module named 'app.services.importer'`

### Step 3: Create `backend/app/services/importer.py`

```python
import json
from dataclasses import dataclass, field

import gpxpy
import gpxpy.gpx


@dataclass
class ImportResult:
    waypoints: list[dict]
    route_coords: list[tuple[float, float]] | None  # (lon, lat) order for PostGIS


def parse_gpx(content: bytes) -> ImportResult:
    try:
        gpx = gpxpy.parse(content.decode("utf-8"))
    except Exception:
        raise ValueError("Invalid GPX file")

    waypoints = []
    for i, wpt in enumerate(gpx.waypoints):
        waypoints.append({
            "name": wpt.name or f"Waypoint {i + 1}",
            "lat": wpt.latitude,
            "lon": wpt.longitude,
            "notes": wpt.description or None,
        })

    route_coords = None
    for track in gpx.tracks:
        for segment in track.segments:
            if segment.points:
                route_coords = [(p.longitude, p.latitude) for p in segment.points]
                break
        if route_coords is not None:
            break

    if not waypoints and route_coords is None:
        raise ValueError("No importable data found")

    return ImportResult(waypoints=waypoints, route_coords=route_coords)


def parse_geojson(content: bytes) -> ImportResult:
    try:
        data = json.loads(content)
    except Exception:
        raise ValueError("Invalid GeoJSON file")

    if data.get("type") == "FeatureCollection":
        features = data.get("features", [])
    elif data.get("type") == "Feature":
        features = [data]
    else:
        raise ValueError("Invalid GeoJSON file")

    waypoints: list[dict] = []
    route_coords: list[tuple[float, float]] | None = None
    wp_count = 0

    for feature in features:
        geom = feature.get("geometry") or {}
        props = feature.get("properties") or {}

        if geom.get("type") == "Point":
            lon, lat = geom["coordinates"][0], geom["coordinates"][1]
            wp_count += 1
            waypoints.append({
                "name": props.get("name") or f"Waypoint {wp_count}",
                "lat": lat,
                "lon": lon,
                "notes": props.get("description") or props.get("notes") or None,
            })
        elif geom.get("type") == "LineString" and route_coords is None:
            route_coords = [(c[0], c[1]) for c in geom["coordinates"]]

    if not waypoints and route_coords is None:
        raise ValueError("No importable data found")

    return ImportResult(waypoints=waypoints, route_coords=route_coords)
```

### Step 4: Run tests — expect all pass

```bash
cd /Users/working_chris/GitHub/MarschPlan/backend
python3 -m pytest tests/test_import.py -v 2>&1 | tail -20
```

Expected: 11 tests PASS

### Step 5: Commit

```bash
git add backend/app/services/importer.py backend/tests/test_import.py
git commit -m "feat: add GPX/GeoJSON import parser service"
```

---

## Task 2: Import endpoints in `routing.py`

**Files:**
- Modify: `backend/app/api/routes/routing.py`
- Modify: `backend/tests/test_import.py` (add endpoint-logic tests)

**Context:** `routing.py` already imports `select`, `delete` (check — if not, add it), `from_shape`, `LineString`, `geo_svc`, `Route`, `Waypoint`. You will need to add `UploadFile`, `File`, `Query`, `func` from sqlalchemy, `Literal` from typing, and the importer service.

### Step 1: Read `routing.py` imports and locate insertion points

```bash
head -30 /Users/working_chris/GitHub/MarschPlan/backend/app/api/routes/routing.py
```

Note which imports already exist. You'll add to them.

### Step 2: Add import tests (append to `test_import.py`)

Append these tests to `backend/tests/test_import.py`:

```python
# ── _apply_import helper tests (mock DB) ────────────────────────────────────

def _mock_db(*scalar_values):
    """Mock db where each execute() call returns a result whose scalar_one_or_none() returns the given value."""
    db = AsyncMock()
    mocks = []
    for val in scalar_values:
        mr = MagicMock()
        mr.scalar_one_or_none.return_value = val
        mocks.append(mr)
    db.execute.side_effect = mocks
    return db


@pytest.mark.asyncio
async def test_apply_import_replace_deletes_existing():
    from app.api.routes.routing import _apply_import
    from app.services.importer import ImportResult

    convoy_id = uuid.uuid4()
    result = ImportResult(
        waypoints=[{"name": "A", "lat": 48.1, "lon": 11.5, "notes": None}],
        route_coords=None,
    )
    db = _mock_db(None)  # one execute call (delete), result not used

    response = await _apply_import(convoy_id, result, "replace", db)

    assert response == {"waypoints_imported": 1, "route_stored": False}
    assert db.execute.call_count == 1  # only the delete statement
    assert db.add.call_count == 1
    db.commit.assert_called_once()


@pytest.mark.asyncio
async def test_apply_import_add_mode_appends_order_index():
    from app.api.routes.routing import _apply_import
    from app.services.importer import ImportResult

    convoy_id = uuid.uuid4()
    result = ImportResult(
        waypoints=[
            {"name": "A", "lat": 48.1, "lon": 11.5, "notes": None},
            {"name": "B", "lat": 48.2, "lon": 11.6, "notes": None},
        ],
        route_coords=None,
    )
    # add mode: max existing order_index is 2 → new ones start at 3
    db = _mock_db(2)

    response = await _apply_import(convoy_id, result, "add", db)

    assert response == {"waypoints_imported": 2, "route_stored": False}
    added = [call.args[0] for call in db.add.call_args_list]
    assert added[0].order_index == 3
    assert added[1].order_index == 4


@pytest.mark.asyncio
async def test_apply_import_add_mode_no_existing_starts_at_zero():
    from app.api.routes.routing import _apply_import
    from app.services.importer import ImportResult

    convoy_id = uuid.uuid4()
    result = ImportResult(
        waypoints=[{"name": "A", "lat": 48.1, "lon": 11.5, "notes": None}],
        route_coords=None,
    )
    # add mode: no existing waypoints → scalar_one_or_none returns None
    db = _mock_db(None)

    await _apply_import(convoy_id, result, "add", db)

    added = db.add.call_args_list[0].args[0]
    assert added.order_index == 0


@pytest.mark.asyncio
async def test_apply_import_stores_route_when_no_existing():
    from app.api.routes.routing import _apply_import
    from app.services.importer import ImportResult
    from app.models.route import Route

    convoy_id = uuid.uuid4()
    result = ImportResult(
        waypoints=[],
        route_coords=[(11.5, 48.1), (11.6, 48.2)],
    )
    # replace mode: delete call (result ignored), route select returns None
    db = _mock_db(None, None)

    response = await _apply_import(convoy_id, result, "replace", db)

    assert response == {"waypoints_imported": 0, "route_stored": True}
    assert db.add.call_count == 1
    added = db.add.call_args_list[0].args[0]
    assert isinstance(added, Route)
    assert added.distance_m is None
    assert added.duration_s is None


@pytest.mark.asyncio
async def test_apply_import_updates_existing_route():
    from app.api.routes.routing import _apply_import
    from app.services.importer import ImportResult
    from app.models.route import Route

    convoy_id = uuid.uuid4()
    result = ImportResult(
        waypoints=[],
        route_coords=[(11.5, 48.1), (11.6, 48.2)],
    )
    existing_route = MagicMock(spec=Route)
    # replace mode: delete call, route select returns existing route
    db = _mock_db(None, existing_route)

    response = await _apply_import(convoy_id, result, "replace", db)

    assert response["route_stored"] is True
    assert db.add.call_count == 0  # updated in-place, not added again
    assert existing_route.distance_m is None
    assert existing_route.duration_s is None
```

### Step 3: Run new tests — expect failures

```bash
cd /Users/working_chris/GitHub/MarschPlan/backend
python3 -m pytest tests/test_import.py::test_apply_import_replace_deletes_existing -v 2>&1 | tail -5
```

Expected: `ImportError: cannot import name '_apply_import'`

### Step 4: Add imports and `_apply_import` to `routing.py`

**4a.** Update the sqlalchemy import line — add `delete` and `func` if not present:
```python
from sqlalchemy import select, delete, func
```

**4b.** Add to the FastAPI import line — add `File`, `Query`, `UploadFile`:
```python
from fastapi import APIRouter, Depends, HTTPException, File, Query, UploadFile
```

**4c.** Add to the top of the imports block:
```python
from typing import Literal
from app.api.guards import get_convoy_access
from app.services import importer as importer_svc
```

**4d.** Add `_apply_import` as a module-level async function, placed just before the first `@router` decorator:

```python
async def _apply_import(
    convoy_id: uuid.UUID,
    result: importer_svc.ImportResult,
    mode: str,
    db: AsyncSession,
) -> dict:
    if mode == "replace":
        await db.execute(delete(Waypoint).where(Waypoint.convoy_id == convoy_id))
        start_index = 0
    else:
        max_res = await db.execute(
            select(func.max(Waypoint.order_index)).where(Waypoint.convoy_id == convoy_id)
        )
        max_val = max_res.scalar_one_or_none()
        start_index = (max_val + 1) if max_val is not None else 0

    for i, wp in enumerate(result.waypoints):
        db.add(Waypoint(
            convoy_id=convoy_id,
            name=wp["name"],
            type="waypoint",
            location=geo_svc.point_to_wkt(wp["lat"], wp["lon"]),
            notes=wp["notes"],
            order_index=start_index + i,
        ))

    route_stored = False
    if result.route_coords:
        line = LineString(result.route_coords)
        existing = await db.execute(select(Route).where(Route.convoy_id == convoy_id))
        route = existing.scalar_one_or_none()
        if route:
            route.geometry = from_shape(line, srid=4326)
            route.distance_m = None
            route.duration_s = None
        else:
            db.add(Route(
                convoy_id=convoy_id,
                geometry=from_shape(line, srid=4326),
                distance_m=None,
                duration_s=None,
            ))
        route_stored = True

    await db.commit()
    return {"waypoints_imported": len(result.waypoints), "route_stored": route_stored}
```

### Step 5: Add the two import endpoints to `routing.py`

Add both endpoints after the existing export endpoints (`export_pdf` and before `find_fuel_stations`):

```python
@router.post("/{convoy_id}/import/gpx")
async def import_gpx(
    convoy_id: uuid.UUID,
    mode: Literal["add", "replace"] = Query(...),
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    await get_convoy_access(convoy_id, current_user, db, require="write")
    content = await file.read()
    try:
        result = importer_svc.parse_gpx(content)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return await _apply_import(convoy_id, result, mode, db)


@router.post("/{convoy_id}/import/geojson")
async def import_geojson(
    convoy_id: uuid.UUID,
    mode: Literal["add", "replace"] = Query(...),
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    await get_convoy_access(convoy_id, current_user, db, require="write")
    content = await file.read()
    try:
        result = importer_svc.parse_geojson(content)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return await _apply_import(convoy_id, result, mode, db)
```

### Step 6: Run all tests

```bash
cd /Users/working_chris/GitHub/MarschPlan/backend
python3 -m pytest tests/ -v --tb=short 2>&1 | tail -25
```

Expected: all 33 tests PASS (28 existing + 5 new `_apply_import` tests + the 11 importer tests = 33 total). If counts differ, verify the run passes fully.

### Step 7: Commit

```bash
git add backend/app/api/routes/routing.py backend/tests/test_import.py
git commit -m "feat: add GPX/GeoJSON import endpoints to routing"
```

---

## Task 3: Frontend import UI

**Files:**
- Modify: `frontend/src/lib/api/client.ts`
- Modify: `frontend/src/lib/api/index.ts`
- Modify: `frontend/src/routes/plan/+page.svelte`

### Step 1: Add `uploadFile` to `client.ts`

Open `frontend/src/lib/api/client.ts`. Read the current `getBaseUrl` and `getToken` functions (they're already there). Add this function at the end of the file:

```typescript
export async function uploadFile<T>(path: string, file: File): Promise<T> {
    const token = getToken();
    const headers: Record<string, string> = {};
    if (token) headers['Authorization'] = `Bearer ${token}`;
    // Do NOT set Content-Type — browser sets multipart/form-data + boundary automatically
    const formData = new FormData();
    formData.append('file', file);
    const res = await fetch(`${getBaseUrl()}${path}`, {
        method: 'POST',
        headers,
        body: formData,
    });
    if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: res.statusText }));
        throw new Error(err.detail ?? 'Request failed');
    }
    return res.json() as T;
}
```

### Step 2: Add `importFile` to `convoysApi` in `index.ts`

Open `frontend/src/lib/api/index.ts`. Find the `convoysApi` object.

**2a.** Add `uploadFile` to the import from `./client`:
```typescript
import { api, uploadFile } from './client';
```

**2b.** Add one line to `convoysApi` (after `exportUrl`):
```typescript
importFile: (id: string, format: 'gpx' | 'geojson', file: File, mode: 'add' | 'replace') =>
    uploadFile<{ waypoints_imported: number; route_stored: boolean }>(
        `/api/convoys/${id}/import/${format}?mode=${mode}`,
        file
    ),
```

### Step 3: Add import state to plan page

Open `frontend/src/routes/plan/+page.svelte`. Find the block where other state variables are declared (around lines 44–51). Add these lines there:

```typescript
let importFile = $state<File | null>(null);
let importMode = $state<'add' | 'replace'>('replace');
let importResult = $state<{ waypoints_imported: number; route_stored: boolean } | null>(null);
let importError = $state('');
let importing = $state(false);
```

### Step 4: Add `doImport` function to plan page

Find `async function addTHStopWaypoint` (around line 449). Add the following function just before it:

```typescript
async function doImport() {
    if (!importFile || !selected) return;
    const ext = importFile.name.split('.').pop()?.toLowerCase();
    const format = ext === 'gpx' ? 'gpx' : 'geojson';
    importing = true;
    importResult = null;
    importError = '';
    try {
        importResult = await convoysApi.importFile(selected.id, format, importFile, importMode);
        await refreshConvoy();
    } catch (e: unknown) {
        importError = e instanceof Error ? e.message : 'Import fehlgeschlagen';
    } finally {
        importing = false;
        importFile = null;
    }
}
```

### Step 5: Add import UI to the Export tab

Find the Export tab block in the template. It starts with `{#if activeTab === 'export' && selected}` (around line 990). Inside that block, after the closing `</div>` of the `export-grid` div (after the Sperrungen button block, before `{/if}`), add:

```svelte
<div class="section-header" style="margin-top:1rem"><strong>Import</strong></div>
<div style="display:flex;flex-direction:column;gap:.5rem">
    <input
        type="file"
        accept=".gpx,.geojson,.json"
        onchange={(e) => { importFile = (e.target as HTMLInputElement).files?.[0] ?? null; importResult = null; importError = ''; }}
        style="font-size:.8rem"
    />
    <div style="display:flex;gap:1rem;font-size:.85rem">
        <label style="display:flex;gap:.3rem;align-items:center;cursor:pointer">
            <input type="radio" bind:group={importMode} value="replace" /> Ersetzen
        </label>
        <label style="display:flex;gap:.3rem;align-items:center;cursor:pointer">
            <input type="radio" bind:group={importMode} value="add" /> Hinzufügen
        </label>
    </div>
    <button
        class="btn-export"
        onclick={doImport}
        disabled={!importFile || importing}
    >
        {importing ? 'Importiere…' : '⬆ Importieren'}
    </button>
    {#if importResult}
        <p style="font-size:.8rem;color:#4caf50;margin:0">
            {importResult.waypoints_imported} Wegpunkt{importResult.waypoints_imported !== 1 ? 'e' : ''} importiert
            {importResult.route_stored ? '· Route gespeichert' : ''}
        </p>
    {/if}
    {#if importError}
        <p style="font-size:.8rem;color:#f44336;margin:0">{importError}</p>
    {/if}
</div>
```

### Step 6: Type-check the frontend

```bash
cd /Users/working_chris/GitHub/MarschPlan/frontend
npm run check 2>&1 | tail -20
```

Expected: 0 errors. If there are type errors, fix them before committing.

### Step 7: Run backend tests one more time

```bash
cd /Users/working_chris/GitHub/MarschPlan/backend
python3 -m pytest tests/ -v --tb=short 2>&1 | tail -10
```

Expected: all tests pass.

### Step 8: Commit

```bash
git add frontend/src/lib/api/client.ts frontend/src/lib/api/index.ts frontend/src/routes/plan/+page.svelte
git commit -m "feat: add GPX/GeoJSON import UI to plan export tab"
```
