# Leitstellen-Verzeichnis & automatische Kanalwechsel Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a system-wide Leitstellen directory with polygon boundaries, and automatically compute radio channel switch points where a calculated route crosses Leitstellen boundaries.

**Architecture:** PostGIS-native intersection (ST_Intersects / ST_Intersection / ST_LineLocatePoint) computes exact crossing points when a route is calculated. Results are persisted as JSON on the Route record. The frontend shows them interleaved with waypoints and in the Marschbefehl section.

**Tech Stack:** Python/FastAPI, SQLAlchemy async, geoalchemy2, PostGIS, Shapely, fpdf2 (PDF), Svelte 5 runes, MapLibre GL

---

## File Map

**Create:**
- `backend/app/models/leitstelle.py` — Leitstelle ORM model
- `backend/alembic/versions/0009_leitstellen.py` — migration: leitstellen table
- `backend/alembic/versions/0010_route_kanalwechsel.py` — migration: routes.kanalwechsel column
- `backend/app/schemas/leitstelle.py` — Pydantic schemas
- `backend/app/api/routes/leitstellen.py` — CRUD router
- `backend/tests/test_leitstellen.py` — API tests
- `backend/tests/test_kanalwechsel.py` — computation tests

**Modify:**
- `backend/app/models/route.py` — add `kanalwechsel` JSON column
- `backend/app/schemas/route.py` — add `KanalwechselEntry`, extend `RouteResponse`
- `backend/app/api/routes/routing.py` — add `_compute_kanalwechsel`, wire into `calculate_route`, extend `get_route` + `export_pdf`
- `backend/app/main.py` — register leitstellen router
- `backend/app/services/pdf.py` — add Kanalwechsel section
- `frontend/src/lib/api/index.ts` — add types + `leistellenApi`
- `frontend/src/routes/admin/+page.svelte` — add Leitstellen tab
- `frontend/src/routes/plan/+page.svelte` — show Kanalwechsel in zeitplan tab + Marschbefehl modal

---

### Task 1: Leitstelle model + migrations

**Files:**
- Create: `backend/app/models/leitstelle.py`
- Create: `backend/alembic/versions/0009_leitstellen.py`
- Modify: `backend/app/models/route.py`
- Create: `backend/alembic/versions/0010_route_kanalwechsel.py`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_leitstellen.py
def test_leitstelle_model_importable():
    from app.models.leitstelle import Leitstelle
    ls = Leitstelle(name="ILS München", anrufgruppe="468")
    assert ls.name == "ILS München"
    assert ls.anrufgruppe == "468"
    assert ls.zusatz_kanaele is None
    assert ls.geometry is None
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd backend && python -m pytest tests/test_leitstellen.py::test_leitstelle_model_importable -v
```
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Create the Leitstelle model**

```python
# backend/app/models/leitstelle.py
import uuid
from datetime import datetime

from geoalchemy2 import Geometry
from sqlalchemy import DateTime, JSON, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class Leitstelle(Base):
    __tablename__ = "leitstellen"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(100))
    anrufgruppe: Mapped[str] = mapped_column(String(50))
    zusatz_kanaele: Mapped[list | None] = mapped_column(JSON, nullable=True)
    geometry = mapped_column(Geometry("GEOMETRY", srid=4326), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
```

- [ ] **Step 4: Add kanalwechsel column to Route model**

In `backend/app/models/route.py`, add one import and one field:

```python
# full file after change:
import uuid

from geoalchemy2 import Geometry
from sqlalchemy import ForeignKey, Integer, JSON, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class Route(Base):
    __tablename__ = "routes"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    convoy_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("convoys.id"), unique=True)
    geometry = mapped_column(Geometry("LINESTRING", srid=4326))
    distance_m: Mapped[int | None] = mapped_column(Integer)
    duration_s: Mapped[int | None] = mapped_column(Integer)
    routing_params: Mapped[dict | None] = mapped_column(JSON)
    gpx_data: Mapped[str | None] = mapped_column(Text)
    kanalwechsel: Mapped[list | None] = mapped_column(JSON, nullable=True)

    convoy: Mapped["Convoy"] = relationship(back_populates="route")
```

- [ ] **Step 5: Create migration 0009 — leitstellen table**

```python
# backend/alembic/versions/0009_leitstellen.py
"""add leitstellen table

Revision ID: 0009
Revises: 0008
Create Date: 2026-05-11
"""
from alembic import op
import sqlalchemy as sa
from geoalchemy2 import Geometry

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "leitstellen",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("anrufgruppe", sa.String(50), nullable=False),
        sa.Column("zusatz_kanaele", sa.JSON(), nullable=True),
        sa.Column("geometry", Geometry("GEOMETRY", srid=4326), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_table("leitstellen")
```

- [ ] **Step 6: Create migration 0010 — routes.kanalwechsel**

```python
# backend/alembic/versions/0010_route_kanalwechsel.py
"""add kanalwechsel column to routes

Revision ID: 0010
Revises: 0009
Create Date: 2026-05-11
"""
from alembic import op
import sqlalchemy as sa

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    inspector = sa.inspect(conn)
    existing = [col["name"] for col in inspector.get_columns("routes")]
    if "kanalwechsel" not in existing:
        op.add_column("routes", sa.Column("kanalwechsel", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("routes", "kanalwechsel")
```

- [ ] **Step 7: Run the test to verify it passes**

```bash
cd backend && python -m pytest tests/test_leitstellen.py::test_leitstelle_model_importable -v
```
Expected: PASS

- [ ] **Step 8: Commit**

```bash
git add backend/app/models/leitstelle.py backend/app/models/route.py \
        backend/alembic/versions/0009_leitstellen.py \
        backend/alembic/versions/0010_route_kanalwechsel.py
git commit -m "feat: Leitstelle model + kanalwechsel column on Route"
```

---

### Task 2: Leitstellen CRUD API

**Files:**
- Create: `backend/app/schemas/leitstelle.py`
- Create: `backend/app/api/routes/leitstellen.py`
- Modify: `backend/app/main.py`
- Modify: `backend/tests/test_leitstellen.py`

- [ ] **Step 1: Write failing tests**

```python
# append to backend/tests/test_leitstellen.py
import uuid
import json
from unittest.mock import AsyncMock, MagicMock, patch
import pytest


def _make_ls(**kw):
    ls = MagicMock()
    ls.id = uuid.uuid4()
    ls.name = kw.get("name", "ILS München")
    ls.anrufgruppe = kw.get("anrufgruppe", "468")
    ls.zusatz_kanaele = kw.get("zusatz_kanaele", [])
    ls.geometry = kw.get("geometry", None)
    ls.created_at = MagicMock()
    return ls


def _mock_db(ls_list=None):
    db = AsyncMock()
    result = MagicMock()
    result.scalars.return_value.all.return_value = ls_list or []
    result.scalar_one_or_none.return_value = ls_list[0] if ls_list else None
    db.execute = AsyncMock(return_value=result)
    db.add = MagicMock()
    db.commit = AsyncMock()
    db.refresh = AsyncMock()
    db.delete = AsyncMock()
    return db


@pytest.mark.asyncio
async def test_list_leitstellen_returns_list():
    from app.api.routes.leitstellen import list_leitstellen
    db = _mock_db([_make_ls()])
    user = MagicMock(is_active=True)
    result = await list_leitstellen(db=db, current_user=user)
    assert len(result) == 1
    assert result[0].name == "ILS München"


@pytest.mark.asyncio
async def test_create_leitstelle_requires_superadmin():
    from app.api.routes.leitstellen import create_leitstelle
    from app.schemas.leitstelle import LeistelleCreate
    from fastapi import HTTPException
    db = _mock_db()
    non_admin = MagicMock(is_superadmin=False)
    with pytest.raises(HTTPException) as exc:
        await create_leitstelle(
            data=LeistelleCreate(name="X", anrufgruppe="1"),
            db=db,
            current_user=non_admin,
        )
    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_create_leitstelle_succeeds_for_superadmin():
    from app.api.routes.leitstellen import create_leitstelle
    from app.schemas.leitstelle import LeistelleCreate

    created = _make_ls(name="ILS Test", anrufgruppe="469")
    db = _mock_db()
    db.refresh = AsyncMock(side_effect=lambda obj: None)

    admin = MagicMock(is_superadmin=True)
    with patch("app.api.routes.leitstellen.Leitstelle", return_value=created):
        result = await create_leitstelle(
            data=LeistelleCreate(name="ILS Test", anrufgruppe="469"),
            db=db,
            current_user=admin,
        )
    db.add.assert_called_once()
    db.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_delete_leitstelle_requires_superadmin():
    from app.api.routes.leitstellen import delete_leitstelle
    from fastapi import HTTPException
    db = _mock_db([_make_ls()])
    non_admin = MagicMock(is_superadmin=False)
    with pytest.raises(HTTPException) as exc:
        await delete_leitstelle(leitstelle_id=uuid.uuid4(), db=db, current_user=non_admin)
    assert exc.value.status_code == 403
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd backend && python -m pytest tests/test_leitstellen.py -v -k "not model_importable"
```
Expected: FAIL with `ModuleNotFoundError` or `ImportError`

- [ ] **Step 3: Create Pydantic schemas**

```python
# backend/app/schemas/leitstelle.py
import uuid
from pydantic import BaseModel


class ZusatzKanal(BaseModel):
    name: str
    kanal: str


class LeistelleCreate(BaseModel):
    name: str
    anrufgruppe: str
    zusatz_kanaele: list[ZusatzKanal] = []


class LeistelleUpdate(BaseModel):
    name: str | None = None
    anrufgruppe: str | None = None
    zusatz_kanaele: list[ZusatzKanal] | None = None


class LeistelleResponse(BaseModel):
    id: uuid.UUID
    name: str
    anrufgruppe: str
    zusatz_kanaele: list[ZusatzKanal]
    has_geometry: bool

    model_config = {"from_attributes": True}


class LeistelleDetailResponse(LeistelleResponse):
    geometry_geojson: dict | None = None
```

- [ ] **Step 4: Create the router**

```python
# backend/app/api/routes/leitstellen.py
import json
import uuid
import xml.etree.ElementTree as ET

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from geoalchemy2.shape import from_shape, to_shape
from shapely.geometry import shape, mapping
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, require_superadmin
from app.database import get_db
from app.models.leitstelle import Leitstelle
from app.models.user import User
from app.schemas.leitstelle import (
    LeistelleCreate, LeistelleUpdate,
    LeistelleResponse, LeistelleDetailResponse, ZusatzKanal,
)

router = APIRouter(prefix="/leitstellen", tags=["leitstellen"])


def _to_response(ls: Leitstelle) -> LeistelleResponse:
    kanaele = [ZusatzKanal(**k) for k in (ls.zusatz_kanaele or [])]
    return LeistelleResponse(
        id=ls.id,
        name=ls.name,
        anrufgruppe=ls.anrufgruppe,
        zusatz_kanaele=kanaele,
        has_geometry=ls.geometry is not None,
    )


def _to_detail_response(ls: Leitstelle) -> LeistelleDetailResponse:
    kanaele = [ZusatzKanal(**k) for k in (ls.zusatz_kanaele or [])]
    geojson = None
    if ls.geometry is not None:
        try:
            geojson = mapping(to_shape(ls.geometry))
        except Exception:
            geojson = None
    return LeistelleDetailResponse(
        id=ls.id,
        name=ls.name,
        anrufgruppe=ls.anrufgruppe,
        zusatz_kanaele=kanaele,
        has_geometry=ls.geometry is not None,
        geometry_geojson=geojson,
    )


@router.get("/", response_model=list[LeistelleResponse])
async def list_leitstellen(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(select(Leitstelle).order_by(Leitstelle.name))
    return [_to_response(ls) for ls in result.scalars().all()]


@router.get("/{leitstelle_id}", response_model=LeistelleDetailResponse)
async def get_leitstelle(
    leitstelle_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    result = await db.execute(select(Leitstelle).where(Leitstelle.id == leitstelle_id))
    ls = result.scalar_one_or_none()
    if not ls:
        raise HTTPException(404, "Leitstelle not found")
    return _to_detail_response(ls)


@router.post("/", response_model=LeistelleResponse, status_code=201)
async def create_leitstelle(
    data: LeistelleCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if not current_user.is_superadmin:
        raise HTTPException(403, "Superadmin required")
    ls = Leitstelle(
        name=data.name,
        anrufgruppe=data.anrufgruppe,
        zusatz_kanaele=[k.model_dump() for k in data.zusatz_kanaele],
    )
    db.add(ls)
    await db.commit()
    await db.refresh(ls)
    return _to_response(ls)


@router.put("/{leitstelle_id}", response_model=LeistelleResponse)
async def update_leitstelle(
    leitstelle_id: uuid.UUID,
    data: LeistelleUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if not current_user.is_superadmin:
        raise HTTPException(403, "Superadmin required")
    result = await db.execute(select(Leitstelle).where(Leitstelle.id == leitstelle_id))
    ls = result.scalar_one_or_none()
    if not ls:
        raise HTTPException(404, "Leitstelle not found")
    if data.name is not None:
        ls.name = data.name
    if data.anrufgruppe is not None:
        ls.anrufgruppe = data.anrufgruppe
    if data.zusatz_kanaele is not None:
        ls.zusatz_kanaele = [k.model_dump() for k in data.zusatz_kanaele]
    await db.commit()
    await db.refresh(ls)
    return _to_response(ls)


@router.delete("/{leitstelle_id}", status_code=204)
async def delete_leitstelle(
    leitstelle_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if not current_user.is_superadmin:
        raise HTTPException(403, "Superadmin required")
    result = await db.execute(select(Leitstelle).where(Leitstelle.id == leitstelle_id))
    ls = result.scalar_one_or_none()
    if not ls:
        raise HTTPException(404, "Leitstelle not found")
    await db.delete(ls)
    await db.commit()


@router.post("/{leitstelle_id}/boundary", response_model=LeistelleResponse)
async def import_boundary(
    leitstelle_id: uuid.UUID,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if not current_user.is_superadmin:
        raise HTTPException(403, "Superadmin required")
    result = await db.execute(select(Leitstelle).where(Leitstelle.id == leitstelle_id))
    ls = result.scalar_one_or_none()
    if not ls:
        raise HTTPException(404, "Leitstelle not found")

    content = await file.read()
    filename = (file.filename or "").lower()

    if filename.endswith(".kml"):
        poly = _parse_kml(content)
    else:
        poly = _parse_geojson(content)

    if poly is None:
        raise HTTPException(400, "No valid Polygon/MultiPolygon found in file")

    ls.geometry = from_shape(poly, srid=4326)
    await db.commit()
    await db.refresh(ls)
    return _to_response(ls)


def _parse_geojson(content: bytes):
    try:
        data = json.loads(content)
    except Exception:
        return None
    # Unwrap FeatureCollection → Feature → Geometry
    if data.get("type") == "FeatureCollection":
        features = data.get("features", [])
        if not features:
            return None
        data = features[0]
    if data.get("type") == "Feature":
        data = data.get("geometry", {})
    if data.get("type") not in ("Polygon", "MultiPolygon"):
        return None
    try:
        return shape(data)
    except Exception:
        return None


def _parse_kml(content: bytes):
    try:
        root = ET.fromstring(content)
    except Exception:
        return None
    # Try both KML 2.2 and Google Earth 2.0 namespaces
    for ns_uri in ("http://www.opengis.net/kml/2.2", "http://earth.google.com/kml/2.0"):
        ns = {"k": ns_uri}
        coords_el = root.find(".//k:coordinates", ns)
        if coords_el is not None and coords_el.text:
            pts = []
            for token in coords_el.text.strip().split():
                parts = token.split(",")
                if len(parts) >= 2:
                    try:
                        pts.append((float(parts[0]), float(parts[1])))
                    except ValueError:
                        continue
            if len(pts) >= 3:
                from shapely.geometry import Polygon
                return Polygon(pts)
    return None
```

- [ ] **Step 5: Register the router in main.py**

In `backend/app/main.py`, add after the other imports:

```python
from app.api.routes import (
    auth, convoys, vehicles, routing, organizations,
    tracking, lage, weather, overpass, status, users,
    leitstellen,
)
```

And after the existing `app.include_router` calls:

```python
app.include_router(leitstellen.router, prefix="/api")
```

- [ ] **Step 6: Run tests to verify they pass**

```bash
cd backend && python -m pytest tests/test_leitstellen.py -v
```
Expected: All 5 tests PASS

- [ ] **Step 7: Commit**

```bash
git add backend/app/schemas/leitstelle.py \
        backend/app/api/routes/leitstellen.py \
        backend/app/main.py \
        backend/tests/test_leitstellen.py
git commit -m "feat: Leitstellen CRUD API with GeoJSON/KML boundary import"
```

---

### Task 3: Kanalwechsel computation

**Files:**
- Modify: `backend/app/schemas/route.py`
- Modify: `backend/app/api/routes/routing.py`
- Create: `backend/tests/test_kanalwechsel.py`

- [ ] **Step 1: Write failing tests**

```python
# backend/tests/test_kanalwechsel.py
import uuid
import pytest


def test_kanalwechsel_entry_schema():
    from app.schemas.route import KanalwechselEntry
    entry = KanalwechselEntry(
        km=34.2, lat=47.856, lon=12.103,
        leitstelle_id=str(uuid.uuid4()),
        leitstelle_name="ILS Rosenheim",
        anrufgruppe="438",
    )
    assert entry.km == 34.2
    assert entry.leitstelle_name == "ILS Rosenheim"


def test_route_response_includes_kanalwechsel():
    from app.schemas.route import RouteResponse, KanalwechselEntry
    r = RouteResponse(
        id=uuid.uuid4(),
        convoy_id=uuid.uuid4(),
        distance_m=50000,
        duration_s=3600,
        routing_params=None,
        geojson=None,
        kanalwechsel=[
            KanalwechselEntry(
                km=25.0, lat=48.0, lon=11.0,
                leitstelle_id=str(uuid.uuid4()),
                leitstelle_name="ILS München",
                anrufgruppe="468",
            )
        ],
    )
    assert len(r.kanalwechsel) == 1
    assert r.kanalwechsel[0].anrufgruppe == "468"


def test_kanalwechsel_sorted_by_km():
    entries = [
        {"km": 67.8, "lat": 47.9, "lon": 12.5, "leitstelle_id": "a", "leitstelle_name": "ILS B", "anrufgruppe": "452"},
        {"km": 34.2, "lat": 47.8, "lon": 12.1, "leitstelle_id": "b", "leitstelle_name": "ILS A", "anrufgruppe": "438"},
    ]
    entries.sort(key=lambda x: x["km"])
    assert entries[0]["km"] == 34.2
    assert entries[1]["km"] == 67.8
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd backend && python -m pytest tests/test_kanalwechsel.py -v
```
Expected: `test_kanalwechsel_entry_schema` and `test_route_response_includes_kanalwechsel` FAIL with `ImportError`

- [ ] **Step 3: Add KanalwechselEntry to route schema**

Replace `backend/app/schemas/route.py` entirely:

```python
import uuid
from typing import Any

from pydantic import BaseModel


class FuelStopPosition(BaseModel):
    lat: float
    lon: float


class VehicleRangeInfo(BaseModel):
    name: str
    callsign: str | None
    range_km: float
    using_defaults: bool = False


class DurationHalt(BaseModel):
    stop_km: float
    stop_position: FuelStopPosition | None
    duration_min: int
    is_rest: bool = False


class FuelAnalysis(BaseModel):
    vehicles_with_range: list[VehicleRangeInfo]
    min_range_km: float | None
    route_distance_km: float
    fuel_stop_needed: bool
    fuel_stop_km: float | None
    fuel_stop_position: FuelStopPosition | None
    limiting_vehicle: str | None
    has_default_values: bool = False
    vehicles_without_data: int = 0
    recommended_stop_duration_min: int | None = None
    duration_halt_needed: bool = False
    duration_halts: list[DurationHalt] = []
    rest_needed: bool = False


class KanalwechselEntry(BaseModel):
    km: float
    lat: float
    lon: float
    leitstelle_id: str
    leitstelle_name: str
    anrufgruppe: str


class RouteResponse(BaseModel):
    id: uuid.UUID
    convoy_id: uuid.UUID
    distance_m: int | None
    duration_s: int | None
    routing_params: dict[str, Any] | None
    geojson: dict | None = None
    fuel_analysis: FuelAnalysis | None = None
    kanalwechsel: list[KanalwechselEntry] = []

    model_config = {"from_attributes": True}
```

- [ ] **Step 4: Run schema tests to verify they pass**

```bash
cd backend && python -m pytest tests/test_kanalwechsel.py -v
```
Expected: All 3 tests PASS

- [ ] **Step 5: Add `_compute_kanalwechsel` helper to routing.py**

At the top of `backend/app/api/routes/routing.py`, add to the imports block (after existing imports):

```python
import json as _json
```

Then add this function before `@router.get("/{convoy_id}/route", ...)`:

```python
async def _compute_kanalwechsel(
    db: AsyncSession,
    route_wkb,
    distance_m: int,
) -> list[dict]:
    from app.models.leitstelle import Leitstelle

    rows = await db.execute(
        select(
            Leitstelle.id,
            Leitstelle.name,
            Leitstelle.anrufgruppe,
            func.ST_AsGeoJSON(
                func.ST_Intersection(route_wkb, func.ST_Boundary(Leitstelle.geometry))
            ).label("crossing_geojson"),
        )
        .where(
            Leitstelle.geometry.isnot(None),
            func.ST_Intersects(route_wkb, Leitstelle.geometry),
        )
    )

    entries: list[dict] = []
    for row in rows.all():
        if not row.crossing_geojson:
            continue
        crossing = _json.loads(row.crossing_geojson)
        if crossing["type"] == "Point":
            pts: list[list[float]] = [crossing["coordinates"]]
        elif crossing["type"] == "MultiPoint":
            pts = crossing["coordinates"]
        else:
            continue

        for lon, lat in pts:
            frac_res = await db.execute(
                select(
                    func.ST_LineLocatePoint(
                        route_wkb,
                        func.ST_SetSRID(func.ST_MakePoint(lon, lat), 4326),
                    )
                )
            )
            frac = frac_res.scalar() or 0.0
            entries.append({
                "km": round((distance_m / 1000) * frac, 1),
                "lat": round(lat, 6),
                "lon": round(lon, 6),
                "leitstelle_id": str(row.id),
                "leitstelle_name": row.name,
                "anrufgruppe": row.anrufgruppe,
            })

    entries.sort(key=lambda x: x["km"])
    return entries
```

- [ ] **Step 6: Wire `_compute_kanalwechsel` into `calculate_route`**

In `calculate_route`, find the block that ends with `await db.commit()` after waypoint resorting (around line 220). After that block and before the fuel analysis, add:

```python
    # Compute Kanalwechsel (radio channel switch points)
    route_wkb = from_shape(line, srid=4326)
    kanalwechsel = await _compute_kanalwechsel(db, route_wkb, route_data["distance_m"])
    route.kanalwechsel = kanalwechsel
    await db.commit()
```

Then update the `return` dict at the end of `calculate_route` to include:

```python
    return {
        "id": route.id,
        "convoy_id": route.convoy_id,
        "distance_m": route.distance_m,
        "duration_s": route.duration_s,
        "routing_params": route.routing_params,
        "geojson": route_data["geometry"],
        "fuel_analysis": fuel_analysis,
        "kanalwechsel": kanalwechsel,
    }
```

- [ ] **Step 7: Update `get_route` to include kanalwechsel**

In the `get_route` handler, update the `RouteResponse(...)` call:

```python
    return RouteResponse(
        id=route.id,
        convoy_id=convoy_id,
        distance_m=route.distance_m,
        duration_s=route.duration_s,
        routing_params=route.routing_params,
        geojson=geojson,
        kanalwechsel=route.kanalwechsel or [],
    )
```

- [ ] **Step 8: Run all tests**

```bash
cd backend && python -m pytest tests/ -v
```
Expected: All tests PASS (45+ tests)

- [ ] **Step 9: Commit**

```bash
git add backend/app/schemas/route.py \
        backend/app/api/routes/routing.py \
        backend/tests/test_kanalwechsel.py
git commit -m "feat: compute and persist Kanalwechsel on route calculation"
```

---

### Task 4: Admin UI – Leitstellen tab

**Files:**
- Modify: `frontend/src/lib/api/index.ts`
- Modify: `frontend/src/routes/admin/+page.svelte`

- [ ] **Step 1: Add Leitstellen types and API to index.ts**

In `frontend/src/lib/api/index.ts`, add these types after the existing interfaces (e.g. after `OrgMember`):

```typescript
export interface ZusatzKanal {
    name: string;
    kanal: string;
}

export interface Leitstelle {
    id: string;
    name: string;
    anrufgruppe: string;
    zusatz_kanaele: ZusatzKanal[];
    has_geometry: boolean;
}

export interface LeistelleDetail extends Leitstelle {
    geometry_geojson: object | null;
}
```

Then add the `leistellenApi` object before the closing `export { ... }` or at the end of the api exports section:

```typescript
export const leistellenApi = {
    list: () => api.get<Leitstelle[]>('/api/leitstellen'),
    get: (id: string) => api.get<LeistelleDetail>(`/api/leitstellen/${id}`),
    create: (data: { name: string; anrufgruppe: string; zusatz_kanaele: ZusatzKanal[] }) =>
        api.post<Leitstelle>('/api/leitstellen', data),
    update: (id: string, data: { name?: string; anrufgruppe?: string; zusatz_kanaele?: ZusatzKanal[] }) =>
        api.put<Leitstelle>(`/api/leitstellen/${id}`, data),
    delete: (id: string) => api.delete(`/api/leitstellen/${id}`),
    importBoundary: (id: string, file: File) =>
        uploadFile<Leitstelle>(`/api/leitstellen/${id}/boundary`, file),
};
```

- [ ] **Step 2: Verify TypeScript compiles**

```bash
cd frontend && npx tsc --noEmit 2>&1 | head -20
```
Expected: No errors for the new types

- [ ] **Step 3: Rewrite admin page with Leitstellen tab**

Replace `frontend/src/routes/admin/+page.svelte` entirely:

```svelte
<script lang="ts">
    import { onMount } from 'svelte';
    import { goto } from '$app/navigation';
    import maplibregl from 'maplibre-gl';
    import 'maplibre-gl/dist/maplibre-gl.css';
    import { auth } from '$lib/stores/auth';
    import { adminApi, leistellenApi, type AdminUser, type Leitstelle, type LeistelleDetail, type ZusatzKanal } from '$lib/api';

    // ── Tab ──────────────────────────────────────────────────────────────────
    let activeTab = $state<'benutzer' | 'leitstellen'>('benutzer');

    // ── Users ────────────────────────────────────────────────────────────────
    let users = $state<AdminUser[]>([]);
    let loading = $state(true);
    let error = $state('');
    let showCreateForm = $state(false);
    let newUser = $state({ email: '', password: '', is_superadmin: false });

    onMount(async () => {
        if (!$auth.is_superadmin) { goto('/plan'); return; }
        await loadUsers();
        await loadLeitstellen();
    });

    async function loadUsers() {
        try {
            loading = true;
            users = await adminApi.listUsers();
        } catch { error = 'Benutzer konnten nicht geladen werden'; }
        finally { loading = false; }
    }

    async function createUser() {
        try {
            await adminApi.createUser(newUser);
            newUser = { email: '', password: '', is_superadmin: false };
            showCreateForm = false;
            await loadUsers();
        } catch (e: unknown) {
            error = e instanceof Error ? e.message : 'Fehler beim Erstellen';
        }
    }

    async function toggleActive(user: AdminUser) {
        try {
            await adminApi.updateUser(user.id, { is_active: !user.is_active });
            await loadUsers();
        } catch { error = 'Konnte Status nicht ändern'; }
    }

    async function toggleSuperadmin(user: AdminUser) {
        try {
            await adminApi.updateUser(user.id, { is_superadmin: !user.is_superadmin });
            await loadUsers();
        } catch { error = 'Konnte Rolle nicht ändern'; }
    }

    async function deleteUser(user: AdminUser) {
        if (!confirm(`${user.email} wirklich löschen?`)) return;
        try {
            await adminApi.deleteUser(user.id);
            await loadUsers();
        } catch { error = 'Benutzer konnte nicht gelöscht werden'; }
    }

    // ── Leitstellen ──────────────────────────────────────────────────────────
    let leitstellen = $state<Leitstelle[]>([]);
    let lsError = $state('');
    let showLsModal = $state(false);
    let editingLs = $state<LeistelleDetail | null>(null);
    let lsForm = $state({ name: '', anrufgruppe: '', zusatz_kanaele: [] as ZusatzKanal[] });

    // Polygon drawing state
    let polyMapContainer: HTMLDivElement | undefined;
    let polyMap: maplibregl.Map | undefined;
    let polygonCoords = $state<[number, number][]>([]);
    let drawingMode = $state(false);

    async function loadLeitstellen() {
        try {
            leitstellen = await leistellenApi.list();
        } catch { lsError = 'Leitstellen konnten nicht geladen werden'; }
    }

    function openCreateLs() {
        editingLs = null;
        lsForm = { name: '', anrufgruppe: '', zusatz_kanaele: [] };
        polygonCoords = [];
        drawingMode = false;
        showLsModal = true;
        initPolyMap();
    }

    async function openEditLs(ls: Leitstelle) {
        try {
            editingLs = await leistellenApi.get(ls.id);
            lsForm = {
                name: editingLs.name,
                anrufgruppe: editingLs.anrufgruppe,
                zusatz_kanaele: [...editingLs.zusatz_kanaele],
            };
            const geo = editingLs.geometry_geojson as { type: string; coordinates: unknown } | null;
            polygonCoords = [];
            drawingMode = false;
            showLsModal = true;
            initPolyMap(geo);
        } catch { lsError = 'Leitstelle konnte nicht geladen werden'; }
    }

    function initPolyMap(existingGeo?: object | null) {
        // Defer until DOM renders the modal
        setTimeout(() => {
            if (!polyMapContainer) return;
            if (polyMap) { polyMap.remove(); polyMap = undefined; }

            polyMap = new maplibregl.Map({
                container: polyMapContainer,
                style: {
                    version: 8,
                    sources: { osm: { type: 'raster', tiles: ['https://tile.openstreetmap.org/{z}/{x}/{y}.png'], tileSize: 256, attribution: '© OpenStreetMap' } },
                    layers: [{ id: 'osm', type: 'raster', source: 'osm' }],
                },
                center: [10.5, 48.5],
                zoom: 6,
            });

            polyMap.on('load', () => {
                polyMap!.addSource('draft', { type: 'geojson', data: { type: 'FeatureCollection', features: [] } });
                polyMap!.addLayer({ id: 'draft-fill', type: 'fill', source: 'draft', paint: { 'fill-color': '#e74c3c', 'fill-opacity': 0.2 } });
                polyMap!.addLayer({ id: 'draft-line', type: 'line', source: 'draft', paint: { 'line-color': '#e74c3c', 'line-width': 2 } });

                if (existingGeo) {
                    updatePolySource(existingGeo as GeoJSON.Geometry);
                    if ((existingGeo as { coordinates?: unknown[] }).coordinates) {
                        // Fly to existing polygon
                        const coords = (existingGeo as { coordinates: [number, number][][] }).coordinates?.[0] ?? [];
                        if (coords.length) {
                            const lons = coords.map(c => c[0]);
                            const lats = coords.map(c => c[1]);
                            polyMap!.fitBounds([
                                [Math.min(...lons), Math.min(...lats)],
                                [Math.max(...lons), Math.max(...lats)],
                            ], { padding: 40 });
                        }
                    }
                }

                polyMap!.on('click', (e) => {
                    if (!drawingMode) return;
                    polygonCoords = [...polygonCoords, [e.lngLat.lng, e.lngLat.lat]];
                    updatePolySource();
                });

                polyMap!.on('dblclick', (e) => {
                    if (!drawingMode || polygonCoords.length < 3) return;
                    e.preventDefault();
                    drawingMode = false;
                    updatePolySource();
                });
            });
        }, 100);
    }

    function updatePolySource(existingGeo?: GeoJSON.Geometry) {
        if (!polyMap) return;
        const src = polyMap.getSource('draft') as maplibregl.GeoJSONSource | undefined;
        if (!src) return;

        if (existingGeo) {
            src.setData({ type: 'Feature', geometry: existingGeo, properties: {} } as GeoJSON.Feature);
            return;
        }
        if (polygonCoords.length < 2) {
            src.setData({ type: 'FeatureCollection', features: [] });
            return;
        }
        if (drawingMode) {
            src.setData({ type: 'Feature', geometry: { type: 'LineString', coordinates: polygonCoords }, properties: {} } as GeoJSON.Feature);
        } else {
            const closed: [number, number][] = [...polygonCoords, polygonCoords[0]];
            src.setData({ type: 'Feature', geometry: { type: 'Polygon', coordinates: [closed] }, properties: {} } as GeoJSON.Feature);
        }
    }

    function resetPolygon() {
        polygonCoords = [];
        drawingMode = false;
        const src = polyMap?.getSource('draft') as maplibregl.GeoJSONSource | undefined;
        src?.setData({ type: 'FeatureCollection', features: [] });
    }

    function addZusatzKanal() {
        lsForm.zusatz_kanaele = [...lsForm.zusatz_kanaele, { name: '', kanal: '' }];
    }

    function removeZusatzKanal(idx: number) {
        lsForm.zusatz_kanaele = lsForm.zusatz_kanaele.filter((_, i) => i !== idx);
    }

    async function saveLs() {
        if (!lsForm.name || !lsForm.anrufgruppe) return;
        try {
            let saved: Leitstelle;
            if (editingLs) {
                saved = await leistellenApi.update(editingLs.id, lsForm);
            } else {
                saved = await leistellenApi.create(lsForm);
            }
            // Upload polygon if drawn
            if (!drawingMode && polygonCoords.length >= 3) {
                const closed: [number, number][] = [...polygonCoords, polygonCoords[0]];
                const geo = { type: 'Feature', geometry: { type: 'Polygon', coordinates: [closed] }, properties: {} };
                const blob = new Blob([JSON.stringify(geo)], { type: 'application/json' });
                const file = new File([blob], 'polygon.geojson', { type: 'application/json' });
                await leistellenApi.importBoundary(saved.id, file);
            }
            showLsModal = false;
            polyMap?.remove(); polyMap = undefined;
            await loadLeitstellen();
        } catch (e: unknown) {
            lsError = e instanceof Error ? e.message : 'Fehler beim Speichern';
        }
    }

    async function handleBoundaryFile(lsId: string, e: Event) {
        const input = e.target as HTMLInputElement;
        const file = input.files?.[0];
        if (!file) return;
        try {
            await leistellenApi.importBoundary(lsId, file);
            await loadLeitstellen();
        } catch { lsError = 'Import fehlgeschlagen'; }
    }

    async function deleteLs(ls: Leitstelle) {
        if (!confirm(`${ls.name} wirklich löschen?`)) return;
        try {
            await leistellenApi.delete(ls.id);
            await loadLeitstellen();
        } catch { lsError = 'Leitstelle konnte nicht gelöscht werden'; }
    }
</script>

<div class="admin-page">
    <div class="admin-header">
        <h1>Admin</h1>
        <a href="/plan" class="back-link">← Plan</a>
    </div>

    <div class="tab-bar">
        <button class="tab" class:active={activeTab === 'benutzer'} onclick={() => (activeTab = 'benutzer')}>Benutzer</button>
        <button class="tab" class:active={activeTab === 'leitstellen'} onclick={() => (activeTab = 'leitstellen')}>Leitstellen</button>
    </div>

    <!-- ── Benutzer ── -->
    {#if activeTab === 'benutzer'}
        {#if error}
            <div class="error-bar">{error} <button onclick={() => (error = '')}>✕</button></div>
        {/if}

        <div class="section">
            <div class="section-header">
                <strong>Benutzer ({users.length})</strong>
                <button class="btn-small" onclick={() => (showCreateForm = !showCreateForm)}>+ Neu</button>
            </div>

            {#if showCreateForm}
                <form class="create-form" onsubmit={(e) => { e.preventDefault(); createUser(); }}>
                    <input placeholder="E-Mail *" type="email" bind:value={newUser.email} required />
                    <input placeholder="Passwort *" type="password" bind:value={newUser.password} required />
                    <label class="checkbox-label">
                        <input type="checkbox" bind:checked={newUser.is_superadmin} />
                        Superadmin
                    </label>
                    <div class="form-actions">
                        <button type="submit" class="btn-primary">Erstellen</button>
                        <button type="button" onclick={() => (showCreateForm = false)}>Abbrechen</button>
                    </div>
                </form>
            {/if}

            {#if loading}
                <p>Lädt…</p>
            {:else}
                <table class="user-table">
                    <thead><tr><th>E-Mail</th><th>Aktiv</th><th>Admin</th><th>Aktionen</th></tr></thead>
                    <tbody>
                        {#each users as user}
                            <tr>
                                <td>{user.email}</td>
                                <td><button class="toggle" class:on={user.is_active} onclick={() => toggleActive(user)}>{user.is_active ? 'Ja' : 'Nein'}</button></td>
                                <td><button class="toggle" class:on={user.is_superadmin} onclick={() => toggleSuperadmin(user)}>{user.is_superadmin ? 'Ja' : 'Nein'}</button></td>
                                <td><button class="btn-small danger" onclick={() => deleteUser(user)}>Löschen</button></td>
                            </tr>
                        {/each}
                    </tbody>
                </table>
            {/if}
        </div>
    {/if}

    <!-- ── Leitstellen ── -->
    {#if activeTab === 'leitstellen'}
        {#if lsError}
            <div class="error-bar">{lsError} <button onclick={() => (lsError = '')}>✕</button></div>
        {/if}

        <div class="section">
            <div class="section-header">
                <strong>Leitstellen ({leitstellen.length})</strong>
                {#if $auth.is_superadmin}
                    <button class="btn-small" onclick={openCreateLs}>+ Neu</button>
                {/if}
            </div>

            <table class="user-table">
                <thead>
                    <tr>
                        <th>Name</th>
                        <th>Anrufgruppe</th>
                        <th>Zusatzkanäle</th>
                        <th>Grenzen</th>
                        {#if $auth.is_superadmin}<th>Aktionen</th>{/if}
                    </tr>
                </thead>
                <tbody>
                    {#each leitstellen as ls}
                        <tr>
                            <td>{ls.name}</td>
                            <td><code>{ls.anrufgruppe}</code></td>
                            <td>{ls.zusatz_kanaele.length > 0 ? ls.zusatz_kanaele.length : '–'}</td>
                            <td>{ls.has_geometry ? '✓' : '✗'}</td>
                            {#if $auth.is_superadmin}
                                <td class="actions-cell">
                                    <button class="btn-small" onclick={() => openEditLs(ls)}>✎</button>
                                    <button class="btn-small danger" onclick={() => deleteLs(ls)}>✕</button>
                                </td>
                            {/if}
                        </tr>
                    {/each}
                    {#if leitstellen.length === 0}
                        <tr><td colspan="5" class="empty-hint">Noch keine Leitstellen erfasst.</td></tr>
                    {/if}
                </tbody>
            </table>
        </div>
    {/if}
</div>

<!-- ── Leitstelle Modal ── -->
{#if showLsModal}
    <div class="modal-backdrop" onclick={() => { showLsModal = false; polyMap?.remove(); polyMap = undefined; }}>
        <div class="modal" onclick={(e) => e.stopPropagation()}>
            <div class="modal-header">
                <h2>{editingLs ? 'Leitstelle bearbeiten' : 'Neue Leitstelle'}</h2>
                <button onclick={() => { showLsModal = false; polyMap?.remove(); polyMap = undefined; }}>✕</button>
            </div>

            <div class="modal-body">
                <div class="ls-form">
                    <label>Name *
                        <input bind:value={lsForm.name} placeholder="z.B. ILS München" required />
                    </label>
                    <label>Anrufgruppe *
                        <input bind:value={lsForm.anrufgruppe} placeholder="z.B. 468" required />
                    </label>

                    <div class="zusatz-section">
                        <div class="zusatz-header">
                            <strong>Zusatzkanäle</strong>
                            <button class="btn-small" onclick={addZusatzKanal}>+ Hinzufügen</button>
                        </div>
                        {#each lsForm.zusatz_kanaele as kanal, idx}
                            <div class="zusatz-row">
                                <input bind:value={kanal.name} placeholder="Bezeichnung" />
                                <input bind:value={kanal.kanal} placeholder="Kanal" />
                                <button class="btn-small danger" onclick={() => removeZusatzKanal(idx)}>✕</button>
                            </div>
                        {/each}
                    </div>

                    <div class="map-section">
                        <strong>Zuständigkeitsgebiet</strong>
                        <div class="poly-controls">
                            <button
                                class="btn-small"
                                class:active={drawingMode}
                                onclick={() => { drawingMode = !drawingMode; }}
                            >
                                {drawingMode ? '✓ Zeichnen aktiv (Doppelklick = fertig)' : '✏ Polygon zeichnen'}
                            </button>
                            <button class="btn-small" onclick={resetPolygon}>↺ Zurücksetzen</button>
                        </div>
                        <div class="poly-map" bind:this={polyMapContainer}></div>
                        <div class="import-row">
                            <label class="btn-small file-label">
                                📂 GeoJSON/KML importieren
                                <input
                                    type="file"
                                    accept=".geojson,.json,.kml"
                                    style="display:none"
                                    onchange={async (e) => {
                                        const input = e.target as HTMLInputElement;
                                        const file = input.files?.[0];
                                        if (!file || !editingLs) return;
                                        await leistellenApi.importBoundary(editingLs.id, file);
                                        await loadLeitstellen();
                                    }}
                                />
                            </label>
                            <span class="hint">Import nur bei bestehenden Einträgen verfügbar</span>
                        </div>
                    </div>
                </div>
            </div>

            <div class="modal-footer">
                <button onclick={() => { showLsModal = false; polyMap?.remove(); polyMap = undefined; }}>Abbrechen</button>
                <button class="btn-primary" onclick={saveLs} disabled={!lsForm.name || !lsForm.anrufgruppe}>Speichern</button>
            </div>
        </div>
    </div>
{/if}

<style>
    :global(body) { margin: 0; font-family: system-ui, sans-serif; background: #f5f3ee; }
    .admin-page { max-width: 900px; margin: 0 auto; padding: 1.5rem; }
    .admin-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 1rem; }
    .admin-header h1 { margin: 0; font-size: 1.4rem; }
    .back-link { font-size: .85rem; color: #3498db; text-decoration: none; }

    .tab-bar { display: flex; gap: 0; border-bottom: 2px solid #ddd; margin-bottom: 1.5rem; }
    .tab { padding: .5rem 1.2rem; background: none; border: none; cursor: pointer; font-size: .9rem; color: #666; border-bottom: 2px solid transparent; margin-bottom: -2px; }
    .tab.active { color: #E23D28; border-bottom-color: #E23D28; font-weight: 600; }

    .error-bar { background: #C23020; color: white; padding: .5rem 1rem; border-radius: 4px; margin-bottom: 1rem; display: flex; justify-content: space-between; }
    .error-bar button { background: none; border: none; color: white; cursor: pointer; }
    .section { background: white; border-radius: 8px; padding: 1rem; box-shadow: 0 1px 4px rgba(0,0,0,.08); margin-bottom: 1rem; }
    .section-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: .75rem; }
    .user-table { width: 100%; border-collapse: collapse; font-size: .85rem; }
    .user-table th, .user-table td { padding: .4rem .6rem; border-bottom: 1px solid #eee; text-align: left; }
    .user-table th { background: #f5f3ee; font-weight: 600; }
    .actions-cell { display: flex; gap: .3rem; }
    .empty-hint { color: #999; font-style: italic; text-align: center; padding: 1rem; }
    .toggle { padding: .2rem .5rem; border-radius: 3px; font-size: .75rem; cursor: pointer; border: 1px solid #ccc; background: #eee; }
    .toggle.on { background: #27ae60; color: white; border-color: #27ae60; }
    code { background: #f0f0f0; padding: .1rem .3rem; border-radius: 3px; font-size: .82rem; }
    .btn-small { padding: .25rem .6rem; font-size: .78rem; border: 1px solid #ccc; border-radius: 3px; background: white; cursor: pointer; }
    .btn-small:hover { background: #f0f0f0; }
    .btn-small.danger { border-color: #e74c3c; color: #e74c3c; }
    .btn-small.active { background: #e74c3c; color: white; border-color: #e74c3c; }
    .btn-primary { padding: .45rem 1rem; background: #E23D28; color: white; border: none; border-radius: 4px; font-weight: 600; cursor: pointer; }
    .btn-primary:disabled { opacity: .5; cursor: not-allowed; }
    .create-form { background: #f9f9f9; border: 1px solid #ddd; border-radius: 6px; padding: .75rem; margin-bottom: .75rem; display: flex; flex-direction: column; gap: .4rem; }
    .create-form input { padding: .35rem .5rem; border: 1px solid #ccc; border-radius: 4px; font-size: .85rem; }
    .checkbox-label { display: flex; align-items: center; gap: .4rem; font-size: .85rem; }
    .form-actions { display: flex; gap: .5rem; margin-top: .25rem; }

    /* Modal */
    .modal-backdrop { position: fixed; inset: 0; background: rgba(0,0,0,.5); display: flex; align-items: center; justify-content: center; z-index: 100; }
    .modal { background: white; border-radius: 8px; width: 600px; max-width: 95vw; max-height: 90vh; display: flex; flex-direction: column; }
    .modal-header { display: flex; justify-content: space-between; align-items: center; padding: 1rem; border-bottom: 1px solid #eee; }
    .modal-header h2 { margin: 0; font-size: 1.1rem; }
    .modal-header button { background: none; border: none; font-size: 1.1rem; cursor: pointer; }
    .modal-body { padding: 1rem; overflow-y: auto; flex: 1; }
    .modal-footer { padding: .75rem 1rem; border-top: 1px solid #eee; display: flex; justify-content: flex-end; gap: .5rem; }
    .ls-form { display: flex; flex-direction: column; gap: .75rem; }
    .ls-form label { display: flex; flex-direction: column; gap: .3rem; font-size: .85rem; font-weight: 600; }
    .ls-form input { padding: .35rem .5rem; border: 1px solid #ccc; border-radius: 4px; font-size: .88rem; font-weight: 400; }
    .zusatz-section { display: flex; flex-direction: column; gap: .4rem; }
    .zusatz-header { display: flex; justify-content: space-between; align-items: center; font-size: .85rem; font-weight: 600; }
    .zusatz-row { display: flex; gap: .4rem; align-items: center; }
    .zusatz-row input { flex: 1; padding: .3rem .4rem; border: 1px solid #ccc; border-radius: 3px; font-size: .82rem; }
    .map-section { display: flex; flex-direction: column; gap: .4rem; font-size: .85rem; font-weight: 600; }
    .poly-controls { display: flex; gap: .4rem; font-weight: 400; }
    .poly-map { height: 280px; border-radius: 6px; overflow: hidden; border: 1px solid #ccc; }
    .import-row { display: flex; gap: .5rem; align-items: center; font-weight: 400; }
    .file-label { cursor: pointer; }
    .hint { font-size: .75rem; color: #888; font-style: italic; }
</style>
```

- [ ] **Step 4: Verify app loads without errors**

```bash
cd frontend && npm run build 2>&1 | tail -10
```
Expected: Build succeeds, no TypeScript errors

- [ ] **Step 5: Commit**

```bash
git add frontend/src/lib/api/index.ts frontend/src/routes/admin/+page.svelte
git commit -m "feat: Leitstellen admin tab with polygon drawing and import"
```

---

### Task 5: Plan page display + PDF export

**Files:**
- Modify: `frontend/src/routes/plan/+page.svelte`
- Modify: `backend/app/services/pdf.py`
- Modify: `backend/app/api/routes/routing.py` (export_pdf section only)

- [ ] **Step 1: Update route state type and calculateRoute in plan page**

In `frontend/src/routes/plan/+page.svelte`, find the `route` state declaration (line 27):

```typescript
let route = $state<{ geojson: unknown; distance_m: number | null; duration_s: number | null; fuel_analysis: FuelAnalysis | null } | null>(null);
```

Replace with:

```typescript
import type { KanalwechselEntry } from '$lib/api';
// ...
let route = $state<{ geojson: unknown; distance_m: number | null; duration_s: number | null; fuel_analysis: FuelAnalysis | null; kanalwechsel: KanalwechselEntry[] } | null>(null);
```

In `calculateRoute()`, find the line (around line 390):

```typescript
route = { geojson: r.geojson, distance_m: r.distance_m, duration_s: r.duration_s, fuel_analysis: r.fuel_analysis };
```

Replace with:

```typescript
route = { geojson: r.geojson, distance_m: r.distance_m, duration_s: r.duration_s, fuel_analysis: r.fuel_analysis, kanalwechsel: r.kanalwechsel ?? [] };
```

- [ ] **Step 2: Add Kanalwechsel section to the `zeitplan` tab**

In the plan page template, find the `zeitplan` tab block (starts with `{#if activeTab === 'zeitplan'`). After the closing `{/if}` for the schedule table hint, add before the closing `</div>` of that tab:

```svelte
{#if route?.kanalwechsel?.length}
    <div class="kw-section">
        <strong>Kanalwechsel</strong>
        <table class="schedule-table kw-table">
            <thead><tr><th>km</th><th>Leitstelle</th><th>Anrufgruppe</th></tr></thead>
            <tbody>
                {#each route.kanalwechsel as kw}
                    <tr>
                        <td>{kw.km.toFixed(1)}</td>
                        <td class="kw-name">
                            <span class="kw-tooltip-wrap">
                                📡 {kw.leitstelle_name}
                            </span>
                        </td>
                        <td><code>{kw.anrufgruppe}</code></td>
                    </tr>
                {/each}
            </tbody>
        </table>
    </div>
{/if}
```

- [ ] **Step 3: Add Kanalwechsel section to Marschbefehl modal**

In the Marschbefehl modal (starting around line 1310), find a good place after the `Funkgruppe` field. After the existing `<div class="modal-field">` block for funkgruppe (or wherever the route info is shown), add:

```svelte
{#if route?.kanalwechsel?.length}
    <div class="modal-field">
        <label>Kanalwechsel</label>
        <table class="kw-befehl-table">
            <thead><tr><th>km</th><th>Leitstelle</th><th>Anrufgruppe</th></tr></thead>
            <tbody>
                {#each route.kanalwechsel as kw}
                    <tr>
                        <td>{kw.km.toFixed(1)}</td>
                        <td>📡 {kw.leitstelle_name}</td>
                        <td><code>{kw.anrufgruppe}</code></td>
                    </tr>
                {/each}
            </tbody>
        </table>
    </div>
{/if}
```

- [ ] **Step 4: Add CSS for Kanalwechsel tables**

In the `<style>` section of `plan/+page.svelte`, add:

```css
.kw-section { margin-top: .75rem; }
.kw-table td code { background: #f0f4f8; padding: .1rem .3rem; border-radius: 3px; font-size: .8rem; }
.kw-befehl-table { width: 100%; border-collapse: collapse; font-size: .82rem; margin-top: .3rem; }
.kw-befehl-table th, .kw-befehl-table td { padding: .3rem .5rem; border: 1px solid #ddd; text-align: left; }
.kw-befehl-table th { background: #f5f3ee; }
```

- [ ] **Step 5: Add Kanalwechsel section to PDF**

In `backend/app/services/pdf.py`, update the `generate_marschbefehl` signature to accept `kanalwechsel`:

```python
def generate_marschbefehl(
    convoy: Any,
    waypoints: list[dict],
    vehicles: list[dict],
    route: Any | None,
    kanalwechsel: list[dict] | None = None,
) -> bytes:
```

Then in the function, after section 5 ("Führung und Verbindung"), add a new subsection before section 6 ("Anlagen"):

```python
    # Kanalwechsel subsection (only if data present)
    if kanalwechsel:
        _subsection(pdf, "Kanalwechsel")
        cols_kw = [(25, "km"), (0, "Leitstelle"), (40, "Anrufgruppe")]
        used_kw = cols_kw[0][0] + cols_kw[2][0]
        cols_kw[1] = (total_w - used_kw, "Leitstelle")
        _table_header(pdf, cols_kw)
        pdf.set_font("DV", "", 8)
        fill = False
        for kw in kanalwechsel:
            pdf.set_fill_color(245, 246, 250) if fill else pdf.set_fill_color(255, 255, 255)
            pdf.cell(cols_kw[0][0], 6, f"{kw.get('km', 0):.1f} km", border=1, fill=fill)
            pdf.cell(cols_kw[1][0], 6, str(kw.get("leitstelle_name", ""))[:35], border=1, fill=fill)
            pdf.cell(cols_kw[2][0], 6, str(kw.get("anrufgruppe", "")), border=1, fill=fill, new_x="LMARGIN", new_y="NEXT")
            fill = not fill
        pdf.ln(3)
```

Note: `total_w` is already defined earlier in `generate_marschbefehl` as `pdf.w - pdf.l_margin - pdf.r_margin`. Place the Kanalwechsel block after the fuel analysis / `_section(pdf, "5", ...)` block.

- [ ] **Step 6: Pass kanalwechsel to PDF in export_pdf endpoint**

In `backend/app/api/routes/routing.py`, find the `export_pdf` handler. After fetching `route`, extract kanalwechsel and pass it:

```python
    kanalwechsel = route.kanalwechsel if route else None
    pdf_bytes = pdf_svc.generate_marschbefehl(convoy, waypoints, vehicles, route, kanalwechsel)
```

- [ ] **Step 7: Run backend tests**

```bash
cd backend && python -m pytest tests/ -v
```
Expected: All tests PASS

- [ ] **Step 8: Run frontend build**

```bash
cd frontend && npm run build 2>&1 | tail -10
```
Expected: Build succeeds

- [ ] **Step 9: Commit**

```bash
git add frontend/src/routes/plan/+page.svelte \
        backend/app/services/pdf.py \
        backend/app/api/routes/routing.py
git commit -m "feat: show Kanalwechsel in zeitplan tab, Marschbefehl modal, and PDF"
```
