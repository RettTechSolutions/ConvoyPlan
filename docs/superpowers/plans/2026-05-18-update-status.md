# Update-Status im Admin-Bereich — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Superadmins können im Admin-Bereich sehen ob eine neue GitHub-Version verfügbar ist und das Update per Klick anstoßen.

**Architecture:** Ein Shared Volume `update_status` verbindet Updater und Backend. Der Updater schreibt nach jedem Deploy eine `status.json` und prüft auf eine `trigger`-Datei für manuelle Updates. Das Backend stellt zwei neue superadmin-geschützte Endpoints bereit. Das Frontend bekommt einen neuen Tab "System" mit Status-Card und Trigger-Button der nach Klick per Polling den Fortschritt überwacht.

**Tech Stack:** Docker Named Volume, Bash (update.sh), FastAPI + httpx (Backend), Svelte 5 $state (Frontend)

---

## File Map

**Modify:**
- `docker-compose.yml` — Volume `update_status` deklarieren, in `updater` + `backend` mounten
- `docker/updater/update.sh` — status.json nach Deploy schreiben, trigger-Datei in Polling-Schleife prüfen
- `backend/app/config.py` — `github_token` + `github_repo` Settings ergänzen
- `backend/app/api/routes/admin.py` — zwei neue Endpoints: GET update-status, POST trigger-update
- `backend/app/main.py` — kein neuer Router nötig (Endpoints landen in admin.py)
- `frontend/src/lib/api/index.ts` — `UpdateStatus`-Interface + zwei neue adminApi-Methoden
- `frontend/src/routes/admin/+page.svelte` — Tab "System" + Status-Card + Trigger-Button
- `backend/tests/test_admin.py` — Tests für die zwei neuen Endpoints

---

## Task 1: Shared Volume + docker-compose.yml

**Files:**
- Modify: `docker-compose.yml`

- [ ] **Step 1: Volume im backend-Service mounten**

In `docker-compose.yml`, im `backend`-Service, die `volumes`-Liste um einen Eintrag erweitern:

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
      - update_status:/update_status
```

- [ ] **Step 2: Volume im updater-Service mounten**

Im `updater`-Service, `volumes` erweitern:

```yaml
  updater:
    build: ./docker/updater
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock
      - .:/workspace
      - update_status:/update_status
    environment:
      - GITHUB_TOKEN=${GITHUB_TOKEN:-}
    restart: unless-stopped
```

- [ ] **Step 3: Volume in der volumes-Sektion deklarieren**

Am Ende der `volumes:`-Sektion in `docker-compose.yml`:

```yaml
volumes:
  postgres_data:
  osm_data:
  gh_graph:
  caddy_data:
  caddy_config:
  cert_uploads:
  logo_uploads:
  update_status:
```

- [ ] **Step 4: Compose-Config validieren**

```bash
docker compose config --quiet && echo "compose OK"
```

Expected: `compose OK`

- [ ] **Step 5: Commit**

```bash
git add docker-compose.yml
git commit -m "feat: add update_status shared volume to compose"
```

---

## Task 2: Updater — status.json schreiben + trigger-Polling

**Files:**
- Modify: `docker/updater/update.sh`

- [ ] **Step 1: status.json nach erfolgreichem Deploy schreiben**

Direkt nach `log "Updated to ${DEPLOYED:0:7}"` die `status.json` in `/update_status/` schreiben. Ersetze den `if`-Block im Deploy-Abschnitt:

```bash
  if [ "${DEPLOYED}" != "${REMOTE}" ]; then
    log "Update detected: ${DEPLOYED:0:7} → ${REMOTE:0:7}"
    SERVICES=$(docker compose "${COMPOSE_FILES[@]}" config --services 2>/dev/null | grep -v '^updater$' | tr '\n' ' ')
    if git -C "${REPO_DIR}" reset --hard origin/main && \
       git -C "${REPO_DIR}" clean -fd && \
       docker compose "${COMPOSE_FILES[@]}" up -d --build ${SERVICES}; then
      DEPLOYED=$(git -C "${REPO_DIR}" rev-parse HEAD)
      log "Updated to ${DEPLOYED:0:7}"
      mkdir -p /update_status
      printf '{"deployed_sha":"%s","deployed_at":"%s"}\n' \
        "${DEPLOYED}" \
        "$(date -u '+%Y-%m-%dT%H:%M:%SZ')" \
        > /update_status/status.json
    else
      log "Deploy failed — will retry in ${INTERVAL}s"
    fi
  fi
```

- [ ] **Step 2: Trigger-Datei in der Hauptschleife prüfen (vor dem sleep)**

Direkt vor `sleep "${INTERVAL}"` am Ende der while-Schleife einfügen:

```bash
  if [ -f /update_status/trigger ]; then
    log "Manual trigger detected"
    rm -f /update_status/trigger
    DEPLOYED=""
  fi
```

Durch `DEPLOYED=""` wird die SHA-Vergleichs-Bedingung im nächsten Schleifendurchlauf immer wahr — egal ob es tatsächlich eine neue Version gibt. Das erzwingt ein Deploy.

- [ ] **Step 3: Vollständiges update.sh zur Referenz**

Die komplette Datei nach beiden Änderungen sieht so aus:

```bash
#!/bin/bash
set -euo pipefail

REPO_DIR=/workspace
REPO_URL="https://github.com/RettTechSolutions/MarschPlan.git"
INTERVAL="${UPDATE_INTERVAL:-300}"

# Fail fast if token not provided
: "${GITHUB_TOKEN:?GITHUB_TOKEN must be set}"

# Store credentials securely in netrc — never exposed in URL or process list
printf 'machine github.com\nlogin x-access-token\npassword %s\n' "${GITHUB_TOKEN}" > ~/.netrc
chmod 600 ~/.netrc

# Allow git to operate on the mounted workspace (owned by host user, not container root)
git config --global --add safe.directory "${REPO_DIR}"

COMPOSE_PROJECT="${COMPOSE_PROJECT_NAME:-marschplan}"
COMPOSE_FILES=(-p "${COMPOSE_PROJECT}" -f "${REPO_DIR}/docker-compose.yml")
[ -f "${REPO_DIR}/docker-compose.override.yml" ] && COMPOSE_FILES+=(-f "${REPO_DIR}/docker-compose.override.yml")

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*"; }

# First start: clone if no git repo present
if [ ! -d "${REPO_DIR}/.git" ]; then
  log "No repo found, cloning..."
  git clone "${REPO_URL}" "${REPO_DIR}"
  log "Cloned to ${REPO_DIR}"
fi

# Keep remote URL current (no token in URL — auth is via ~/.netrc)
git -C "${REPO_DIR}" remote set-url origin "${REPO_URL}"

# Track last successfully deployed SHA separately from HEAD
# so a failed build is retried next iteration
DEPLOYED=$(git -C "${REPO_DIR}" rev-parse HEAD)

log "Updater started. Polling every ${INTERVAL}s."

while true; do
  if ! git -C "${REPO_DIR}" fetch origin main --quiet 2>&1; then
    log "fetch failed, retrying in ${INTERVAL}s"
    sleep "${INTERVAL}"
    continue
  fi

  REMOTE=$(git -C "${REPO_DIR}" rev-parse origin/main)

  if [ "${DEPLOYED}" != "${REMOTE}" ]; then
    log "Update detected: ${DEPLOYED:0:7} → ${REMOTE:0:7}"
    SERVICES=$(docker compose "${COMPOSE_FILES[@]}" config --services 2>/dev/null | grep -v '^updater$' | tr '\n' ' ')
    if git -C "${REPO_DIR}" reset --hard origin/main && \
       git -C "${REPO_DIR}" clean -fd && \
       docker compose "${COMPOSE_FILES[@]}" up -d --build ${SERVICES}; then
      DEPLOYED=$(git -C "${REPO_DIR}" rev-parse HEAD)
      log "Updated to ${DEPLOYED:0:7}"
      mkdir -p /update_status
      printf '{"deployed_sha":"%s","deployed_at":"%s"}\n' \
        "${DEPLOYED}" \
        "$(date -u '+%Y-%m-%dT%H:%M:%SZ')" \
        > /update_status/status.json
    else
      log "Deploy failed — will retry in ${INTERVAL}s"
    fi
  fi

  if [ -f /update_status/trigger ]; then
    log "Manual trigger detected"
    rm -f /update_status/trigger
    DEPLOYED=""
  fi

  sleep "${INTERVAL}"
done
```

- [ ] **Step 4: Syntax prüfen**

```bash
bash -n docker/updater/update.sh && echo "syntax OK"
```

Expected: `syntax OK`

- [ ] **Step 5: Commit**

```bash
git add docker/updater/update.sh
git commit -m "feat: updater writes status.json and polls for manual trigger"
```

---

## Task 3: Backend — Settings + Endpoints

**Files:**
- Modify: `backend/app/config.py`
- Modify: `backend/app/api/routes/admin.py`

- [ ] **Step 1: Settings erweitern**

`backend/app/config.py` — zwei optionale Felder ergänzen:

```python
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str = "postgresql+asyncpg://marschplan:marschplan@localhost:5432/marschplan"
    jwt_secret: str = "changeme-in-production"
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 60 * 24 * 7  # 7 days
    graphhopper_url: str = "http://localhost:8989"
    caddy_admin_url: str = "http://caddy:2019"
    github_token: str = ""
    github_repo: str = "RettTechSolutions/MarschPlan"

    class Config:
        env_file = ".env"


settings = Settings()
```

- [ ] **Step 2: Failing-Tests schreiben**

`backend/tests/test_admin.py` ersetzen:

```python
import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch, mock_open
from httpx import AsyncClient, ASGITransport, Response
from app.main import app


def _superadmin():
    user = MagicMock()
    user.is_superadmin = True
    return user


def _make_app_with_superadmin():
    from app.api.deps import require_superadmin
    app.dependency_overrides[require_superadmin] = lambda: _superadmin()
    return app


def _mock_github_client(sha: str):
    mock_resp = MagicMock()
    mock_resp.is_success = True
    mock_resp.json.return_value = [{"sha": sha}]
    inner = MagicMock()
    inner.get = AsyncMock(return_value=mock_resp)
    ctx = MagicMock()
    ctx.__aenter__ = AsyncMock(return_value=inner)
    ctx.__aexit__ = AsyncMock(return_value=False)
    return ctx


@pytest.mark.asyncio
async def test_get_update_status_no_status_file():
    _make_app_with_superadmin()
    with patch("builtins.open", side_effect=FileNotFoundError), \
         patch("app.api.routes.admin.httpx.AsyncClient", return_value=_mock_github_client("abc1234567890")):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            r = await client.get("/api/admin/update-status")
    assert r.status_code == 200
    data = r.json()
    assert data["deployed_sha"] is None
    assert data["remote_sha"] == "abc1234"
    assert data["update_available"] is False
    assert data["github_reachable"] is True
    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_get_update_status_update_available():
    _make_app_with_superadmin()
    status_content = json.dumps({"deployed_sha": "aaa1111", "deployed_at": "2026-05-18T10:00:00Z"})
    with patch("builtins.open", mock_open(read_data=status_content)), \
         patch("app.api.routes.admin.httpx.AsyncClient", return_value=_mock_github_client("bbb2222abcdef")):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            r = await client.get("/api/admin/update-status")
    assert r.status_code == 200
    data = r.json()
    assert data["deployed_sha"] == "aaa1111"
    assert data["remote_sha"] == "bbb2222"
    assert data["update_available"] is True
    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_get_update_status_github_unreachable():
    _make_app_with_superadmin()
    import httpx as _httpx
    inner = MagicMock()
    inner.get = AsyncMock(side_effect=_httpx.ConnectError("unreachable"))
    ctx = MagicMock()
    ctx.__aenter__ = AsyncMock(return_value=inner)
    ctx.__aexit__ = AsyncMock(return_value=False)
    with patch("builtins.open", side_effect=FileNotFoundError), \
         patch("app.api.routes.admin.httpx.AsyncClient", return_value=ctx):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            r = await client.get("/api/admin/update-status")
    assert r.status_code == 200
    data = r.json()
    assert data["github_reachable"] is False
    assert data["remote_sha"] is None
    assert data["update_available"] is False
    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_trigger_update_creates_file():
    _make_app_with_superadmin()
    m = mock_open()
    with patch("builtins.open", m), \
         patch("os.path.exists", return_value=False), \
         patch("os.makedirs"):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            r = await client.post("/api/admin/trigger-update")
    assert r.status_code == 202
    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_trigger_update_409_when_already_triggered():
    _make_app_with_superadmin()
    with patch("os.path.exists", return_value=True):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            r = await client.post("/api/admin/trigger-update")
    assert r.status_code == 409
    app.dependency_overrides.clear()
```

- [ ] **Step 3: Tests ausführen — müssen FEHLSCHLAGEN**

```bash
cd backend && python -m pytest tests/test_admin.py -v
```

Expected: Fehler wegen fehlender Endpoints (ImportError oder 404/405).

- [ ] **Step 4: Endpoints implementieren**

In `backend/app/api/routes/admin.py` — am Anfang die neuen Imports ergänzen und zwei neue Router-Funktionen hinzufügen. Die bestehenden User-Endpoints bleiben unverändert.

Imports-Block am Anfang der Datei ersetzen durch:

```python
import json
import os
import uuid
from datetime import datetime, timezone

import bcrypt
import httpx
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.deps import get_db, require_superadmin
from app.config import settings
from app.models.organization import UserOrganization
from app.models.user import User
from app.schemas.user import AdminUserCreate, AdminUserResponse, AdminUserUpdate, AdminUserOrgInfo

router = APIRouter(prefix="/admin", tags=["admin"])

STATUS_FILE = "/update_status/status.json"
TRIGGER_FILE = "/update_status/trigger"
```

Dann am Ende der Datei (nach dem letzten bestehenden Endpoint) die zwei neuen Endpoints anhängen:

```python
@router.get("/update-status")
async def get_update_status(
    _: User = Depends(require_superadmin),
):
    deployed_sha = None
    deployed_at = None
    try:
        with open(STATUS_FILE) as f:
            data = json.load(f)
            deployed_sha = data.get("deployed_sha")
            deployed_at = data.get("deployed_at")
    except (FileNotFoundError, json.JSONDecodeError):
        pass

    remote_sha = None
    github_reachable = False
    try:
        headers = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}
        if settings.github_token:
            headers["Authorization"] = f"Bearer {settings.github_token}"
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(
                f"https://api.github.com/repos/{settings.github_repo}/commits/main",
                headers=headers,
            )
        if resp.is_success:
            commits = resp.json()
            if commits and isinstance(commits, list):
                remote_sha = commits[0]["sha"][:7]
            github_reachable = True
    except Exception:
        pass

    update_available = bool(
        deployed_sha and remote_sha and deployed_sha[:7] != remote_sha[:7]
    )

    return {
        "deployed_sha": deployed_sha,
        "deployed_at": deployed_at,
        "remote_sha": remote_sha,
        "update_available": update_available,
        "github_reachable": github_reachable,
    }


@router.post("/trigger-update", status_code=202)
async def trigger_update(
    _: User = Depends(require_superadmin),
):
    if os.path.exists(TRIGGER_FILE):
        raise HTTPException(409, "Update already triggered")
    os.makedirs(os.path.dirname(TRIGGER_FILE), exist_ok=True)
    with open(TRIGGER_FILE, "w") as f:
        f.write(datetime.now(timezone.utc).isoformat())
    return {"status": "triggered"}
```

- [ ] **Step 5: Tests ausführen — müssen BESTEHEN**

```bash
cd backend && python -m pytest tests/test_admin.py -v
```

Expected: 5 Tests PASS.

- [ ] **Step 6: Alle Backend-Tests ausführen**

```bash
cd backend && python -m pytest -v
```

Expected: Alle bestehenden Tests weiterhin PASS.

- [ ] **Step 7: Commit**

```bash
git add backend/app/config.py backend/app/api/routes/admin.py backend/tests/test_admin.py
git commit -m "feat: add update-status and trigger-update admin endpoints"
```

---

## Task 4: Frontend — API-Client + System-Tab

**Files:**
- Modify: `frontend/src/lib/api/index.ts`
- Modify: `frontend/src/routes/admin/+page.svelte`

- [ ] **Step 1: UpdateStatus-Interface und adminApi-Methoden ergänzen**

In `frontend/src/lib/api/index.ts`, direkt nach dem `adminApi`-Objekt (nach Zeile 281 — nach der schließenden `};`) einfügen:

```typescript
export interface UpdateStatus {
    deployed_sha: string | null;
    deployed_at: string | null;
    remote_sha: string | null;
    update_available: boolean;
    github_reachable: boolean;
}
```

Das bestehende `adminApi`-Objekt um zwei Methoden erweitern:

```typescript
export const adminApi = {
    listUsers: () => api.get<AdminUser[]>('/api/admin/users'),
    createUser: (data: AdminUserCreate) => api.post<AdminUser>('/api/admin/users', data),
    updateUser: (id: string, data: AdminUserUpdate) => api.patch<AdminUser>(`/api/admin/users/${id}`, data),
    deleteUser: (id: string) => api.delete(`/api/admin/users/${id}`),
    getUpdateStatus: () => api.get<UpdateStatus>('/api/admin/update-status'),
    triggerUpdate: () => api.post<{ status: string }>('/api/admin/trigger-update', {}),
};
```

- [ ] **Step 2: Tab "System" — State-Variablen ergänzen**

In `frontend/src/routes/admin/+page.svelte`, die `activeTab`-Deklaration (Zeile 12) erweitern:

```typescript
let activeTab = $state<'benutzer' | 'leitstellen' | 'branding' | 'system'>('benutzer');
```

Dann direkt darunter (nach den bestehenden State-Variablen, vor `onMount`) die Update-State-Variablen einfügen:

```typescript
// ── System / Update ──────────────────────────────────────────────────────────
let updateStatus = $state<import('$lib/api').UpdateStatus | null>(null);
let updateLoading = $state(false);
let updateTriggering = $state(false);
let updateError = $state('');
let updateSuccess = $state('');

async function loadUpdateStatus() {
    updateLoading = true;
    updateError = '';
    try {
        updateStatus = await adminApi.getUpdateStatus();
    } catch {
        updateError = 'Status konnte nicht geladen werden';
    } finally {
        updateLoading = false;
    }
}

async function triggerUpdate() {
    updateError = '';
    updateSuccess = '';
    updateTriggering = true;
    try {
        await adminApi.triggerUpdate();
    } catch (e: unknown) {
        const msg = e instanceof Error ? e.message : 'Fehler beim Trigger';
        if (msg.includes('409') || msg.includes('already')) {
            updateError = 'Update läuft bereits';
        } else {
            updateError = msg;
        }
        updateTriggering = false;
        return;
    }

    // Poll every 3s until deployed_sha changes or 3min timeout
    const startSha = updateStatus?.deployed_sha ?? null;
    const deadline = Date.now() + 3 * 60 * 1000;
    const poll = async () => {
        if (Date.now() > deadline) {
            updateTriggering = false;
            updateError = 'Timeout — bitte Server-Logs prüfen';
            return;
        }
        try {
            const fresh = await adminApi.getUpdateStatus();
            updateStatus = fresh;
            if (!fresh.update_available && fresh.deployed_sha !== startSha) {
                updateTriggering = false;
                updateSuccess = `Aktualisiert auf ${fresh.deployed_sha?.slice(0, 7) ?? '?'}`;
                return;
            }
        } catch { /* ignore transient errors during polling */ }
        setTimeout(poll, 3000);
    };
    setTimeout(poll, 3000);
}
```

- [ ] **Step 3: Tab-Button + Tab-Inhalt hinzufügen**

Im Template-Teil, die Tab-Bar erweitern. Den bestehenden Branding-Tab-Button:

```svelte
        <button class="tab" class:active={activeTab === 'branding'} onclick={() => activeTab = 'branding'}>
            Branding
        </button>
```

ersetzen durch:

```svelte
        <button class="tab" class:active={activeTab === 'branding'} onclick={() => activeTab = 'branding'}>
            Branding
        </button>
        <button class="tab" class:active={activeTab === 'system'} onclick={() => { activeTab = 'system'; loadUpdateStatus(); }}>
            System
        </button>
```

Dann nach dem letzten `{/if}` (nach dem Branding-Block, vor dem schließenden `</main>`) den System-Tab-Block einfügen:

```svelte
    {#if activeTab === 'system'}
        <div class="section">
            <div class="section-header">
                <strong>Software-Update</strong>
                {#if !updateTriggering}
                    <button class="btn-small" onclick={loadUpdateStatus}>↺ Aktualisieren</button>
                {/if}
            </div>

            {#if updateError}
                <div class="error-bar">{updateError} <button onclick={() => updateError = ''}>✕</button></div>
            {/if}
            {#if updateSuccess}
                <div class="success-bar">{updateSuccess}</div>
            {/if}

            {#if updateLoading}
                <p class="hint">Lade Status…</p>
            {:else if updateStatus}
                <div class="update-grid">
                    <div class="update-row">
                        <span class="update-label">Installiert</span>
                        <code>{updateStatus.deployed_sha?.slice(0, 7) ?? '—'}</code>
                        {#if updateStatus.deployed_at}
                            <span class="hint">{new Date(updateStatus.deployed_at).toLocaleString('de-DE')}</span>
                        {/if}
                    </div>
                    <div class="update-row">
                        <span class="update-label">GitHub (main)</span>
                        {#if updateStatus.github_reachable}
                            <code>{updateStatus.remote_sha?.slice(0, 7) ?? '—'}</code>
                        {:else}
                            <span class="hint">nicht erreichbar</span>
                        {/if}
                    </div>
                    <div class="update-row">
                        <span class="update-label">Status</span>
                        {#if !updateStatus.github_reachable}
                            <span class="badge badge-warn">GitHub nicht erreichbar</span>
                        {:else if updateStatus.update_available}
                            <span class="badge badge-update">Update verfügbar ↑</span>
                        {:else}
                            <span class="badge badge-ok">Aktuell ✓</span>
                        {/if}
                    </div>
                </div>

                <div style="margin-top: 1rem;">
                    {#if updateTriggering}
                        <button class="btn-primary" disabled>
                            <span class="spinner"></span> Update wird durchgeführt…
                        </button>
                    {:else}
                        <button
                            class="btn-primary"
                            disabled={!updateStatus.update_available || !updateStatus.github_reachable}
                            onclick={triggerUpdate}
                        >
                            Jetzt updaten
                        </button>
                    {/if}
                </div>
            {:else}
                <p class="hint">Status nicht verfügbar</p>
            {/if}
        </div>
    {/if}
```

- [ ] **Step 4: CSS für Update-Tab ergänzen**

Am Ende des `<style>`-Blocks in `+page.svelte` (vor `</style>`) ergänzen:

```css
    .update-grid { display: flex; flex-direction: column; gap: .6rem; }
    .update-row { display: flex; align-items: center; gap: .75rem; font-size: var(--text-sm); }
    .update-label { width: 130px; color: var(--text-muted); font-size: var(--text-xs); text-transform: uppercase; letter-spacing: .04em; flex-shrink: 0; }
    .badge { display: inline-block; padding: .15rem .5rem; border-radius: 3px; font-size: var(--text-xs); font-weight: 600; }
    .badge-ok { background: rgba(107,127,77,.2); color: #a8c070; border: 1px solid rgba(107,127,77,.4); }
    .badge-update { background: rgba(210,120,30,.2); color: #e8a050; border: 1px solid rgba(210,120,30,.4); }
    .badge-warn { background: rgba(180,60,40,.15); color: var(--color-primary); border: 1px solid rgba(180,60,40,.3); }
    .spinner { display: inline-block; width: 12px; height: 12px; border: 2px solid rgba(255,255,255,.3); border-top-color: white; border-radius: 50%; animation: spin .7s linear infinite; vertical-align: middle; margin-right: .3rem; }
    @keyframes spin { to { transform: rotate(360deg); } }
```

- [ ] **Step 5: TypeScript-Build prüfen**

```bash
cd frontend && npm run check 2>&1 | tail -20
```

Expected: Keine Typ-Fehler. Etwaige Warnungen zu ungenutzten Variablen sind OK.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/lib/api/index.ts frontend/src/routes/admin/+page.svelte
git commit -m "feat: add System tab with update status and manual trigger to admin UI"
```

---

## Task 5: Deploy + End-to-End-Verifikation

**Files:** keine neuen — nur Deployment und Smoke-Test

- [ ] **Step 1: Push zu GitHub**

```bash
git push origin main
```

Expected: alle Commits gepusht, kein Fehler.

- [ ] **Step 2: Server deployen**

```bash
rsync -az docker/updater/update.sh s-lx04-docker:~/MarschPlan/docker/updater/update.sh
ssh s-lx04-docker "cd ~/MarschPlan && docker compose build --no-cache updater && docker compose up -d"
```

Expected: Alle Container starten, kein Fehler.

- [ ] **Step 3: Updater-Status prüfen**

```bash
ssh s-lx04-docker "docker logs --tail=5 marschplan-updater-1"
```

Expected: Letzte Zeile enthält `Updater started. Polling every 300s.` oder `Updated to <sha>`.

- [ ] **Step 4: Backend-Endpoint direkt testen**

```bash
ssh s-lx04-docker "curl -s -o /dev/null -w '%{http_code}' http://localhost:8000/api/admin/update-status"
```

Expected: `401` (nicht eingeloggt — korrekt, Superadmin-Guard greift).

- [ ] **Step 5: Im Browser testen**

1. `https://192.168.178.18/admin` aufrufen (als Superadmin einloggen)
2. Tab "System" anklicken
3. Status-Card prüft: installierter SHA, GitHub-SHA, Badge korrekt
4. Falls Update verfügbar: "Jetzt updaten" klicken, Spinner beobachten, Erfolg-Meldung abwarten

- [ ] **Step 6: status.json manuell prüfen**

```bash
ssh s-lx04-docker "docker exec marschplan-updater-1 cat /update_status/status.json"
```

Expected: JSON mit `deployed_sha` und `deployed_at`.
