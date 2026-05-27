# Responsive Layout Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the `/plan` page responsive: fixed sidebar on desktop, collapsible sidebar as left-side overlay on mobile with a top bar.

**Architecture:** All changes are in a single file (`frontend/src/routes/plan/+page.svelte`). A new `sidebarOpen` Svelte state variable drives a CSS class on the sidebar and the visibility of a backdrop. A CSS media query at ≤768px switches the sidebar from inline-flex to `position: fixed` and shows the top bar.

**Tech Stack:** Svelte 5 (`$state` rune), CSS media queries, no new dependencies.

---

## File Map

| File | Change |
|------|--------|
| `frontend/src/routes/plan/+page.svelte` (lines 1–870) | Add state, 3 new HTML elements, CSS defaults + media query |

---

### Task 1: Add `sidebarOpen` state and three new HTML elements

**Files:**
- Modify: `frontend/src/routes/plan/+page.svelte`

There are no unit-testable logic changes here — verification is visual (see Task 2). Add the markup first so the CSS in Task 2 has something to target.

- [ ] **Step 1: Add `sidebarOpen` state**

  In the `// ── State ──` block around line 22, add one line after `let loading = $state(false);`:

  ```svelte
  let sidebarOpen = $state(false);
  ```

- [ ] **Step 2: Add the top bar inside `.app`**

  The current template starts at line 288:
  ```html
  <div class="app">
  	<!-- ── Sidebar ──────────────────────────────────────────────────── -->
  	<aside class="sidebar">
  ```

  Replace those three lines with:
  ```html
  <div class="app">
  	<!-- ── Mobile top bar (hidden on desktop via CSS) ── -->
  	<div class="topbar">
  		<button class="hamburger" onclick={() => (sidebarOpen = !sidebarOpen)} title="Menü">☰</button>
  		<span class="topbar-name">{selected?.name ?? 'MarschPlan'}</span>
  		<div class="topbar-actions">
  			<button class="btn-map" class:active={$mapMode === 'set-start'} onclick={() => mapMode.set($mapMode === 'set-start' ? 'idle' : 'set-start')}>📍</button>
  			<button class="btn-map" class:active={$mapMode === 'set-end'} onclick={() => mapMode.set($mapMode === 'set-end' ? 'idle' : 'set-end')}>🏁</button>
  			<button class="btn-map" class:active={$mapMode === 'add-waypoint'} onclick={() => mapMode.set($mapMode === 'add-waypoint' ? 'idle' : 'add-waypoint')}>➕</button>
  		</div>
  	</div>

  	<!-- ── Sidebar backdrop (mobile only, shown when sidebar is open) ── -->
  	{#if sidebarOpen}
  		<div class="sidebar-backdrop" onclick={() => (sidebarOpen = false)}></div>
  	{/if}

  	<!-- ── Sidebar ──────────────────────────────────────────────────── -->
  	<aside class="sidebar" class:open={sidebarOpen}>
  ```

- [ ] **Step 3: Add the FAB route button inside `<main>`**

  Find the `<main class="map-area">` block (currently around line 688). It looks like:
  ```html
  <main class="map-area">

  		<!-- V3: Weather widget -->
  ```
  (The exact first child may differ — just find the opening `<main class="map-area">` line.)

  Add the FAB as the **first child** inside `<main>`:
  ```html
  <main class="map-area">
  	<!-- FAB route button shown on mobile only -->
  	<button class="fab-route" onclick={calculateRoute} disabled={loading}>
  		{loading ? 'Berechne…' : '🗺 Route'}
  	</button>
  ```

- [ ] **Step 4: Verify the template renders without errors**

  Run the dev server (or rebuild the Docker image) and open the app in a browser. The page should look identical to before on desktop — the new elements are invisible until the media query activates. No console errors.

  ```bash
  # If running locally:
  cd frontend && npm run dev
  # If running in Docker (baked image):
  docker compose build frontend && docker compose up -d --no-deps frontend
  ```

---

### Task 2: CSS — desktop defaults + mobile media query

**Files:**
- Modify: `frontend/src/routes/plan/+page.svelte` (the `<style>` block, currently lines 743–870)

- [ ] **Step 1: Add desktop defaults after `.map-area` rule**

  Find the `.map-area` CSS rule (around line 817):
  ```css
  .map-area { flex: 1; position: relative; }
  ```

  Add these lines immediately after it:
  ```css
  /* Desktop defaults — these elements exist in DOM but are hidden */
  .topbar { display: none; }
  .sidebar-backdrop { display: none; }
  .fab-route { display: none; }
  ```

- [ ] **Step 2: Add mobile media query at the end of the style block**

  The style block currently ends around line 870 with:
  ```css
  	.wp-name-input::placeholder { color: rgba(255,255,255,.35); }
  	.wizard-wp-list li { ... }
  </style>
  ```

  Add the full media query block just before `</style>`:
  ```css
  	/* ── Mobile layout (≤ 768px) ─────────────────────────────────── */
  	@media (max-width: 768px) {
  		/* Show top bar, push content down */
  		.topbar {
  			display: flex;
  			align-items: center;
  			gap: .5rem;
  			position: fixed;
  			top: 0; left: 0; right: 0;
  			height: 48px;
  			padding: 0 .75rem;
  			background: #1a2744;
  			border-bottom: 1px solid rgba(255,255,255,.1);
  			z-index: 200;
  		}
  		.hamburger {
  			background: rgba(255,255,255,.1);
  			border: none;
  			color: white;
  			border-radius: 6px;
  			width: 34px;
  			height: 34px;
  			font-size: 1.1rem;
  			cursor: pointer;
  			flex-shrink: 0;
  			display: flex;
  			align-items: center;
  			justify-content: center;
  		}
  		.topbar-name {
  			flex: 1;
  			font-size: .9rem;
  			font-weight: 600;
  			color: white;
  			white-space: nowrap;
  			overflow: hidden;
  			text-overflow: ellipsis;
  		}
  		.topbar-actions {
  			display: flex;
  			gap: .3rem;
  		}
  		.topbar-actions .btn-map {
  			padding: .3rem .45rem;
  			font-size: .8rem;
  		}

  		/* Push the flex layout down to clear the fixed top bar */
  		.app {
  			padding-top: 48px;
  		}

  		/* Sidebar becomes a fixed overlay from the left */
  		.sidebar {
  			position: fixed;
  			top: 48px;
  			left: 0;
  			bottom: 0;
  			width: 300px;
  			z-index: 300;
  			transform: translateX(-100%);
  			transition: transform .25s ease;
  		}
  		.sidebar.open {
  			transform: translateX(0);
  		}

  		/* Backdrop behind open sidebar */
  		.sidebar-backdrop {
  			display: block;
  			position: fixed;
  			inset: 0;
  			background: rgba(0,0,0,.45);
  			z-index: 299;
  		}

  		/* FAB route button floating over map */
  		.fab-route {
  			display: block;
  			position: fixed;
  			bottom: 1.5rem;
  			right: 1rem;
  			z-index: 100;
  			padding: .6rem 1.1rem;
  			background: #e74c3c;
  			color: white;
  			border: none;
  			border-radius: 8px;
  			font-size: .9rem;
  			font-weight: 600;
  			cursor: pointer;
  			box-shadow: 0 2px 12px rgba(0,0,0,.3);
  		}
  		.fab-route:disabled {
  			opacity: .55;
  			cursor: not-allowed;
  		}
  	}
  ```

- [ ] **Step 3: Visual verification — desktop**

  Open the app on desktop (any browser, window > 768px wide).

  Expected:
  - Layout looks exactly the same as before — sidebar on left, map on right
  - No hamburger button visible
  - No FAB button visible on the map

- [ ] **Step 4: Visual verification — mobile**

  Open browser DevTools → toggle device emulation (or open on phone at `http://192.168.178.67:8080`).

  Expected:
  - Top bar visible with ☰, convoy name, 📍 🏁 ➕ buttons
  - Sidebar NOT visible (hidden behind left edge)
  - Map fills full screen below the top bar
  - Red "🗺 Route" FAB button in bottom-right corner

- [ ] **Step 5: Visual verification — sidebar open**

  Tap/click ☰ hamburger.

  Expected:
  - Sidebar slides in from the left
  - Dark backdrop appears over the map to the right of the sidebar
  - Tapping backdrop closes sidebar (slides out)
  - Tapping ☰ again closes sidebar

- [ ] **Step 6: Rebuild Docker image and verify on phone**

  ```bash
  docker compose build frontend && docker compose up -d --no-deps frontend
  ```

  Open `http://192.168.178.67:8080` on iPhone. Repeat the checks from Steps 3–5.

- [ ] **Step 7: Commit**

  ```bash
  git add frontend/src/routes/plan/+page.svelte
  git commit -m "feat: responsive layout — mobile top bar + collapsible sidebar overlay"
  ```
