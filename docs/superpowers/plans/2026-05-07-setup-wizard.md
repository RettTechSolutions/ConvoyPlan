# First-Run Setup Wizard Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace env-var superadmin seeding with a first-run browser wizard that creates the superadmin account, configures the server domain, and sets up SSL — with immediate Caddy live-reload.

**Architecture:** A `system_settings` key/value table persists domain+TLS config. On first load, the frontend checks `GET /api/setup/status`; if setup is required it redirects to `/setup`. The wizard posts to `POST /api/setup` which creates the superadmin, saves settings, writes a Caddyfile to a shared `/certs` volume, and live-reloads Caddy via its admin API at `http://caddy:2019`. Caddy's `entrypoint.sh` is updated to prefer the persisted `/certs/Caddyfile` over env-var-generated config on startup.

**Tech Stack:** FastAPI, SQLAlchemy async, Alembic, SvelteKit (Svelte 5 runes), httpx, Caddy 2 admin API, Docker named volumes

---

## File Map

**New files:**
- `backend/app/models/settings.py` — `SystemSetting` key/value model
- `backend/alembic/versions/0008_settings.py` — migration
- `backend/app/schemas/setup.py` — `SetupRequest`, `SetupStatusResponse` Pydantic schemas
- `backend/app/api/routes/setup.py` — `/api/setup/status` and `/api/setup` endpoints
- `frontend/src/routes/setup/+page.svelte` — 3-step setup wizard

**Modified files:**
- `backend/app/main.py` — remove `_seed_superadmin` + lifespan, register setup router
- `backend/app/config.py` — remove `superadmin_email`/`superadmin_password`, add `caddy_admin_url`
- `caddy/entrypoint.sh` — add `admin 0.0.0.0:2019` global option; prefer `/certs/Caddyfile` if present
- `docker-compose.yml` — add `cert_uploads` named volume; mount it into backend (rw) and caddy (ro); remove `SUPERADMIN_EMAIL`/`SUPERADMIN_PASSWORD` env vars
- `portainer-stack.yml` — same changes
- `frontend/src/routes/+layout.svelte` — add `/setup` to public routes; check setup status and redirect if needed
- `.env.example` — remove `SUPERADMIN_EMAIL`/`SUPERADMIN_PASSWORD` lines

---

## Task 1: SystemSetting model + migration

**Files:**
- Create: `backend/app/models/settings.py`
- Create: `backend/alembic/versions/0008_settings.py`

- [ ] **Step 1: Create the model**

Create `backend/app/models/settings.py`:

```python
from sqlalchemy import String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class SystemSetting(Base):
    __tablename__ = "system_settings"

    key: Mapped[str] = mapped_column(String(255), primary_key=True)
    value: Mapped[str] = mapped_column(Text, nullable=False, default="")
```

- [ ] **Step 2: Create migration**

Create `backend/alembic/versions/0008_settings.py`:

```python
"""add system_settings table

Revision ID: 0008
Revises: 0007
Create Date: 2026-05-07
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.engine.reflection import Inspector

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = Inspector.from_engine(bind)
    if "system_settings" not in inspector.get_table_names():
        op.create_table(
            "system_settings",
            sa.Column("key", sa.String(255), primary_key=True),
            sa.Column("value", sa.Text(), nullable=False, server_default=""),
        )


def downgrade() -> None:
    op.drop_table("system_settings")
```

- [ ] **Step 3: Commit**

```bash
git add backend/app/models/settings.py backend/alembic/versions/0008_settings.py
git commit -m "feat: add system_settings model and migration"
```

---

## Task 2: Setup schemas

**Files:**
- Create: `backend/app/schemas/setup.py`

- [ ] **Step 1: Create schemas**

Create `backend/app/schemas/setup.py`:

```python
from pydantic import BaseModel, EmailStr
from typing import Literal


class SetupStatusResponse(BaseModel):
    setup_required: bool


class SetupRequest(BaseModel):
    # Admin account
    email: EmailStr
    password: str

    # Server config
    domain: str
    tls_mode: Literal["letsencrypt", "custom", "internal"]
    acme_email: EmailStr = "admin@example.com"

    # Custom cert (PEM content as strings, only when tls_mode == "custom")
    cert_pem: str = ""
    key_pem: str = ""
```

- [ ] **Step 2: Commit**

```bash
git add backend/app/schemas/setup.py
git commit -m "feat: add setup request/response schemas"
```

---

## Task 3: Setup API routes

**Files:**
- Create: `backend/app/api/routes/setup.py`

- [ ] **Step 1: Create setup.py**

Create `backend/app/api/routes/setup.py`:

```python
import logging
from pathlib import Path

import bcrypt
import httpx
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db
from app.config import settings
from app.database import get_db_session
from app.models.settings import SystemSetting
from app.models.user import User
from app.schemas.setup import SetupRequest, SetupStatusResponse

router = APIRouter(prefix="/setup", tags=["setup"])
logger = logging.getLogger(__name__)

CERTS_DIR = Path("/certs")


async def _superadmin_exists(db: AsyncSession) -> bool:
    result = await db.execute(select(User).where(User.is_superadmin == True))
    return result.scalar_one_or_none() is not None


def _generate_caddyfile(domain: str, tls_mode: str, acme_email: str) -> str:
    if tls_mode == "custom":
        tls_directive = "tls /certs/cert.pem /certs/key.pem"
    elif tls_mode == "internal":
        tls_directive = "tls internal"
    else:
        tls_directive = ""  # auto Let's Encrypt

    return f"""{{
    admin 0.0.0.0:2019
    email {acme_email}
}}

{domain} {{
    {tls_directive}

    handle /api/* {{
        reverse_proxy backend:8000
    }}
    handle /ws/* {{
        reverse_proxy backend:8000
    }}
    handle {{
        reverse_proxy frontend:3000
    }}
}}
"""


async def _reload_caddy(caddyfile: str) -> bool:
    """Push new Caddyfile to Caddy's admin API. Returns True on success."""
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            # Step 1: adapt Caddyfile → JSON
            adapt = await client.post(
                f"{settings.caddy_admin_url}/adapt",
                content=caddyfile.encode(),
                params={"adapter": "caddyfile"},
            )
            adapt.raise_for_status()
            # Step 2: load JSON config
            load = await client.post(
                f"{settings.caddy_admin_url}/load",
                content=adapt.content,
                headers={"Content-Type": "application/json"},
            )
            load.raise_for_status()
            return True
    except Exception as exc:
        logger.warning("Caddy reload failed (will apply on next start): %s", exc)
        return False


@router.get("/status", response_model=SetupStatusResponse)
async def setup_status(db: AsyncSession = Depends(get_db)):
    return SetupStatusResponse(setup_required=not await _superadmin_exists(db))


@router.post("", status_code=201)
async def run_setup(data: SetupRequest, db: AsyncSession = Depends(get_db)):
    if await _superadmin_exists(db):
        raise HTTPException(409, "Setup already completed")

    # Validate domain format
    import re
    if not re.match(r'^[a-zA-Z0-9._-]+$', data.domain):
        raise HTTPException(400, "Invalid domain format")

    # Create superadmin
    user = User(
        email=data.email,
        hashed_password=bcrypt.hashpw(data.password.encode(), bcrypt.gensalt()).decode(),
        is_superadmin=True,
    )
    db.add(user)

    # Persist settings
    for key, value in [
        ("domain", data.domain),
        ("tls_mode", data.tls_mode),
        ("acme_email", data.acme_email),
    ]:
        db.add(SystemSetting(key=key, value=value))

    await db.commit()

    # Write cert files if custom TLS
    CERTS_DIR.mkdir(parents=True, exist_ok=True)
    if data.tls_mode == "custom" and data.cert_pem and data.key_pem:
        (CERTS_DIR / "cert.pem").write_text(data.cert_pem)
        (CERTS_DIR / "key.pem").write_text(data.key_pem)

    # Write Caddyfile to shared volume (persists across restarts)
    caddyfile = _generate_caddyfile(data.domain, data.tls_mode, data.acme_email)
    (CERTS_DIR / "Caddyfile").write_text(caddyfile)

    # Live-reload Caddy
    reloaded = await _reload_caddy(caddyfile)

    return {"status": "ok", "caddy_reloaded": reloaded}
```

- [ ] **Step 2: Commit**

```bash
git add backend/app/api/routes/setup.py
git commit -m "feat: setup API routes (status + run_setup with Caddy reload)"
```

---

## Task 4: Update main.py and config.py

**Files:**
- Modify: `backend/app/main.py`
- Modify: `backend/app/config.py`

- [ ] **Step 1: Update config.py**

Replace `backend/app/config.py`:

```python
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str = "postgresql+asyncpg://marschplan:marschplan@localhost:5432/marschplan"
    jwt_secret: str = "changeme-in-production"
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 60 * 24 * 7  # 7 days
    graphhopper_url: str = "http://localhost:8989"
    caddy_admin_url: str = "http://caddy:2019"

    class Config:
        env_file = ".env"


settings = Settings()
```

- [ ] **Step 2: Update main.py — remove seed, register setup router**

Replace `backend/app/main.py`:

```python
import logging
import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import (
    auth, convoys, vehicles, routing, organizations,
    tracking, lage, weather, overpass, status, users,
)
from app.api.routes import admin as admin_router
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


@app.get("/health")
async def health():
    return {"status": "ok", "version": "0.4.0"}
```

- [ ] **Step 3: Commit**

```bash
git add backend/app/main.py backend/app/config.py
git commit -m "feat: register setup router, remove seed logic, add caddy_admin_url config"
```

---

## Task 5: Update Caddy entrypoint and Docker Compose

**Files:**
- Modify: `caddy/entrypoint.sh`
- Modify: `docker-compose.yml`
- Modify: `portainer-stack.yml`

- [ ] **Step 1: Update caddy/entrypoint.sh**

Replace `caddy/entrypoint.sh`:

```sh
#!/bin/sh
set -e

# If setup wizard wrote a Caddyfile to the shared volume, use it directly.
if [ -f "/certs/Caddyfile" ]; then
    echo "[caddy] Using persisted Caddyfile from /certs/Caddyfile"
    exec caddy run --config /certs/Caddyfile --adapter caddyfile
fi

# Otherwise fall back to env-var-based generation (initial start before setup).
DOMAIN="${DOMAIN:-localhost}"
ACME_EMAIL="${ACME_EMAIL:-admin@example.com}"

if [ -n "$CADDY_TLS_CERT" ] && [ -n "$CADDY_TLS_KEY" ]; then
    TLS_DIRECTIVE="tls $CADDY_TLS_CERT $CADDY_TLS_KEY"
elif [ "$DOMAIN" = "localhost" ]; then
    TLS_DIRECTIVE="tls internal"
else
    TLS_DIRECTIVE=""
fi

# Validate DOMAIN to prevent Caddyfile injection
case "$DOMAIN" in
    *[!a-zA-Z0-9._-]*)
        echo "[caddy] ERROR: DOMAIN contains invalid characters: $DOMAIN" >&2
        exit 1
        ;;
esac

cat > /tmp/Caddyfile << CADDYEOF
{
    admin 0.0.0.0:2019
    email $ACME_EMAIL
}

$DOMAIN {
    $TLS_DIRECTIVE

    handle /api/* {
        reverse_proxy backend:8000
    }
    handle /ws/* {
        reverse_proxy backend:8000
    }
    handle {
        reverse_proxy frontend:3000
    }
}
CADDYEOF

echo "[caddy] Starting with domain: $DOMAIN (env-var mode)"
exec caddy run --config /tmp/Caddyfile --adapter caddyfile
```

Make executable:
```bash
chmod +x caddy/entrypoint.sh
```

- [ ] **Step 2: Update docker-compose.yml**

In `docker-compose.yml`:

1. Add `cert_uploads` volume mount to `backend` service (after the `./backend:/app` line):
```yaml
      - cert_uploads:/certs
```

2. Remove `SUPERADMIN_EMAIL` and `SUPERADMIN_PASSWORD` from backend environment.

3. Change caddy's cert volume from `${CERT_DIR:-/tmp}:/certs:ro` to `cert_uploads:/certs:ro`.

4. Add `cert_uploads:` to the top-level `volumes:` block.

Full `docker-compose.yml` after changes:

```yaml
services:
  db:
    image: postgis/postgis:15-3.4
    environment:
      POSTGRES_USER: marschplan
      POSTGRES_PASSWORD: marschplan
      POSTGRES_DB: marschplan
    volumes:
      - postgres_data:/var/lib/postgresql/data
    ports:
      - "5432:5432"
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U marschplan"]
      interval: 5s
      timeout: 5s
      retries: 10

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
    depends_on:
      db:
        condition: service_healthy
      graphhopper:
        condition: service_healthy

  graphhopper:
    build:
      context: ./graphhopper
      args:
        GH_VERSION: "9.1"
    environment:
      OSM_DOWNLOAD_URL: https://download.geofabrik.de/europe/germany-latest.osm.pbf
      OSM_FILENAME: germany-latest.osm.pbf
      JAVA_OPTS: -Xmx2g -Xms512m -XX:+UseG1GC
    volumes:
      - osm_data:/data/osm
      - gh_graph:/data/graph
    ports:
      - "8989:8989"
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8989/health"]
      interval: 15s
      timeout: 10s
      retries: 40
      start_period: 30s

  frontend:
    build:
      context: ./frontend
    depends_on:
      - backend

  caddy:
    image: caddy:2-alpine
    ports:
      - "${HTTP_PORT:-80}:80"
      - "${HTTPS_PORT:-443}:443"
    environment:
      DOMAIN: ${DOMAIN:-localhost}
      ACME_EMAIL: ${ACME_EMAIL:-admin@example.com}
      CADDY_TLS_CERT: ${CADDY_TLS_CERT:-}
      CADDY_TLS_KEY: ${CADDY_TLS_KEY:-}
    volumes:
      - ./caddy/entrypoint.sh:/entrypoint.sh:ro
      - caddy_data:/data
      - caddy_config:/config
      - cert_uploads:/certs:ro
    entrypoint: ["/bin/sh", "/entrypoint.sh"]
    depends_on:
      - frontend
      - backend

volumes:
  postgres_data:
  osm_data:
  gh_graph:
  caddy_data:
  caddy_config:
  cert_uploads:
```

- [ ] **Step 3: Update portainer-stack.yml**

Apply the same changes to `portainer-stack.yml`:
- Remove `SUPERADMIN_EMAIL` and `SUPERADMIN_PASSWORD` from backend environment
- Add `cert_uploads:/certs` volume mount to backend
- Change caddy cert volume from `${CERT_DIR:-/tmp}:/certs:ro` to `cert_uploads:/certs:ro`
- Add `cert_uploads:` to volumes block

```yaml
services:
  db:
    image: postgis/postgis:15-3.4
    restart: unless-stopped
    environment:
      POSTGRES_USER: ${POSTGRES_USER:-marschplan}
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD:-marschplan}
      POSTGRES_DB: ${POSTGRES_DB:-marschplan}
    volumes:
      - postgres_data:/var/lib/postgresql/data
    ports:
      - "${DB_PORT:-5432}:5432"
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U ${POSTGRES_USER:-marschplan}"]
      interval: 5s
      timeout: 5s
      retries: 10

  backend:
    image: ${BACKEND_IMAGE:-marschplan-backend:latest}
    restart: unless-stopped
    command: sh -c "alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port 8000"
    environment:
      DATABASE_URL: postgresql+asyncpg://${POSTGRES_USER:-marschplan}:${POSTGRES_PASSWORD:-marschplan}@db:5432/${POSTGRES_DB:-marschplan}
      JWT_SECRET: ${JWT_SECRET:-changeme-in-production}
      GRAPHHOPPER_URL: http://graphhopper:8989
    volumes:
      - cert_uploads:/certs
    depends_on:
      db:
        condition: service_healthy
      graphhopper:
        condition: service_healthy

  graphhopper:
    image: ${GRAPHHOPPER_IMAGE:-marschplan-graphhopper:latest}
    restart: unless-stopped
    environment:
      OSM_DOWNLOAD_URL: ${OSM_DOWNLOAD_URL:-https://download.geofabrik.de/europe/germany-latest.osm.pbf}
      OSM_FILENAME: ${OSM_FILENAME:-germany-latest.osm.pbf}
      JAVA_OPTS: ${JAVA_OPTS:--Xmx2g -Xms512m -XX:+UseG1GC}
    volumes:
      - osm_data:/data/osm
      - gh_graph:/data/graph
    ports:
      - "${GH_PORT:-8989}:8989"
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8989/health"]
      interval: 15s
      timeout: 10s
      retries: 40
      start_period: 30s

  frontend:
    image: ${FRONTEND_IMAGE:-marschplan-frontend:latest}
    restart: unless-stopped
    depends_on:
      - backend

  caddy:
    image: caddy:2-alpine
    restart: unless-stopped
    ports:
      - "${HTTP_PORT:-80}:80"
      - "${HTTPS_PORT:-443}:443"
    environment:
      DOMAIN: ${DOMAIN:-localhost}
      ACME_EMAIL: ${ACME_EMAIL:-admin@example.com}
      CADDY_TLS_CERT: ${CADDY_TLS_CERT:-}
      CADDY_TLS_KEY: ${CADDY_TLS_KEY:-}
    volumes:
      - ./caddy/entrypoint.sh:/entrypoint.sh:ro
      - caddy_data:/data
      - caddy_config:/config
      - cert_uploads:/certs:ro
    entrypoint: ["/bin/sh", "/entrypoint.sh"]
    depends_on:
      - frontend
      - backend

volumes:
  postgres_data:
  osm_data:
  gh_graph:
  caddy_data:
  caddy_config:
  cert_uploads:
```

- [ ] **Step 4: Update .env.example — remove superadmin env vars**

In `.env.example`, remove these lines:
```
# Superadmin — created automatically on first start if no superadmin exists
SUPERADMIN_EMAIL=admin@yourdomain.com
SUPERADMIN_PASSWORD=change-me-strong-password
```

Replace with:
```
# Superadmin account is created via the first-run setup wizard at /setup
```

- [ ] **Step 5: Validate YAML**

```bash
python3 -c "import yaml; yaml.safe_load(open('docker-compose.yml'))" && echo "docker-compose OK"
python3 -c "import yaml; yaml.safe_load(open('portainer-stack.yml'))" && echo "portainer-stack OK"
```

Expected: both print OK.

- [ ] **Step 6: Commit**

```bash
git add caddy/entrypoint.sh docker-compose.yml portainer-stack.yml .env.example
git commit -m "feat: Caddy uses persisted Caddyfile, cert_uploads shared volume, remove superadmin env vars"
```

---

## Task 6: Frontend — layout guard

**Files:**
- Modify: `frontend/src/routes/+layout.svelte`

- [ ] **Step 1: Add setup status check to layout**

Replace `frontend/src/routes/+layout.svelte`:

```svelte
<script lang="ts">
	import { onMount } from 'svelte';
	import { goto } from '$app/navigation';
	import { page } from '$app/stores';
	import { auth } from '$lib/stores/auth';

	let { children } = $props();

	const PUBLIC_ROUTES = ['/login', '/share', '/setup'];

	onMount(async () => {
		auth.init();

		// Check if first-run setup is required
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
	});

	$effect(() => {
		const isPublic = PUBLIC_ROUTES.some((r) => $page.url.pathname.startsWith(r));
		if (!isPublic && !$auth.token && typeof window !== 'undefined') {
			goto('/login');
		}
	});
</script>

<svelte:head>
	<title>ConvoyPlan</title>
	<link rel="icon" type="image/svg+xml" href="/favicon.svg" />
</svelte:head>

{@render children()}
```

- [ ] **Step 2: Run svelte-check**

```bash
cd /path/to/project/frontend && npx svelte-check --tsconfig ./tsconfig.json 2>&1 | grep -E "ERROR|COMPLETED"
```

Expected: same error count as before (errors are pre-existing in tracking page, not in layout).

- [ ] **Step 3: Commit**

```bash
git add frontend/src/routes/+layout.svelte
git commit -m "feat: redirect to /setup if first-run setup not completed"
```

---

## Task 7: Frontend — setup wizard page

**Files:**
- Create: `frontend/src/routes/setup/+page.svelte`

- [ ] **Step 1: Create the setup wizard**

Create `frontend/src/routes/setup/+page.svelte`:

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
			const resp = await fetch('/api/setup', {
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

			if (resp.status === 409) {
				error = 'Setup wurde bereits durchgeführt.';
				return;
			}
			if (!resp.ok) {
				const data = await resp.json().catch(() => ({}));
				error = data.detail || 'Fehler beim Setup';
				return;
			}

			step = 3;
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
			<span class="step-dot" class:active={step >= 3}>3</span>
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
	.step-line { flex: 1; height: 2px; background: rgba(255,255,255,.12); max-width: 60px; }

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

- [ ] **Step 2: Run svelte-check**

```bash
cd /path/to/project/frontend && npx svelte-check --tsconfig ./tsconfig.json 2>&1 | grep -E "ERROR|COMPLETED"
```

Expected: 20 pre-existing errors only (all in tracking page), no new errors.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/routes/setup/+page.svelte
git commit -m "feat: first-run setup wizard (account + domain + SSL in 3 steps)"
```

---

## Self-Review

**Spec coverage:**
- ✅ `GET /api/setup/status` → Task 3
- ✅ `POST /api/setup` — creates superadmin, only when none exists → Task 3
- ✅ `system_settings` table for domain/TLS/ACME config → Task 1
- ✅ Cert file upload (PEM text → written to shared volume) → Task 3
- ✅ Caddy live-reload via admin API (`/adapt` + `/load`) → Task 3
- ✅ Shared `cert_uploads` volume between backend and Caddy → Task 5
- ✅ Caddy entrypoint prefers persisted `/certs/Caddyfile` → Task 5
- ✅ `admin 0.0.0.0:2019` so backend can reach Caddy admin API → Tasks 3 + 5
- ✅ Remove `_seed_superadmin` and env-based credentials → Task 4
- ✅ Frontend layout redirects to `/setup` if setup required → Task 6
- ✅ 3-step setup wizard (account → server → done) → Task 7
- ✅ TLS mode: Let's Encrypt / custom cert / internal → Task 7
- ✅ File upload via FileReader → PEM string in JSON body → Task 7
- ✅ ACME email field for Let's Encrypt mode → Task 7
- ✅ `.env.example` updated → Task 5
- ✅ `portainer-stack.yml` updated → Task 5

**No placeholders found.**

**Type consistency:** `SetupRequest.tls_mode` uses `Literal["letsencrypt", "custom", "internal"]` (Task 2), the `_generate_caddyfile` function in Task 3 handles all three values, and the frontend `TlsMode` type (Task 7) uses the same three string values. Consistent throughout.
