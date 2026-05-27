# Branding & CI-Anpassung Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Allow superadmins to customize app name, logos, and color scheme system-wide, with "Powered by ConvoyPlan" preserved.

**Architecture:** Backend stores branding in the existing `system_settings` key/value table under `branding.*` keys; a public `GET /api/branding` endpoint serves the values; a new Svelte writable store loads them on app start and applies them as CSS custom properties to `:root`. The setup wizard gains a skippable step 3, and the admin panel gains a Branding tab.

**Tech Stack:** FastAPI, SQLAlchemy async, Alembic, Pydantic v2, Svelte 5 (runes), CSS custom properties

---

## File Map

**Create:**
- `backend/app/schemas/branding.py` — Pydantic response + update schemas
- `backend/app/api/routes/branding.py` — GET/PUT branding + logo upload
- `backend/alembic/versions/0011_branding_defaults.py` — seed default values
- `backend/tests/test_branding.py` — backend unit tests
- `frontend/src/lib/stores/branding.ts` — writable store + applyBranding()

**Modify:**
- `backend/app/main.py` — register branding router + mount /uploads StaticFiles
- `docker-compose.yml` — add `logo_uploads` named volume at `/uploads`
- `frontend/src/lib/api/index.ts` — BrandingData interface + brandingApi
- `frontend/src/lib/components/AppLogo.svelte` — read URLs from branding store
- `frontend/src/routes/+layout.svelte` — fetch+apply branding on mount, dynamic title, "Powered by" footer
- `frontend/src/app.html` — add `:root` CSS var defaults
- `frontend/src/routes/plan/+page.svelte` — CSS: replace hardcoded brand colors
- `frontend/src/routes/admin/+page.svelte` — CSS migration + new Branding tab
- `frontend/src/lib/components/InfoPill.svelte` — CSS migration
- `frontend/src/routes/tracking/[convoy_id]/+page.svelte` — CSS migration
- `frontend/src/routes/setup/+page.svelte` — add step 3 (branding), completion → step 4

---

## Task 1: Backend – Schema, Route, Migration, Registration

**Files:**
- Create: `backend/app/schemas/branding.py`
- Create: `backend/app/api/routes/branding.py`
- Create: `backend/alembic/versions/0011_branding_defaults.py`
- Create: `backend/tests/test_branding.py`
- Modify: `backend/app/main.py`
- Modify: `docker-compose.yml`

- [ ] **Step 1: Write failing tests**

Create `backend/tests/test_branding.py`:

```python
from unittest.mock import AsyncMock, MagicMock
import pytest


def _mock_db(settings=None):
    db = AsyncMock()
    result = MagicMock()
    result.scalars.return_value.all.return_value = settings or []
    result.scalar_one_or_none.return_value = settings[0] if settings else None
    db.execute = AsyncMock(return_value=result)
    db.add = MagicMock()
    db.commit = AsyncMock()
    return db


@pytest.mark.asyncio
async def test_get_branding_returns_defaults_when_empty():
    from app.api.routes.branding import get_branding
    db = _mock_db([])
    response = await get_branding(db=db)
    assert response.app_name == "ConvoyPlan"
    assert response.color_primary == "#E23D28"
    assert response.logo_main_url is None
    assert response.logo_horizontal_url is None


@pytest.mark.asyncio
async def test_get_branding_returns_stored_app_name():
    from app.api.routes.branding import get_branding
    setting = MagicMock()
    setting.key = "branding.app_name"
    setting.value = "Feuerwehr München"
    db = _mock_db([setting])
    response = await get_branding(db=db)
    assert response.app_name == "Feuerwehr München"


@pytest.mark.asyncio
async def test_update_branding_requires_superadmin():
    from app.api.routes.branding import update_branding
    from app.schemas.branding import BrandingUpdate
    from fastapi import HTTPException
    db = _mock_db()
    non_admin = MagicMock(is_superadmin=False)
    with pytest.raises(HTTPException) as exc:
        await update_branding(
            data=BrandingUpdate(
                app_name="Test",
                color_primary="#E23D28",
                color_primary_hover="#C23020",
                color_accent="#3498db",
                color_bg="#f5f3ee",
                color_surface="#ffffff",
                color_nav_bg="#2c3e50",
                color_nav_text="#ecf0f1",
                color_text="#2c3e50",
                color_text_muted="#7f8c8d",
            ),
            db=db,
            current_user=non_admin,
        )
    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_upload_logo_requires_superadmin():
    from app.api.routes.branding import upload_logo
    from fastapi import HTTPException
    db = _mock_db()
    non_admin = MagicMock(is_superadmin=False)
    mock_file = MagicMock()
    mock_file.filename = "logo.png"
    mock_file.read = AsyncMock(return_value=b"data")
    with pytest.raises(HTTPException) as exc:
        await upload_logo(slot="main", file=mock_file, db=db, current_user=non_admin)
    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_upload_logo_rejects_oversized():
    from app.api.routes.branding import upload_logo
    from fastapi import HTTPException
    db = _mock_db()
    admin = MagicMock(is_superadmin=True)
    mock_file = MagicMock()
    mock_file.filename = "logo.png"
    mock_file.read = AsyncMock(return_value=b"x" * (2 * 1024 * 1024 + 1))
    with pytest.raises(HTTPException) as exc:
        await upload_logo(slot="main", file=mock_file, db=db, current_user=admin)
    assert exc.value.status_code == 400
    assert "too large" in exc.value.detail.lower()


@pytest.mark.asyncio
async def test_upload_logo_rejects_bad_extension():
    from app.api.routes.branding import upload_logo
    from fastapi import HTTPException
    db = _mock_db()
    admin = MagicMock(is_superadmin=True)
    mock_file = MagicMock()
    mock_file.filename = "malware.exe"
    mock_file.read = AsyncMock(return_value=b"x")
    with pytest.raises(HTTPException) as exc:
        await upload_logo(slot="main", file=mock_file, db=db, current_user=admin)
    assert exc.value.status_code == 400
    assert "Invalid file type" in exc.value.detail
```

- [ ] **Step 2: Run tests, confirm they all fail with ImportError**

```bash
cd backend && python -m pytest tests/test_branding.py -v 2>&1 | head -40
```

Expected: all 6 tests fail with `ModuleNotFoundError` or `ImportError` (branding module doesn't exist yet).

- [ ] **Step 3: Create branding schemas**

Create `backend/app/schemas/branding.py`:

```python
from pydantic import BaseModel, Field


class BrandingResponse(BaseModel):
    app_name: str
    logo_main_url: str | None
    logo_horizontal_url: str | None
    color_primary: str
    color_primary_hover: str
    color_accent: str
    color_bg: str
    color_surface: str
    color_nav_bg: str
    color_nav_text: str
    color_text: str
    color_text_muted: str


class BrandingUpdate(BaseModel):
    app_name: str = Field(min_length=1, max_length=100)
    color_primary: str = Field(pattern=r'^#[0-9A-Fa-f]{6}$')
    color_primary_hover: str = Field(pattern=r'^#[0-9A-Fa-f]{6}$')
    color_accent: str = Field(pattern=r'^#[0-9A-Fa-f]{6}$')
    color_bg: str = Field(pattern=r'^#[0-9A-Fa-f]{6}$')
    color_surface: str = Field(pattern=r'^#[0-9A-Fa-f]{6}$')
    color_nav_bg: str = Field(pattern=r'^#[0-9A-Fa-f]{6}$')
    color_nav_text: str = Field(pattern=r'^#[0-9A-Fa-f]{6}$')
    color_text: str = Field(pattern=r'^#[0-9A-Fa-f]{6}$')
    color_text_muted: str = Field(pattern=r'^#[0-9A-Fa-f]{6}$')
```

- [ ] **Step 4: Create branding route**

Create `backend/app/api/routes/branding.py`:

```python
import logging
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db
from app.models.settings import SystemSetting
from app.models.user import User
from app.schemas.branding import BrandingResponse, BrandingUpdate

router = APIRouter(prefix="/branding", tags=["branding"])
logger = logging.getLogger(__name__)

BRANDING_DEFAULTS: dict[str, str] = {
    "branding.app_name": "ConvoyPlan",
    "branding.logo_main": "",
    "branding.logo_horizontal": "",
    "branding.color_primary": "#E23D28",
    "branding.color_primary_hover": "#C23020",
    "branding.color_accent": "#3498db",
    "branding.color_bg": "#f5f3ee",
    "branding.color_surface": "#ffffff",
    "branding.color_nav_bg": "#2c3e50",
    "branding.color_nav_text": "#ecf0f1",
    "branding.color_text": "#2c3e50",
    "branding.color_text_muted": "#7f8c8d",
}

LOGOS_DIR = Path("/uploads/logos")


async def _get_branding_response(db: AsyncSession) -> BrandingResponse:
    result = await db.execute(
        select(SystemSetting).where(SystemSetting.key.like("branding.%"))
    )
    stored = {s.key: s.value for s in result.scalars().all()}
    merged: dict[str, str] = {**BRANDING_DEFAULTS, **stored}
    logo_main = merged["branding.logo_main"]
    logo_horizontal = merged["branding.logo_horizontal"]
    return BrandingResponse(
        app_name=merged["branding.app_name"],
        logo_main_url=f"/uploads/logos/{logo_main}" if logo_main else None,
        logo_horizontal_url=f"/uploads/logos/{logo_horizontal}" if logo_horizontal else None,
        color_primary=merged["branding.color_primary"],
        color_primary_hover=merged["branding.color_primary_hover"],
        color_accent=merged["branding.color_accent"],
        color_bg=merged["branding.color_bg"],
        color_surface=merged["branding.color_surface"],
        color_nav_bg=merged["branding.color_nav_bg"],
        color_nav_text=merged["branding.color_nav_text"],
        color_text=merged["branding.color_text"],
        color_text_muted=merged["branding.color_text_muted"],
    )


async def _upsert(db: AsyncSession, key: str, value: str) -> None:
    result = await db.execute(select(SystemSetting).where(SystemSetting.key == key))
    setting = result.scalar_one_or_none()
    if setting:
        setting.value = value
    else:
        db.add(SystemSetting(key=key, value=value))


@router.get("", response_model=BrandingResponse)
async def get_branding(db: AsyncSession = Depends(get_db)):
    return await _get_branding_response(db)


@router.put("", response_model=BrandingResponse)
async def update_branding(
    data: BrandingUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> BrandingResponse:
    if not current_user.is_superadmin:
        raise HTTPException(status_code=403, detail="Superadmin required")
    updates = {
        "branding.app_name": data.app_name,
        "branding.color_primary": data.color_primary,
        "branding.color_primary_hover": data.color_primary_hover,
        "branding.color_accent": data.color_accent,
        "branding.color_bg": data.color_bg,
        "branding.color_surface": data.color_surface,
        "branding.color_nav_bg": data.color_nav_bg,
        "branding.color_nav_text": data.color_nav_text,
        "branding.color_text": data.color_text,
        "branding.color_text_muted": data.color_text_muted,
    }
    for key, value in updates.items():
        await _upsert(db, key, value)
    await db.commit()
    return await _get_branding_response(db)


@router.post("/logo/{slot}", response_model=BrandingResponse)
async def upload_logo(
    slot: Literal["main", "horizontal"],
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> BrandingResponse:
    if not current_user.is_superadmin:
        raise HTTPException(status_code=403, detail="Superadmin required")
    content = await file.read()
    if len(content) > 2 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="File too large (max 2 MB)")
    ext = Path(file.filename or "").suffix.lower()
    if ext not in {".png", ".jpg", ".jpeg", ".svg"}:
        raise HTTPException(status_code=400, detail="Invalid file type (PNG, JPG, SVG only)")
    LOGOS_DIR.mkdir(parents=True, exist_ok=True)
    filename = f"{slot}{ext}"
    (LOGOS_DIR / filename).write_bytes(content)
    await _upsert(db, f"branding.logo_{slot}", filename)
    await db.commit()
    return await _get_branding_response(db)
```

- [ ] **Step 5: Run tests, confirm they pass**

```bash
cd backend && python -m pytest tests/test_branding.py -v
```

Expected: all 6 tests PASS.

- [ ] **Step 6: Create Alembic migration 0011**

Create `backend/alembic/versions/0011_branding_defaults.py`:

```python
"""branding defaults in system_settings

Revision ID: 0011
Revises: 0010
Create Date: 2026-05-12
"""
import sqlalchemy as sa
from alembic import op

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None

_DEFAULTS = {
    "branding.app_name": "ConvoyPlan",
    "branding.logo_main": "",
    "branding.logo_horizontal": "",
    "branding.color_primary": "#E23D28",
    "branding.color_primary_hover": "#C23020",
    "branding.color_accent": "#3498db",
    "branding.color_bg": "#f5f3ee",
    "branding.color_surface": "#ffffff",
    "branding.color_nav_bg": "#2c3e50",
    "branding.color_nav_text": "#ecf0f1",
    "branding.color_text": "#2c3e50",
    "branding.color_text_muted": "#7f8c8d",
}


def upgrade() -> None:
    conn = op.get_bind()
    for key, value in _DEFAULTS.items():
        conn.execute(
            sa.text(
                "INSERT INTO system_settings (key, value) VALUES (:key, :value) "
                "ON CONFLICT (key) DO NOTHING"
            ),
            {"key": key, "value": value},
        )


def downgrade() -> None:
    conn = op.get_bind()
    for key in _DEFAULTS:
        conn.execute(
            sa.text("DELETE FROM system_settings WHERE key = :key"),
            {"key": key},
        )
```

- [ ] **Step 7: Register router + mount StaticFiles in main.py**

Edit `backend/app/main.py`. Add import and router registration:

```python
# Add to imports at top:
from fastapi.staticfiles import StaticFiles
from app.api.routes import branding as branding_router

# Add after existing include_router calls (before @app.get("/health")):
app.include_router(branding_router.router, prefix="/api")
app.mount("/uploads", StaticFiles(directory="/uploads", html=False), name="uploads")
```

Full updated `backend/app/main.py`:

```python
import logging
import os
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.api.routes import (
    auth, convoys, vehicles, routing, organizations,
    tracking, lage, weather, overpass, status, users, leitstellen,
)
from app.api.routes import admin as admin_router
from app.api.routes import branding as branding_router
from app.api.routes import setup as setup_router

logger = logging.getLogger(__name__)

app = FastAPI(title="ConvoyPlan API", version="0.4.0")

_origins_env = os.environ.get("CORS_ORIGINS", "*")
_allow_origins = [o.strip() for o in _origins_env.split(",")] if _origins_env != "*" else ["*"]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_allow_origins,
    allow_credentials=_allow_origins != ["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router, prefix="/api")
app.include_router(vehicles.router, prefix="/api")
app.include_router(convoys.router, prefix="/api")
app.include_router(routing.router, prefix="/api")
app.include_router(organizations.router, prefix="/api")
app.include_router(tracking.router, prefix="/api")
app.include_router(lage.router, prefix="/api")
app.include_router(weather.router, prefix="/api")
app.include_router(overpass.router, prefix="/api")
app.include_router(status.router, prefix="/api")
app.include_router(users.router, prefix="/api")
app.include_router(admin_router.router, prefix="/api")
app.include_router(setup_router.router, prefix="/api")
app.include_router(leitstellen.router, prefix="/api")
app.include_router(branding_router.router, prefix="/api")

_uploads_dir = Path("/uploads")
_uploads_dir.mkdir(parents=True, exist_ok=True)
app.mount("/uploads", StaticFiles(directory="/uploads", html=False), name="uploads")


@app.get("/health")
async def health():
    return {"status": "ok", "version": "0.4.0"}
```

- [ ] **Step 8: Add logo_uploads volume to docker-compose.yml**

Edit `docker-compose.yml`. Add volume mount to the backend service and declare the volume.

In the `backend` service `volumes` list, add:
```yaml
      - logo_uploads:/uploads
```

In the top-level `volumes` dict, add:
```yaml
  logo_uploads:
```

Full updated relevant sections:
```yaml
  backend:
    build: ./backend
    command: sh -c "alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload"
    environment:
      DATABASE_URL: postgresql+asyncpg://marschplan:marschplan@db:5432/marschplan
      JWT_SECRET: changeme-in-production
      GRAPHHOPPER_URL: http://graphhopper:8989
    volumes:
      - ./backend:/app
      - cert_uploads:/certs
      - logo_uploads:/uploads
    depends_on:
      ...

volumes:
  postgres_data:
  osm_data:
  gh_graph:
  caddy_data:
  caddy_config:
  cert_uploads:
  logo_uploads:
```

- [ ] **Step 9: Run full backend test suite**

```bash
cd backend && python -m pytest -v 2>&1 | tail -20
```

Expected: all tests pass (53+ previously passing + 6 new branding tests).

- [ ] **Step 10: Commit**

```bash
git add backend/app/schemas/branding.py backend/app/api/routes/branding.py \
    backend/alembic/versions/0011_branding_defaults.py backend/tests/test_branding.py \
    backend/app/main.py docker-compose.yml
git commit -m "feat: branding API – schema, route, migration, StaticFiles mount"
```

---

## Task 2: Frontend — Branding Store, API Client, AppLogo, Layout

**Files:**
- Create: `frontend/src/lib/stores/branding.ts`
- Modify: `frontend/src/lib/api/index.ts`
- Modify: `frontend/src/lib/components/AppLogo.svelte`
- Modify: `frontend/src/routes/+layout.svelte`
- Modify: `frontend/src/app.html`

- [ ] **Step 1: Create branding store**

Create `frontend/src/lib/stores/branding.ts`:

```typescript
import { writable } from 'svelte/store';

export interface Branding {
    app_name: string;
    logo_main_url: string | null;
    logo_horizontal_url: string | null;
    color_primary: string;
    color_primary_hover: string;
    color_accent: string;
    color_bg: string;
    color_surface: string;
    color_nav_bg: string;
    color_nav_text: string;
    color_text: string;
    color_text_muted: string;
}

export const BRANDING_DEFAULTS: Branding = {
    app_name: 'ConvoyPlan',
    logo_main_url: null,
    logo_horizontal_url: null,
    color_primary: '#E23D28',
    color_primary_hover: '#C23020',
    color_accent: '#3498db',
    color_bg: '#f5f3ee',
    color_surface: '#ffffff',
    color_nav_bg: '#2c3e50',
    color_nav_text: '#ecf0f1',
    color_text: '#2c3e50',
    color_text_muted: '#7f8c8d',
};

export function applyBranding(b: Branding): void {
    const root = document.documentElement;
    root.style.setProperty('--color-primary', b.color_primary);
    root.style.setProperty('--color-primary-hover', b.color_primary_hover);
    root.style.setProperty('--color-accent', b.color_accent);
    root.style.setProperty('--color-bg', b.color_bg);
    root.style.setProperty('--color-surface', b.color_surface);
    root.style.setProperty('--color-nav-bg', b.color_nav_bg);
    root.style.setProperty('--color-nav-text', b.color_nav_text);
    root.style.setProperty('--color-text', b.color_text);
    root.style.setProperty('--color-text-muted', b.color_text_muted);
}

export const brandingStore = writable<Branding>(BRANDING_DEFAULTS);
```

- [ ] **Step 2: Add branding types and API to index.ts**

Edit `frontend/src/lib/api/index.ts`. Add after the `adminApi` block (around line 281) and before the `ZusatzKanal` interface:

```typescript
export interface BrandingData {
    app_name: string;
    logo_main_url: string | null;
    logo_horizontal_url: string | null;
    color_primary: string;
    color_primary_hover: string;
    color_accent: string;
    color_bg: string;
    color_surface: string;
    color_nav_bg: string;
    color_nav_text: string;
    color_text: string;
    color_text_muted: string;
}

export interface BrandingUpdate {
    app_name: string;
    color_primary: string;
    color_primary_hover: string;
    color_accent: string;
    color_bg: string;
    color_surface: string;
    color_nav_bg: string;
    color_nav_text: string;
    color_text: string;
    color_text_muted: string;
}

export const brandingApi = {
    get: () => api.get<BrandingData>('/api/branding'),
    update: (data: BrandingUpdate) => api.put<BrandingData>('/api/branding', data),
    uploadLogo: (slot: 'main' | 'horizontal', file: File) =>
        uploadFile<BrandingData>(`/api/branding/logo/${slot}`, file),
};
```

- [ ] **Step 3: Update AppLogo to use branding store**

Replace `frontend/src/lib/components/AppLogo.svelte` entirely:

```svelte
<script lang="ts">
    import { brandingStore } from '$lib/stores/branding';

    interface Props {
        variant?: 'horizontal' | 'main';
        height?: number | null;
        width?: number | null;
    }
    let { variant = 'horizontal', height = null, width = null }: Props = $props();

    const fallbackSrc = variant === 'main' ? '/Hauptlogo.svg' : '/LogoHorizontal.svg';

    const src = $derived(
        variant === 'main'
            ? ($brandingStore.logo_main_url ?? fallbackSrc)
            : ($brandingStore.logo_horizontal_url ?? fallbackSrc)
    );

    const style = width
        ? `width:${width}px;height:auto;display:block;object-fit:contain`
        : height
        ? `height:${height}px;width:auto;display:block;object-fit:contain`
        : `width:100%;height:auto;display:block;object-fit:contain`;
</script>

<img {src} alt={$brandingStore.app_name} {style} />
```

- [ ] **Step 4: Add CSS var defaults to app.html**

Edit `frontend/src/app.html`. Add `:root` defaults to the existing `<style>` block so the page renders correctly before `applyBranding()` runs client-side:

```html
<!doctype html>
<html lang="en">
	<head>
		<meta charset="utf-8" />
		<meta name="viewport" content="width=device-width, initial-scale=1" />
		<style>
			*, *::before, *::after { box-sizing: border-box; }
			html, body { margin: 0; padding: 0; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; }
			:root {
				--color-primary: #E23D28;
				--color-primary-hover: #C23020;
				--color-accent: #3498db;
				--color-bg: #f5f3ee;
				--color-surface: #ffffff;
				--color-nav-bg: #2c3e50;
				--color-nav-text: #ecf0f1;
				--color-text: #2c3e50;
				--color-text-muted: #7f8c8d;
			}
		</style>
		%sveltekit.head%
	</head>
	<body data-sveltekit-preload-data="hover">
		<div style="display: contents">%sveltekit.body%</div>
	</body>
</html>
```

- [ ] **Step 5: Update root layout to load branding + add footer**

Replace `frontend/src/routes/+layout.svelte` entirely:

```svelte
<script lang="ts">
	import { onMount } from 'svelte';
	import { goto } from '$app/navigation';
	import { page } from '$app/stores';
	import { auth } from '$lib/stores/auth';
	import { brandingStore, applyBranding } from '$lib/stores/branding';

	let { children } = $props();

	const PUBLIC_ROUTES = ['/login', '/share', '/setup'];
	let setupChecked = $state(false);

	onMount(async () => {
		auth.init();

		try {
			const resp = await fetch('/api/branding');
			if (resp.ok) {
				const data = await resp.json();
				brandingStore.set(data);
				applyBranding(data);
			}
		} catch {
			// Keep defaults
		}

		try {
			const resp = await fetch('/api/setup/status');
			if (resp.ok) {
				const data = await resp.json();
				if (data.setup_required && !$page.url.pathname.startsWith('/setup')) {
					goto('/setup');
					return;
				}
			}
		} catch {
			// Backend not reachable yet — don't block the UI
		}

		setupChecked = true;
	});

	$effect(() => {
		if (!setupChecked) return;
		const isPublic = PUBLIC_ROUTES.some((r) => $page.url.pathname.startsWith(r));
		if (!isPublic && !$auth.token && typeof window !== 'undefined') {
			goto('/login');
		}
	});
</script>

<svelte:head>
	<title>{$brandingStore.app_name}</title>
	<link rel="icon" type="image/svg+xml" href="/favicon.svg" />
</svelte:head>

{@render children()}

<footer class="powered-by">Powered by ConvoyPlan</footer>

<style>
	.powered-by {
		position: fixed;
		bottom: .25rem;
		right: .5rem;
		font-size: .65rem;
		color: var(--color-text-muted, #7f8c8d);
		opacity: 0.55;
		pointer-events: none;
		z-index: 1;
		user-select: none;
	}
</style>
```

- [ ] **Step 6: Verify TypeScript compiles**

```bash
cd frontend && npx svelte-check --tsconfig tsconfig.json 2>&1 | grep -E "Error|error" | head -20
```

Expected: no errors in the modified files.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/lib/stores/branding.ts frontend/src/lib/api/index.ts \
    frontend/src/lib/components/AppLogo.svelte frontend/src/routes/+layout.svelte \
    frontend/src/app.html
git commit -m "feat: branding store, API client, AppLogo, layout footer"
```

---

## Task 3: CSS Custom Properties Migration

Replace hardcoded brand hex colors in 4 Svelte files with CSS custom properties. JS constants used for MapLibre map layers (e.g. STATUS_COLORS) are **not** changed.

**Files:**
- Modify: `frontend/src/routes/plan/+page.svelte`
- Modify: `frontend/src/routes/admin/+page.svelte`
- Modify: `frontend/src/lib/components/InfoPill.svelte`
- Modify: `frontend/src/routes/tracking/[convoy_id]/+page.svelte`

- [ ] **Step 1: Migrate plan/+page.svelte**

Make the following exact string replacements in `frontend/src/routes/plan/+page.svelte`:

| Old string | New string |
|---|---|
| `border-bottom-color: #E23D28;` | `border-bottom-color: var(--color-primary);` |
| `background: #E23D28; border-color: #E23D28;` | `background: var(--color-primary); border-color: var(--color-primary);` |
| `background: #E23D28; color: white; border: none; border-radius: 4px; font-weight: 600; cursor: pointer; font-size: .9rem;` | `background: var(--color-primary); color: white; border: none; border-radius: 4px; font-weight: 600; cursor: pointer; font-size: .9rem;` |
| `.btn-small.active { background: #E23D28; }` | `.btn-small.active { background: var(--color-primary); }` |
| `.modal-btn-export { padding: .55rem 1.1rem; border-radius: 5px; border: none; background: #E23D28;` | `.modal-btn-export { padding: .55rem 1.1rem; border-radius: 5px; border: none; background: var(--color-primary);` |
| `.btn-export.active { background: rgba(226,61,40,.3); border-color: #E23D28;` | `.btn-export.active { background: rgba(226,61,40,.3); border-color: var(--color-primary);` |
| `.btn-small.danger { background: rgba(226,61,40,.3); border-color: #E23D28;` | `.btn-small.danger { background: rgba(226,61,40,.3); border-color: var(--color-primary);` |
| `background: #C23020; color: white; padding: .4rem .75rem; font-size: .8rem; margin: 0;` | `background: var(--color-primary-hover); color: white; padding: .4rem .75rem; font-size: .8rem; margin: 0;` |
| `background: #f5f3ee; }` (sidebar-header line) | `background: var(--color-bg); }` |
| `.kw-befehl-table th { background: #f5f3ee; }` | `.kw-befehl-table th { background: var(--color-bg); }` |
| `border: 1px solid #3498db;` (in .tag-pill) | `border: 1px solid var(--color-accent);` |
| `style="color:#E23D28"` (inline style in HTML) | `style="color: var(--color-primary)"` |
| `background: #E23D28;` (in kw-section, around line 1781) | `background: var(--color-primary);` |

Check work by confirming no remaining raw `#E23D28`, `#C23020`, or `#f5f3ee` in CSS context:

```bash
grep -n "#E23D28\|#C23020\|#f5f3ee" frontend/src/routes/plan/+page.svelte | grep -v "rgba\|//"
```

Expected: only remaining occurrences are inside `rgba(226,61,40` (intentional) and comment lines.

- [ ] **Step 2: Migrate admin/+page.svelte**

Make the following exact string replacements in `frontend/src/routes/admin/+page.svelte`:

| Old string | New string |
|---|---|
| `.tab.active { color: #E23D28; border-bottom-color: #E23D28;` | `.tab.active { color: var(--color-primary); border-bottom-color: var(--color-primary);` |
| `background: #C23020; color: white; padding: .4rem .75rem; border-radius: 4px;` | `background: var(--color-primary-hover); color: white; padding: .4rem .75rem; border-radius: 4px;` |
| `border-color: #E23D28; color: #E23D28; }` (in .btn-small.danger) | `border-color: var(--color-primary); color: var(--color-primary); }` |
| `background: #E23D28; color: white; border: none; border-radius: 4px; font-weight: 600; cursor: pointer;` (in .btn-primary) | `background: var(--color-primary); color: white; border: none; border-radius: 4px; font-weight: 600; cursor: pointer;` |

Verify:

```bash
grep -n "#E23D28\|#C23020" frontend/src/routes/admin/+page.svelte | grep -v "rgba\|//"
```

Expected: no results (or only results that will be inside the Branding tab added in Task 5 as color picker defaults, which is acceptable).

- [ ] **Step 3: Migrate InfoPill.svelte**

Make the following exact string replacements in `frontend/src/lib/components/InfoPill.svelte`:

| Old string | New string |
|---|---|
| `background: #C23020;` (line ~282, the first occurrence) | `background: var(--color-primary-hover);` |
| `.dot.err { background: #E23D28; }` | `.dot.err { background: var(--color-primary); }` |
| `.svc-val.err { color: #E23D28; }` | `.svc-val.err { color: var(--color-primary); }` |
| `background: #C23020; border-radius: 10px;` (line ~385) | `background: var(--color-primary-hover); border-radius: 10px;` |

Verify:

```bash
grep -n "#E23D28\|#C23020" frontend/src/lib/components/InfoPill.svelte
```

Expected: no results.

- [ ] **Step 4: Migrate tracking/[convoy_id]/+page.svelte**

Make one replacement in `frontend/src/routes/tracking/[convoy_id]/+page.svelte`:

In the CSS block, find `.sidebar-header { ... background: #f5f3ee; }` and change `background: #f5f3ee;` to `background: var(--color-bg);`.

Verify:

```bash
grep -n "#f5f3ee" frontend/src/routes/tracking/[convoy_id]/+page.svelte
```

Expected: no results.

- [ ] **Step 5: Final check across all Svelte files**

```bash
grep -rn "#E23D28\|#C23020\|#f5f3ee" frontend/src --include="*.svelte" | grep -v "rgba\|//"
```

Expected: zero results (all brand-color CSS values now use CSS custom properties).

- [ ] **Step 6: Commit**

```bash
git add frontend/src/routes/plan/+page.svelte frontend/src/routes/admin/+page.svelte \
    frontend/src/lib/components/InfoPill.svelte \
    "frontend/src/routes/tracking/[convoy_id]/+page.svelte"
git commit -m "feat: migrate hardcoded brand colors to CSS custom properties"
```

---

## Task 4: Setup Wizard — Branding Step

Add branding as step 3 in the setup wizard. Old step 3 (completion) becomes step 4. The step is skippable.

**Files:**
- Modify: `frontend/src/routes/setup/+page.svelte`

- [ ] **Step 1: Plan the structural changes**

Current flow: step 1 (account) → step 2 (server, "Einrichten" calls submit()) → step 3 (complete)

New flow: step 1 → step 2 (server, "Weiter →" calls nextStep()) → step 3 (branding, "Überspringen" or "Einrichten" calls submit()) → step 4 (complete)

Key changes to `submit()`:
1. After `POST /api/setup` succeeds, immediately call `POST /api/auth/login` with the user's credentials to get a bearer token
2. Call `PUT /api/branding` using that token (even with defaults, to ensure records exist)
3. Upload logos if files were selected
4. Set `step = 4` (was 3)

- [ ] **Step 2: Write the new setup page**

Replace `frontend/src/routes/setup/+page.svelte` entirely:

```svelte
<script lang="ts">
	import { goto } from '$app/navigation';
	import AppLogo from '$lib/components/AppLogo.svelte';

	type TlsMode = 'letsencrypt' | 'custom' | 'internal';

	let step = $state(1);
	let loading = $state(false);
	let error = $state('');

	// Step 1 — Account
	let email = $state('');
	let password = $state('');
	let passwordConfirm = $state('');

	// Step 2 — Server
	let domain = $state('');
	let tlsMode = $state<TlsMode>('letsencrypt');
	let acmeEmail = $state('');
	let certPem = $state('');
	let keyPem = $state('');

	// Step 3 — Branding
	let appName = $state('');
	let colorPrimary = $state('#E23D28');
	let colorPrimaryHover = $state('#C23020');
	let colorAccent = $state('#3498db');
	let colorBg = $state('#f5f3ee');
	let colorSurface = $state('#ffffff');
	let colorNavBg = $state('#2c3e50');
	let colorNavText = $state('#ecf0f1');
	let colorText = $state('#2c3e50');
	let colorTextMuted = $state('#7f8c8d');
	let showAdvancedColors = $state(false);
	let logoMainFile = $state<File | null>(null);
	let logoMainPreview = $state<string | null>(null);
	let logoHorizFile = $state<File | null>(null);
	let logoHorizPreview = $state<string | null>(null);

	function darken(hex: string, amount = 10): string {
		const r = parseInt(hex.slice(1, 3), 16) / 255;
		const g = parseInt(hex.slice(3, 5), 16) / 255;
		const b = parseInt(hex.slice(5, 7), 16) / 255;
		const max = Math.max(r, g, b), min = Math.min(r, g, b);
		let h = 0, s = 0, l = (max + min) / 2;
		if (max !== min) {
			const d = max - min;
			s = l > 0.5 ? d / (2 - max - min) : d / (max + min);
			if (max === r) h = ((g - b) / d + (g < b ? 6 : 0)) / 6;
			else if (max === g) h = ((b - r) / d + 2) / 6;
			else h = ((r - g) / d + 4) / 6;
		}
		l = Math.max(0, l - amount / 100);
		function hue2rgb(p: number, q: number, t: number) {
			if (t < 0) t += 1; if (t > 1) t -= 1;
			if (t < 1/6) return p + (q - p) * 6 * t;
			if (t < 1/2) return q;
			if (t < 2/3) return p + (q - p) * (2/3 - t) * 6;
			return p;
		}
		const q2 = l < 0.5 ? l * (1 + s) : l + s - l * s;
		const p2 = 2 * l - q2;
		const nr = Math.round(hue2rgb(p2, q2, h + 1/3) * 255);
		const ng = Math.round(hue2rgb(p2, q2, h) * 255);
		const nb = Math.round(hue2rgb(p2, q2, h - 1/3) * 255);
		return `#${[nr, ng, nb].map(x => x.toString(16).padStart(2, '0')).join('')}`;
	}

	function onPrimaryColorChange() {
		colorPrimaryHover = darken(colorPrimary, 10);
	}

	function readFile(file: File): Promise<string> {
		return new Promise((resolve, reject) => {
			const reader = new FileReader();
			reader.onload = () => resolve(reader.result as string);
			reader.onerror = reject;
			reader.readAsText(file);
		});
	}

	async function onCertUpload(e: Event) {
		const file = (e.target as HTMLInputElement).files?.[0];
		if (file) certPem = await readFile(file);
	}

	async function onKeyUpload(e: Event) {
		const file = (e.target as HTMLInputElement).files?.[0];
		if (file) keyPem = await readFile(file);
	}

	function onLogoMainChange(e: Event) {
		const file = (e.target as HTMLInputElement).files?.[0];
		if (!file) return;
		logoMainFile = file;
		logoMainPreview = URL.createObjectURL(file);
	}

	function onLogoHorizChange(e: Event) {
		const file = (e.target as HTMLInputElement).files?.[0];
		if (!file) return;
		logoHorizFile = file;
		logoHorizPreview = URL.createObjectURL(file);
	}

	function validateStep1(): string {
		if (!email) return 'E-Mail ist erforderlich';
		if (password.length < 8) return 'Passwort muss mindestens 8 Zeichen haben';
		if (password !== passwordConfirm) return 'Passwörter stimmen nicht überein';
		return '';
	}

	function validateStep2(): string {
		if (!domain) return 'Domain ist erforderlich';
		if (!/^[a-zA-Z0-9._-]+$/.test(domain)) return 'Ungültiges Domain-Format';
		if (tlsMode === 'letsencrypt' && !acmeEmail) return 'E-Mail für Let\'s Encrypt ist erforderlich';
		if (tlsMode === 'custom' && (!certPem || !keyPem)) return 'Zertifikat und Schlüssel sind erforderlich';
		return '';
	}

	function nextStep() {
		error = '';
		const validationError = step === 1 ? validateStep1() : validateStep2();
		if (validationError) { error = validationError; return; }
		step++;
	}

	async function submit() {
		error = '';
		const validationError = validateStep1() || validateStep2();
		if (validationError) { error = validationError; step = 1; return; }

		loading = true;
		try {
			// 1. Create admin account + server config
			const setupResp = await fetch('/api/setup', {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({
					email,
					password,
					domain,
					tls_mode: tlsMode,
					acme_email: acmeEmail || email,
					cert_pem: certPem,
					key_pem: keyPem,
				}),
			});

			if (setupResp.status === 409) { error = 'Setup wurde bereits durchgeführt.'; return; }
			if (!setupResp.ok) {
				const data = await setupResp.json().catch(() => ({}));
				error = data.detail || 'Fehler beim Setup';
				return;
			}

			// 2. Login to get token for branding API
			const loginResp = await fetch('/api/auth/login', {
				method: 'POST',
				headers: { 'Content-Type': 'application/json' },
				body: JSON.stringify({ email, password }),
			});
			if (!loginResp.ok) {
				// Non-fatal: setup succeeded, branding will use defaults
				step = 4;
				return;
			}
			const { access_token: token } = await loginResp.json();

			// 3. Save branding text/colors
			await fetch('/api/branding', {
				method: 'PUT',
				headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${token}` },
				body: JSON.stringify({
					app_name: appName || 'ConvoyPlan',
					color_primary: colorPrimary,
					color_primary_hover: colorPrimaryHover,
					color_accent: colorAccent,
					color_bg: colorBg,
					color_surface: colorSurface,
					color_nav_bg: colorNavBg,
					color_nav_text: colorNavText,
					color_text: colorText,
					color_text_muted: colorTextMuted,
				}),
			});

			// 4. Upload logos if selected
			if (logoMainFile) {
				const fd = new FormData();
				fd.append('file', logoMainFile);
				await fetch('/api/branding/logo/main', {
					method: 'POST',
					headers: { 'Authorization': `Bearer ${token}` },
					body: fd,
				});
			}
			if (logoHorizFile) {
				const fd = new FormData();
				fd.append('file', logoHorizFile);
				await fetch('/api/branding/logo/horizontal', {
					method: 'POST',
					headers: { 'Authorization': `Bearer ${token}` },
					body: fd,
				});
			}

			step = 4;
		} catch {
			error = 'Verbindungsfehler — bitte erneut versuchen';
		} finally {
			loading = false;
		}
	}
</script>

<div class="setup-page">
	<div class="setup-card">
		<div class="logo-area">
			<AppLogo variant="main" height={64} />
		</div>

		<div class="steps">
			<span class="step-dot" class:active={step >= 1} class:done={step > 1}>1</span>
			<span class="step-line"></span>
			<span class="step-dot" class:active={step >= 2} class:done={step > 2}>2</span>
			<span class="step-line"></span>
			<span class="step-dot" class:active={step >= 3} class:done={step > 3}>3</span>
			<span class="step-line"></span>
			<span class="step-dot" class:active={step >= 4}>4</span>
		</div>

		{#if error}
			<div class="error-bar">{error}</div>
		{/if}

		{#if step === 1}
			<h2>Admin-Account anlegen</h2>
			<p class="hint">Dieser Account hat vollen Zugriff auf alle Einstellungen.</p>
			<div class="form-group">
				<label>E-Mail</label>
				<input type="email" bind:value={email} placeholder="admin@example.com" autocomplete="username" />
			</div>
			<div class="form-group">
				<label>Passwort</label>
				<input type="password" bind:value={password} placeholder="Mindestens 8 Zeichen" autocomplete="new-password" />
			</div>
			<div class="form-group">
				<label>Passwort bestätigen</label>
				<input type="password" bind:value={passwordConfirm} placeholder="Passwort wiederholen" autocomplete="new-password" />
			</div>
			<button class="btn-primary" onclick={nextStep}>Weiter →</button>

		{:else if step === 2}
			<h2>Server konfigurieren</h2>
			<p class="hint">Wie ist dieser Server erreichbar?</p>

			<div class="form-group">
				<label>Domain / FQDN</label>
				<input type="text" bind:value={domain} placeholder="convoy.example.com" />
			</div>

			<div class="form-group">
				<label>SSL-Zertifikat</label>
				<div class="radio-group">
					<label class="radio-label">
						<input type="radio" bind:group={tlsMode} value="letsencrypt" />
						Automatisch (Let's Encrypt)
					</label>
					<label class="radio-label">
						<input type="radio" bind:group={tlsMode} value="custom" />
						Eigenes Zertifikat hochladen
					</label>
					<label class="radio-label">
						<input type="radio" bind:group={tlsMode} value="internal" />
						Intern / localhost (kein HTTPS)
					</label>
				</div>
			</div>

			{#if tlsMode === 'letsencrypt'}
				<div class="form-group">
					<label>E-Mail für Let's Encrypt</label>
					<input type="email" bind:value={acmeEmail} placeholder={email || 'admin@example.com'} />
					<span class="field-hint">Für Ablauf-Benachrichtigungen</span>
				</div>
			{/if}

			{#if tlsMode === 'custom'}
				<div class="form-group">
					<label>Zertifikat (cert.pem)</label>
					<input type="file" accept=".pem,.crt" onchange={onCertUpload} />
					{#if certPem}<span class="field-hint ok">✓ Geladen</span>{/if}
				</div>
				<div class="form-group">
					<label>Privater Schlüssel (key.pem)</label>
					<input type="file" accept=".pem,.key" onchange={onKeyUpload} />
					{#if keyPem}<span class="field-hint ok">✓ Geladen</span>{/if}
				</div>
			{/if}

			<div class="btn-row">
				<button class="btn-secondary" onclick={() => step--}>← Zurück</button>
				<button class="btn-primary" onclick={nextStep}>Weiter →</button>
			</div>

		{:else if step === 3}
			<h2>Branding</h2>
			<p class="hint">Passe Aussehen und Namen an deine Organisation an. Dieser Schritt ist optional.</p>

			<div class="form-group">
				<label>App-Name</label>
				<input type="text" bind:value={appName} placeholder="z.B. Feuerwehr München" />
				<span class="field-hint">Leer lassen für "ConvoyPlan"</span>
			</div>

			<div class="form-group">
				<label>Hauptlogo (quadratisch)</label>
				{#if logoMainPreview}
					<img src={logoMainPreview} alt="Vorschau" class="logo-preview" />
				{/if}
				<input type="file" accept=".png,.jpg,.jpeg,.svg" onchange={onLogoMainChange} />
				<span class="field-hint">PNG, JPG oder SVG, max. 2 MB</span>
			</div>

			<div class="form-group">
				<label>Horizontales Logo</label>
				{#if logoHorizPreview}
					<img src={logoHorizPreview} alt="Vorschau" class="logo-preview" />
				{/if}
				<input type="file" accept=".png,.jpg,.jpeg,.svg" onchange={onLogoHorizChange} />
			</div>

			<div class="form-group color-group">
				<label>Primärfarbe</label>
				<div class="color-row">
					<input type="color" bind:value={colorPrimary} oninput={onPrimaryColorChange} class="color-input" />
					<span class="color-hex">{colorPrimary}</span>
				</div>
			</div>

			<details class="advanced-colors">
				<summary>Erweiterte Farben</summary>
				<div class="adv-colors-grid">
					<div class="form-group color-group">
						<label>Hover</label>
						<div class="color-row">
							<input type="color" bind:value={colorPrimaryHover} class="color-input" />
							<span class="color-hex">{colorPrimaryHover}</span>
						</div>
					</div>
					<div class="form-group color-group">
						<label>Akzentfarbe</label>
						<div class="color-row">
							<input type="color" bind:value={colorAccent} class="color-input" />
							<span class="color-hex">{colorAccent}</span>
						</div>
					</div>
					<div class="form-group color-group">
						<label>Hintergrund</label>
						<div class="color-row">
							<input type="color" bind:value={colorBg} class="color-input" />
							<span class="color-hex">{colorBg}</span>
						</div>
					</div>
					<div class="form-group color-group">
						<label>Oberfläche</label>
						<div class="color-row">
							<input type="color" bind:value={colorSurface} class="color-input" />
							<span class="color-hex">{colorSurface}</span>
						</div>
					</div>
					<div class="form-group color-group">
						<label>Navigationsleiste</label>
						<div class="color-row">
							<input type="color" bind:value={colorNavBg} class="color-input" />
							<span class="color-hex">{colorNavBg}</span>
						</div>
					</div>
					<div class="form-group color-group">
						<label>Nav-Text</label>
						<div class="color-row">
							<input type="color" bind:value={colorNavText} class="color-input" />
							<span class="color-hex">{colorNavText}</span>
						</div>
					</div>
					<div class="form-group color-group">
						<label>Text</label>
						<div class="color-row">
							<input type="color" bind:value={colorText} class="color-input" />
							<span class="color-hex">{colorText}</span>
						</div>
					</div>
					<div class="form-group color-group">
						<label>Gedämpfter Text</label>
						<div class="color-row">
							<input type="color" bind:value={colorTextMuted} class="color-input" />
							<span class="color-hex">{colorTextMuted}</span>
						</div>
					</div>
				</div>
			</details>

			<p class="powered-by-note">Powered by ConvoyPlan</p>

			<div class="btn-row">
				<button class="btn-secondary" onclick={() => step--}>← Zurück</button>
				<button class="btn-secondary" onclick={submit} disabled={loading}>Überspringen</button>
				<button class="btn-primary" onclick={submit} disabled={loading}>
					{loading ? 'Wird eingerichtet…' : 'Einrichten'}
				</button>
			</div>

		{:else}
			<h2>Einrichtung abgeschlossen</h2>
			<p class="hint">
				ConvoyPlan ist einsatzbereit. Melde dich mit deinem Admin-Account an.
			</p>
			{#if domain && domain !== 'localhost'}
				<p class="hint">
					Domain: <strong>{domain}</strong> — Caddy wurde neu geladen.
					Let's Encrypt-Zertifikate werden in wenigen Sekunden ausgestellt.
				</p>
			{/if}
			<button class="btn-primary" onclick={() => goto('/login')}>Zum Login →</button>
		{/if}
	</div>
</div>

<style>
	:global(body) { margin: 0; font-family: system-ui, sans-serif; background: #0F1B24; color: white; }
	.setup-page { min-height: 100vh; display: flex; align-items: center; justify-content: center; padding: 1rem; }
	.setup-card { background: rgba(255,255,255,.05); border: 1px solid rgba(255,255,255,.1); border-radius: 12px; padding: 2rem; width: 100%; max-width: 440px; }
	.logo-area { display: flex; justify-content: center; margin-bottom: 1.5rem; }

	.steps { display: flex; align-items: center; justify-content: center; gap: 0; margin-bottom: 1.5rem; }
	.step-dot { width: 28px; height: 28px; border-radius: 50%; border: 2px solid rgba(255,255,255,.2); display: flex; align-items: center; justify-content: center; font-size: .75rem; color: rgba(255,255,255,.4); }
	.step-dot.active { border-color: #6B7F4D; color: #a8c070; }
	.step-dot.done { background: #6B7F4D; border-color: #6B7F4D; color: white; }
	.step-line { flex: 1; height: 2px; background: rgba(255,255,255,.12); max-width: 45px; }

	h2 { margin: 0 0 .25rem; font-size: 1.15rem; }
	.hint { color: rgba(255,255,255,.55); font-size: .85rem; margin: 0 0 1.25rem; }
	.error-bar { background: rgba(194,48,32,.2); border: 1px solid #C23020; color: #ff9e93; padding: .5rem .75rem; border-radius: 6px; font-size: .85rem; margin-bottom: 1rem; }

	.form-group { margin-bottom: 1rem; }
	.form-group label { display: block; font-size: .82rem; color: rgba(255,255,255,.65); margin-bottom: .3rem; }
	.form-group input[type="email"],
	.form-group input[type="text"],
	.form-group input[type="password"] {
		width: 100%; box-sizing: border-box; padding: .5rem .7rem;
		background: rgba(255,255,255,.08); border: 1px solid rgba(255,255,255,.18);
		border-radius: 6px; color: white; font-size: .9rem;
	}
	.form-group input[type="email"]:focus,
	.form-group input[type="text"]:focus,
	.form-group input[type="password"]:focus { outline: none; border-color: #6B7F4D; }
	.form-group input[type="file"] { font-size: .85rem; color: rgba(255,255,255,.7); }

	.logo-preview { max-height: 60px; max-width: 100%; margin-bottom: .5rem; border-radius: 4px; }

	.color-group .color-row { display: flex; align-items: center; gap: .5rem; }
	.color-input { width: 36px; height: 36px; padding: 0; border: none; border-radius: 4px; cursor: pointer; background: none; }
	.color-hex { font-size: .82rem; color: rgba(255,255,255,.6); font-family: monospace; }

	.advanced-colors { margin-bottom: 1rem; }
	.advanced-colors summary { font-size: .85rem; color: rgba(255,255,255,.65); cursor: pointer; margin-bottom: .75rem; }
	.adv-colors-grid { display: grid; grid-template-columns: 1fr 1fr; gap: .25rem 1rem; }

	.powered-by-note { font-size: .72rem; color: rgba(255,255,255,.35); text-align: center; margin: .75rem 0 0; }

	.radio-group { display: flex; flex-direction: column; gap: .4rem; }
	.radio-label { display: flex; align-items: center; gap: .5rem; font-size: .88rem; color: rgba(255,255,255,.8); cursor: pointer; }
	.radio-label input[type="radio"] { accent-color: #6B7F4D; }

	.field-hint { font-size: .76rem; color: rgba(255,255,255,.45); display: block; margin-top: .2rem; }
	.field-hint.ok { color: #a8c070; }

	.btn-primary { width: 100%; padding: .6rem 1rem; background: #6B7F4D; border: none; border-radius: 6px; color: white; font-size: .95rem; font-weight: 600; cursor: pointer; margin-top: .5rem; }
	.btn-primary:hover:not(:disabled) { background: #7a9158; }
	.btn-primary:disabled { opacity: .5; cursor: not-allowed; }
	.btn-secondary { padding: .6rem 1rem; background: rgba(255,255,255,.08); border: 1px solid rgba(255,255,255,.2); border-radius: 6px; color: white; font-size: .9rem; cursor: pointer; }
	.btn-row { display: flex; gap: .75rem; margin-top: .5rem; }
	.btn-row .btn-primary { flex: 1; margin-top: 0; }
</style>
```

- [ ] **Step 3: Verify TypeScript**

```bash
cd frontend && npx svelte-check --tsconfig tsconfig.json 2>&1 | grep -E "Error|error" | grep "setup" | head -10
```

Expected: no errors in setup page.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/routes/setup/+page.svelte
git commit -m "feat: add branding step (step 3) to setup wizard"
```

---

## Task 5: Admin — Branding Tab

Add a "Branding" tab to the `/admin` page with live preview, logo upload, color pickers, and reset-to-defaults.

**Files:**
- Modify: `frontend/src/routes/admin/+page.svelte`

- [ ] **Step 1: Plan the additions**

The admin page currently has `activeTab = $state<'benutzer' | 'leitstellen'>('benutzer')`. Change its type to include `'branding'`.

Add to script section:
- Import `brandingStore`, `applyBranding`, `BRANDING_DEFAULTS` from branding store
- Import `brandingApi` from `$lib/api`
- New state variables for branding form, logo files/previews, saving state
- `loadBranding()` called in `onMount`
- `$effect` for live color preview
- Helper functions: `saveBranding()`, `resetBrandingDefaults()`, `onLogoMainChange()`, `onLogoHorizChange()`

- [ ] **Step 2: Add branding state and functions to the script block**

In `frontend/src/routes/admin/+page.svelte`, after the existing imports (around line 7), add:

```typescript
import { brandingStore, applyBranding, BRANDING_DEFAULTS, type Branding } from '$lib/stores/branding';
import { brandingApi, type BrandingUpdate } from '$lib/api';
```

Change the `activeTab` type declaration from:
```typescript
let activeTab = $state<'benutzer' | 'leitstellen'>('benutzer');
```
to:
```typescript
let activeTab = $state<'benutzer' | 'leitstellen' | 'branding'>('benutzer');
```

In `onMount`, add `await loadBranding();` alongside `await loadLeitstellen();`.

Add these new state variables and functions after the Leitstellen section (around line 260–300, before closing of the `<script>` block):

```typescript
// ── Branding ──────────────────────────────────────────────────────────────
let brandingForm = $state<BrandingUpdate>({
    app_name: BRANDING_DEFAULTS.app_name,
    color_primary: BRANDING_DEFAULTS.color_primary,
    color_primary_hover: BRANDING_DEFAULTS.color_primary_hover,
    color_accent: BRANDING_DEFAULTS.color_accent,
    color_bg: BRANDING_DEFAULTS.color_bg,
    color_surface: BRANDING_DEFAULTS.color_surface,
    color_nav_bg: BRANDING_DEFAULTS.color_nav_bg,
    color_nav_text: BRANDING_DEFAULTS.color_nav_text,
    color_text: BRANDING_DEFAULTS.color_text,
    color_text_muted: BRANDING_DEFAULTS.color_text_muted,
});
let logoMainPreview = $state<string | null>(null);
let logoHorizPreview = $state<string | null>(null);
let logoMainFile = $state<File | null>(null);
let logoHorizFile = $state<File | null>(null);
let brandingSaving = $state(false);
let brandingError = $state('');
let brandingSuccess = $state(false);

$effect(() => {
    if (activeTab !== 'branding') return;
    const root = document.documentElement;
    root.style.setProperty('--color-primary', brandingForm.color_primary);
    root.style.setProperty('--color-primary-hover', brandingForm.color_primary_hover);
    root.style.setProperty('--color-accent', brandingForm.color_accent);
    root.style.setProperty('--color-bg', brandingForm.color_bg);
    root.style.setProperty('--color-surface', brandingForm.color_surface);
    root.style.setProperty('--color-nav-bg', brandingForm.color_nav_bg);
    root.style.setProperty('--color-nav-text', brandingForm.color_nav_text);
    root.style.setProperty('--color-text', brandingForm.color_text);
    root.style.setProperty('--color-text-muted', brandingForm.color_text_muted);
});

async function loadBranding() {
    try {
        const data = await brandingApi.get();
        brandingForm = {
            app_name: data.app_name,
            color_primary: data.color_primary,
            color_primary_hover: data.color_primary_hover,
            color_accent: data.color_accent,
            color_bg: data.color_bg,
            color_surface: data.color_surface,
            color_nav_bg: data.color_nav_bg,
            color_nav_text: data.color_nav_text,
            color_text: data.color_text,
            color_text_muted: data.color_text_muted,
        };
        logoMainPreview = data.logo_main_url;
        logoHorizPreview = data.logo_horizontal_url;
    } catch { /* keep defaults */ }
}

async function saveBranding() {
    brandingError = '';
    brandingSuccess = false;
    brandingSaving = true;
    try {
        const result = await brandingApi.update(brandingForm);
        brandingStore.set({ ...result });
        applyBranding({ ...result });
        brandingSuccess = true;
        setTimeout(() => { brandingSuccess = false; }, 3000);
    } catch (e: unknown) {
        brandingError = e instanceof Error ? e.message : 'Fehler beim Speichern';
    } finally {
        brandingSaving = false;
    }
}

function resetBrandingDefaults() {
    brandingForm = {
        app_name: BRANDING_DEFAULTS.app_name,
        color_primary: BRANDING_DEFAULTS.color_primary,
        color_primary_hover: BRANDING_DEFAULTS.color_primary_hover,
        color_accent: BRANDING_DEFAULTS.color_accent,
        color_bg: BRANDING_DEFAULTS.color_bg,
        color_surface: BRANDING_DEFAULTS.color_surface,
        color_nav_bg: BRANDING_DEFAULTS.color_nav_bg,
        color_nav_text: BRANDING_DEFAULTS.color_nav_text,
        color_text: BRANDING_DEFAULTS.color_text,
        color_text_muted: BRANDING_DEFAULTS.color_text_muted,
    };
    logoMainPreview = null;
    logoHorizPreview = null;
}

function onAdminLogoMainChange(e: Event) {
    const file = (e.target as HTMLInputElement).files?.[0];
    if (!file) return;
    logoMainFile = file;
    logoMainPreview = URL.createObjectURL(file);
    brandingApi.uploadLogo('main', file)
        .then(result => { brandingStore.set({ ...result }); applyBranding({ ...result }); })
        .catch(() => { brandingError = 'Logo-Upload fehlgeschlagen'; });
}

function onAdminLogoHorizChange(e: Event) {
    const file = (e.target as HTMLInputElement).files?.[0];
    if (!file) return;
    logoHorizFile = file;
    logoHorizPreview = URL.createObjectURL(file);
    brandingApi.uploadLogo('horizontal', file)
        .then(result => { brandingStore.set({ ...result }); applyBranding({ ...result }); })
        .catch(() => { brandingError = 'Logo-Upload fehlgeschlagen'; });
}
```

- [ ] **Step 3: Add Branding tab button in the tabs row**

In the HTML section, find the tabs row that contains `'benutzer'` and `'leitstellen'` tab buttons and add a third:

```html
<button class="tab" class:active={activeTab === 'branding'} onclick={() => activeTab = 'branding'}>
    Branding
</button>
```

- [ ] **Step 4: Add Branding tab content panel**

In the HTML section, after the `{:else if activeTab === 'leitstellen'}` block (and before `{/if}`), add:

```html
{:else if activeTab === 'branding'}
<div class="branding-panel">
    <h2>Branding</h2>

    {#if brandingError}
        <div class="error-bar">{brandingError} <button onclick={() => brandingError = ''}>✕</button></div>
    {/if}
    {#if brandingSuccess}
        <div class="success-bar">Gespeichert.</div>
    {/if}

    <div class="bf-section">
        <label class="bf-label">App-Name
            <input type="text" bind:value={brandingForm.app_name} placeholder="z.B. Feuerwehr München" />
        </label>
    </div>

    <div class="bf-section">
        <h3>Logos</h3>
        <div class="logo-row">
            <div class="logo-slot">
                <span class="bf-sublabel">Hauptlogo</span>
                {#if logoMainPreview}
                    <img src={logoMainPreview} alt="Hauptlogo" class="logo-thumb" />
                {/if}
                <input type="file" accept=".png,.jpg,.jpeg,.svg" onchange={onAdminLogoMainChange} />
            </div>
            <div class="logo-slot">
                <span class="bf-sublabel">Horizontales Logo</span>
                {#if logoHorizPreview}
                    <img src={logoHorizPreview} alt="Horizontales Logo" class="logo-thumb" />
                {/if}
                <input type="file" accept=".png,.jpg,.jpeg,.svg" onchange={onAdminLogoHorizChange} />
            </div>
        </div>
    </div>

    <div class="bf-section">
        <h3>Farben</h3>
        <div class="colors-grid">
            <label class="color-label">Primärfarbe
                <div class="color-row">
                    <input type="color" bind:value={brandingForm.color_primary} class="color-swatch" />
                    <span class="color-hex">{brandingForm.color_primary}</span>
                </div>
            </label>
            <label class="color-label">Hover
                <div class="color-row">
                    <input type="color" bind:value={brandingForm.color_primary_hover} class="color-swatch" />
                    <span class="color-hex">{brandingForm.color_primary_hover}</span>
                </div>
            </label>
            <label class="color-label">Akzent
                <div class="color-row">
                    <input type="color" bind:value={brandingForm.color_accent} class="color-swatch" />
                    <span class="color-hex">{brandingForm.color_accent}</span>
                </div>
            </label>
            <label class="color-label">Hintergrund
                <div class="color-row">
                    <input type="color" bind:value={brandingForm.color_bg} class="color-swatch" />
                    <span class="color-hex">{brandingForm.color_bg}</span>
                </div>
            </label>
            <label class="color-label">Oberfläche
                <div class="color-row">
                    <input type="color" bind:value={brandingForm.color_surface} class="color-swatch" />
                    <span class="color-hex">{brandingForm.color_surface}</span>
                </div>
            </label>
            <label class="color-label">Nav-Hintergrund
                <div class="color-row">
                    <input type="color" bind:value={brandingForm.color_nav_bg} class="color-swatch" />
                    <span class="color-hex">{brandingForm.color_nav_bg}</span>
                </div>
            </label>
            <label class="color-label">Nav-Text
                <div class="color-row">
                    <input type="color" bind:value={brandingForm.color_nav_text} class="color-swatch" />
                    <span class="color-hex">{brandingForm.color_nav_text}</span>
                </div>
            </label>
            <label class="color-label">Text
                <div class="color-row">
                    <input type="color" bind:value={brandingForm.color_text} class="color-swatch" />
                    <span class="color-hex">{brandingForm.color_text}</span>
                </div>
            </label>
            <label class="color-label">Gedämpfter Text
                <div class="color-row">
                    <input type="color" bind:value={brandingForm.color_text_muted} class="color-swatch" />
                    <span class="color-hex">{brandingForm.color_text_muted}</span>
                </div>
            </label>
        </div>
    </div>

    <div class="bf-actions">
        <button class="btn-secondary" onclick={resetBrandingDefaults}>Defaults wiederherstellen</button>
        <button class="btn-primary" onclick={saveBranding} disabled={brandingSaving}>
            {brandingSaving ? 'Wird gespeichert…' : 'Speichern'}
        </button>
    </div>
</div>
```

- [ ] **Step 5: Add CSS for the new branding panel**

In the `<style>` block of `frontend/src/routes/admin/+page.svelte`, add:

```css
    .branding-panel { padding: 1.5rem; max-width: 700px; }
    .branding-panel h2 { margin: 0 0 1rem; font-size: 1.1rem; }
    .branding-panel h3 { margin: 0 0 .6rem; font-size: .9rem; color: #555; }
    .bf-section { margin-bottom: 1.5rem; }
    .bf-label { display: flex; flex-direction: column; gap: .3rem; font-size: .85rem; color: #555; }
    .bf-label input[type="text"] { padding: .45rem .7rem; border: 1px solid #ddd; border-radius: 4px; font-size: .9rem; width: 100%; box-sizing: border-box; }
    .bf-sublabel { font-size: .82rem; color: #555; margin-bottom: .25rem; display: block; }
    .success-bar { background: #d4edda; border: 1px solid #c3e6cb; color: #155724; padding: .4rem .75rem; border-radius: 4px; margin-bottom: 1rem; font-size: .85rem; }
    .logo-row { display: flex; gap: 1.5rem; flex-wrap: wrap; }
    .logo-slot { display: flex; flex-direction: column; gap: .3rem; }
    .logo-thumb { max-height: 52px; max-width: 160px; border: 1px solid #ddd; border-radius: 4px; }
    .colors-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: .75rem 1rem; }
    .color-label { display: flex; flex-direction: column; gap: .25rem; font-size: .8rem; color: #555; }
    .color-row { display: flex; align-items: center; gap: .4rem; }
    .color-swatch { width: 32px; height: 32px; padding: 0; border: 1px solid #ccc; border-radius: 4px; cursor: pointer; }
    .color-hex { font-size: .75rem; font-family: monospace; color: #666; }
    .bf-actions { display: flex; gap: .75rem; justify-content: flex-end; padding-top: .5rem; border-top: 1px solid #eee; margin-top: 1rem; }
```

- [ ] **Step 6: Verify TypeScript**

```bash
cd frontend && npx svelte-check --tsconfig tsconfig.json 2>&1 | grep -E "Error|error" | grep "admin" | head -10
```

Expected: no errors.

- [ ] **Step 7: Run full backend tests one final time**

```bash
cd backend && python -m pytest -v 2>&1 | tail -10
```

Expected: all tests pass.

- [ ] **Step 8: Commit**

```bash
git add frontend/src/routes/admin/+page.svelte
git commit -m "feat: add Branding tab to admin panel with live preview"
```
