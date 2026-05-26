# Demo-Modus Banner Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Show a persistent orange banner to all logged-in users when ConvoyPlan runs without a valid license.

**Architecture:** New public `GET /api/license/mode` backend endpoint returns `{"demo_mode": bool}` without auth. `+layout.svelte` fetches it on mount and renders a sticky top banner when `demo_mode` is true.

**Tech Stack:** FastAPI (Python), SvelteKit 5, httpx AsyncClient for backend tests.

---

## File Map

| File | Action | What changes |
|------|--------|-------------|
| `backend/app/api/routes/license.py` | Modify | Add `GET /license/mode` endpoint |
| `backend/tests/test_license.py` | Modify | Add HTTP test for the new endpoint |
| `frontend/src/routes/+layout.svelte` | Modify | Add demo mode fetch + sticky banner |

---

## Task 1: Backend — `GET /api/license/mode` endpoint

**Files:**
- Modify: `backend/app/api/routes/license.py`
- Modify: `backend/tests/test_license.py`

- [ ] **Step 1: Write the failing test**

Append to `backend/tests/test_license.py`:

```python
# ── HTTP endpoint tests ──────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_license_mode_endpoint_demo_mode():
    """GET /api/license/mode returns demo_mode=true when no key is stored."""
    from httpx import AsyncClient, ASGITransport
    from app.main import app
    from unittest.mock import patch, AsyncMock

    with patch("app.api.routes.license.get_saved_license_key", new=AsyncMock(return_value="")), \
         patch("app.api.routes.license.get_or_create_instance_id", new=AsyncMock(return_value="test-id")):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            r = await client.get("/api/license/mode")

    assert r.status_code == 200
    data = r.json()
    assert "demo_mode" in data
    assert data["demo_mode"] is True


@pytest.mark.asyncio
async def test_license_mode_endpoint_licensed(monkeypatch):
    """GET /api/license/mode returns demo_mode=false when a valid key is stored."""
    import base64
    import json
    from datetime import date, timedelta
    from httpx import AsyncClient, ASGITransport
    from app.main import app
    from unittest.mock import patch, AsyncMock
    import app.services.license as lic_mod
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

    priv = Ed25519PrivateKey.generate()
    pub_b64 = base64.b64encode(
        priv.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
    ).decode()
    monkeypatch.setattr(lic_mod, "_PUBLIC_KEY_B64", pub_b64)

    payload = {
        "expires": (date.today() + timedelta(days=365)).isoformat(),
        "instance_id": "",
    }
    payload_bytes = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()
    sig = priv.sign(payload_bytes)
    p64 = base64.urlsafe_b64encode(payload_bytes).decode().rstrip("=")
    s64 = base64.urlsafe_b64encode(sig).decode().rstrip("=")
    valid_key = f"{p64}.{s64}"

    with patch("app.api.routes.license.get_saved_license_key", new=AsyncMock(return_value=valid_key)), \
         patch("app.api.routes.license.get_or_create_instance_id", new=AsyncMock(return_value="")):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            r = await client.get("/api/license/mode")

    assert r.status_code == 200
    assert r.json()["demo_mode"] is False
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd backend
pytest tests/test_license.py::test_license_mode_endpoint_demo_mode tests/test_license.py::test_license_mode_endpoint_licensed -v
```

Expected: both FAIL with `404 Not Found` or similar (endpoint doesn't exist yet).

- [ ] **Step 3: Implement the endpoint**

In `backend/app/api/routes/license.py`, append after the `activate_license` function (before the last line):

```python
@router.get("/mode")
async def license_mode(db: AsyncSession = Depends(get_db)):
    """Public endpoint — no auth required.

    Returns only {demo_mode: bool} so any logged-in frontend client can show
    a banner without exposing instance IDs or license details.
    """
    license_key = settings.license_key
    if not license_key:
        license_key = await get_saved_license_key(db)
    instance_id = await get_or_create_instance_id(db)
    info = validate_license(license_key, instance_id)
    return {"demo_mode": not info.valid}
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd backend
pytest tests/test_license.py -v
```

Expected: all tests in `test_license.py` PASS, including the two new ones.

- [ ] **Step 5: Commit**

```bash
git add backend/app/api/routes/license.py backend/tests/test_license.py
git commit -m "feat(license): add public GET /api/license/mode endpoint"
```

---

## Task 2: Frontend — sticky demo-mode banner in layout

**Files:**
- Modify: `frontend/src/routes/+layout.svelte`

- [ ] **Step 1: Add state variable and fetch logic**

In `frontend/src/routes/+layout.svelte`, add `demoMode` state and the fetch call.

Replace the entire `<script>` block with:

```svelte
<script lang="ts">
	import { onMount } from 'svelte';
	import { goto } from '$app/navigation';
	import { page } from '$app/stores';
	import { auth } from '$lib/stores/auth';
	import { brandingStore, applyBranding, type Branding } from '$lib/stores/branding';
	import { themeStore } from '$lib/stores/theme';

	let { children } = $props();

	const PUBLIC_ROUTES = ['/login', '/share', '/setup'];
	let setupChecked = $state(false);
	let demoMode = $state(false);

	onMount(async () => {
		auth.init();
		themeStore.init();

		// Raw fetch (not brandingApi) — GET /api/branding is public and needs no auth token
		try {
			const resp = await fetch('/api/branding');
			if (resp.ok) {
				const data = await resp.json() as Branding;
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

		// Fetch demo mode status — public endpoint, only meaningful when logged in
		if ($auth.token && !PUBLIC_ROUTES.some(r => $page.url.pathname.startsWith(r))) {
			try {
				const resp = await fetch('/api/license/mode');
				if (resp.ok) {
					const data = await resp.json();
					demoMode = data.demo_mode === true;
				}
			} catch {
				// Silently ignore — demo mode banner is non-critical
			}
		}
	});

	$effect(() => {
		if (!setupChecked) return;
		const isPublic = PUBLIC_ROUTES.some((r) => $page.url.pathname.startsWith(r));
		if (!isPublic && !$auth.token && typeof window !== 'undefined') {
			goto('/login');
		}
	});
</script>
```

- [ ] **Step 2: Add banner HTML and CSS**

Replace the `<svelte:head>...{@render children()}<footer...` block with:

```svelte
<svelte:head>
	<title>{$brandingStore.app_name}</title>
	<link rel="icon" type="image/png" href={$themeStore === 'light' ? '/logo/dark/Logo_Favicon.png' : '/logo/light/Logo_Favicon.png'} />
</svelte:head>

{#if demoMode}
	<div class="demo-banner" role="alert">
		<span>⚠ Demo-Modus — keine gültige Lizenz. Schreiboperationen sind gesperrt.</span>
		{#if $auth.is_superadmin}
			<a href="/admin">Lizenz aktivieren →</a>
		{/if}
	</div>
{/if}

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

	.demo-banner {
		position: sticky;
		top: 0;
		z-index: 1000;
		background: #f59e0b;
		color: #1c1917;
		padding: 0.5rem 1.25rem;
		display: flex;
		justify-content: center;
		align-items: center;
		gap: 1.25rem;
		font-size: 0.875rem;
		font-weight: 500;
		text-align: center;
	}

	.demo-banner a {
		color: #1c1917;
		text-decoration: underline;
		font-weight: 700;
		white-space: nowrap;
	}
</style>
```

- [ ] **Step 3: Run svelte-check to verify no type errors**

```bash
cd frontend
npx svelte-check --tsconfig ./tsconfig.json 2>&1 | grep -E "Error|Warning" | head -20
```

Expected: no errors related to `+layout.svelte`.

- [ ] **Step 4: Manual smoke test**

Start the backend without a license key configured and open the app:

```bash
cd backend
DATABASE_URL=postgresql+asyncpg://convoyplan:convoyplan@localhost:5432/convoyplan \
JWT_SECRET=test python -m uvicorn app.main:app --port 8000
```

1. Log in as any user → orange banner „Demo-Modus" should appear at the top
2. Log in as superadmin → banner shows + „Lizenz aktivieren →" link is visible
3. Enter a valid license key in Admin → reload → banner is gone

- [ ] **Step 5: Commit**

```bash
git add frontend/src/routes/+layout.svelte
git commit -m "feat(frontend): show sticky demo-mode banner for all logged-in users"
```

---

## Task 3: Push and deploy

- [ ] **Step 1: Push to main**

```bash
git push origin main
```

- [ ] **Step 2: Verify CI passes**

```bash
gh run list --limit 3
```

Wait for the `CI` run on `main` to show `completed success`.

- [ ] **Step 3: Deploy on VPS**

```bash
# On the VPS:
cd ~/convoyplan && docker compose pull && docker compose up -d
```

The updater container will also pick up the change automatically within 5 minutes.
