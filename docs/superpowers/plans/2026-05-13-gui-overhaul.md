# GUI Overhaul — Modern Design System Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Introduce a CSS design token system (semantic color/typography/spacing vars), a light/dark mode toggle in the plan sidebar, and migrate all hardcoded style values across 6 pages to the new tokens.

**Architecture:** A `data-theme` attribute on `<html>` switches token values. An inline script in `app.html` reads `localStorage` before first paint (FOUC prevention). The plan page sidebar gains a fixed footer with the toggle. All other pages get the correct theme automatically via the same CSS vars.

**Tech Stack:** SvelteKit 5 (runes), CSS custom properties, localStorage

---

## File Map

**Modify only:**
- `frontend/src/app.html` — FOUC script + token CSS (dark + light themes, typography vars, `--sidebar-bg`)
- `frontend/src/routes/+layout.svelte` — read localStorage on mount, apply `data-theme`
- `frontend/src/routes/plan/+page.svelte` — sidebar footer + toggle logic + full CSS token migration
- `frontend/src/routes/admin/+page.svelte` — CSS token migration
- `frontend/src/routes/tracking/[convoy_id]/+page.svelte` — CSS token migration
- `frontend/src/routes/login/+page.svelte` — CSS token migration
- `frontend/src/routes/share/[token]/+page.svelte` — CSS token migration

**Not changed:** backend, branding vars (`--color-*`), MapLibre JS layer constants, setup wizard.

---

## Task 1: Token Foundation — app.html + layout.svelte

**Files:**
- Modify: `frontend/src/app.html`
- Modify: `frontend/src/routes/+layout.svelte`

- [ ] **Step 1: Replace app.html entirely**

Replace `frontend/src/app.html` with:

```html
<!doctype html>
<html lang="en" data-theme="dark">
	<head>
		<meta charset="utf-8" />
		<meta name="viewport" content="width=device-width, initial-scale=1" />
		<script>
			(function() {
				var t = localStorage.getItem('marschplan-theme');
				if (t === 'light' || t === 'dark') document.documentElement.setAttribute('data-theme', t);
			})();
		</script>
		<style>
			*, *::before, *::after { box-sizing: border-box; }
			html, body { margin: 0; padding: 0; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; }

			:root {
				/* Typography scale */
				--text-xs:   .72rem;
				--text-sm:   .82rem;
				--text-base: .92rem;
				--text-lg:   1.05rem;

				/* Sidebar always dark regardless of theme */
				--sidebar-bg: #161f2e;

				/* Branding vars (overridden at runtime by /api/branding) */
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

			[data-theme="dark"] {
				--bg:         #0f1419;
				--surface-1:  #161f2e;
				--surface-2:  #1e2d3d;
				--border:     rgba(255, 255, 255, .1);
				--text-1:     #e8edf2;
				--text-2:     rgba(255, 255, 255, .55);
				--text-muted: rgba(255, 255, 255, .32);
				--shadow:     none;
			}

			[data-theme="light"] {
				--bg:         #f0f2f5;
				--surface-1:  #ffffff;
				--surface-2:  #f8f9fa;
				--border:     #dde1e7;
				--text-1:     #1a2332;
				--text-2:     #4a5568;
				--text-muted: #9aa3b0;
				--shadow:     0 1px 3px rgba(0, 0, 0, .08);
			}
		</style>
		%sveltekit.head%
	</head>
	<body data-sveltekit-preload-data="hover">
		<div style="display: contents">%sveltekit.body%</div>
	</body>
</html>
```

- [ ] **Step 2: Update +layout.svelte to init theme on mount**

In `frontend/src/routes/+layout.svelte`, add theme init inside the existing `onMount`. After `auth.init();` add:

```typescript
// Apply saved theme (backup for SSR hydration — inline script in app.html handles FOUC)
const saved = localStorage.getItem('marschplan-theme');
if (saved === 'light' || saved === 'dark') {
    document.documentElement.setAttribute('data-theme', saved);
}
```

- [ ] **Step 3: Verify no TypeScript errors**

```bash
cd frontend && npx svelte-check --tsconfig tsconfig.json 2>&1 | grep -E "^.*Error" | head -10
```

Expected: no errors.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/app.html frontend/src/routes/+layout.svelte
git commit -m "feat: add design token system and theme foundation (dark/light)"
```

---

## Task 2: Plan Page — Sidebar Redesign + Theme Toggle + Token Migration

**Files:**
- Modify: `frontend/src/routes/plan/+page.svelte`

This is the largest change. The sidebar gets a footer with theme toggle, tabs get a pill-style active state, section headers become uppercase labels, and all hardcoded colors/sizes become tokens.

- [ ] **Step 1: Add theme state + toggleTheme function to script block**

In `frontend/src/routes/plan/+page.svelte`, in the `<script lang="ts">` block, add after the existing `let` declarations at the top of the state section:

```typescript
// Theme toggle
let theme = $state<'dark' | 'light'>(
    (typeof window !== 'undefined' ? localStorage.getItem('marschplan-theme') : null) as 'dark' | 'light' ?? 'dark'
);
function toggleTheme() {
    theme = theme === 'dark' ? 'light' : 'dark';
    document.documentElement.setAttribute('data-theme', theme);
    localStorage.setItem('marschplan-theme', theme);
}
```

- [ ] **Step 2: Add sidebar footer HTML**

In the HTML section, find the closing `</aside>` tag of the sidebar (the `<aside id="sidebar" class="sidebar">` element). Directly before `</aside>`, add:

```html
<div class="sidebar-footer">
    <button class="theme-toggle" onclick={toggleTheme} aria-label="Theme umschalten">
        {theme === 'dark' ? '☾' : '☀'}
        <span>{theme === 'dark' ? 'Dark' : 'Light'}</span>
    </button>
    <span class="app-version">v0.4.0</span>
</div>
```

- [ ] **Step 3: Replace the sidebar CSS block**

In the `<style>` block, find and replace the following CSS rules. Make these exact replacements (search for the old string, replace with new):

**Sidebar background and color:**
```css
/* OLD */
.sidebar { width: 340px; min-width: 280px; background: #0F1B24; color: white; display: flex; flex-direction: column; overflow: hidden; }
```
```css
/* NEW */
.sidebar { width: 340px; min-width: 280px; background: var(--sidebar-bg); color: var(--text-1); display: flex; flex-direction: column; overflow: hidden; }
```

**Sidebar header:**
```css
/* OLD */
.sidebar-header { display: flex; justify-content: space-between; align-items: center; padding: 0.75rem 1rem; border-bottom: 1px solid rgba(255,255,255,.15); background: var(--color-bg); }
```
```css
/* NEW */
.sidebar-header { display: flex; justify-content: space-between; align-items: center; padding: 1rem; border-bottom: 1px solid var(--border); background: var(--sidebar-bg); }
```

**Logout + admin link:**
```css
/* OLD */
.logout-btn { background: none; border: none; color: rgba(0,0,0,.4); cursor: pointer; font-size: 1rem; flex-shrink: 0; }
	.admin-link { font-size: .72rem; color: rgba(0,0,0,.45); text-decoration: none; white-space: nowrap; }
	.admin-link:hover { color: rgba(0,0,0,.7); }
```
```css
/* NEW */
.logout-btn { background: none; border: none; color: var(--text-muted); cursor: pointer; font-size: 1rem; flex-shrink: 0; }
.admin-link { font-size: var(--text-xs); color: var(--text-muted); text-decoration: none; white-space: nowrap; }
.admin-link:hover { color: var(--text-2); }
```

**Convoy selector:**
```css
/* OLD */
.convoy-selector { display: flex; gap: .5rem; padding: .75rem 1rem; border-bottom: 1px solid rgba(255,255,255,.1); }
	.convoy-selector select { flex: 1; padding: .4rem; border-radius: 4px; border: none; background: rgba(255,255,255,.12); color: white; }
```
```css
/* NEW */
.convoy-selector { display: flex; gap: .5rem; padding: .75rem 1rem; border-bottom: 1px solid var(--border); }
.convoy-selector select { flex: 1; padding: .5rem; border-radius: 6px; border: 1px solid var(--border); background: var(--surface-2); color: var(--text-1); font-size: var(--text-sm); }
```

**Tabs — pill style:**
```css
/* OLD */
.tabs { display: flex; overflow-x: auto; scrollbar-width: none; border-bottom: 1px solid rgba(255,255,255,.1); }
	.tabs::-webkit-scrollbar { display: none; }
	.tab { flex: 0 0 auto; padding: .55rem .75rem; background: none; border: none; color: rgba(255,255,255,.55); font-size: .8rem; cursor: pointer; border-bottom: 2px solid transparent; white-space: nowrap; }
	.tab.active { color: white; border-bottom-color: var(--color-primary); font-weight: 600; }
	.tabs-verwaltung { background: rgba(0,0,0,.25); align-items: center; border-bottom: 1px solid rgba(255,255,255,.08); }
	.tabs-verwaltung .tab { font-size: .78rem; padding: .4rem .7rem; }
	.tabs-verwaltung .tab.active { border-bottom-color: rgba(226,61,40,.7); color: rgba(255,255,255,.9); }
	.tabs-section-label { flex-shrink: 0; font-size: .65rem; text-transform: uppercase; letter-spacing: .05em; color: rgba(255,255,255,.3); padding: 0 .6rem 0 .75rem; white-space: nowrap; }
```
```css
/* NEW */
.tabs { display: flex; overflow-x: auto; scrollbar-width: none; padding: .25rem .5rem; gap: .25rem; border-bottom: 1px solid var(--border); }
.tabs::-webkit-scrollbar { display: none; }
.tab { flex: 0 0 auto; padding: .5rem .75rem; background: none; border: none; color: var(--text-2); font-size: var(--text-sm); cursor: pointer; white-space: nowrap; border-radius: 4px; }
.tab.active { color: var(--text-1); background: var(--surface-2); font-weight: 600; }
.tabs-verwaltung { padding: .25rem .5rem; gap: .25rem; border-bottom: 1px solid var(--border); }
.tabs-verwaltung .tab { font-size: var(--text-sm); }
.tabs-verwaltung .tab.active { color: var(--text-1); background: var(--surface-2); }
.tabs-section-label { flex-shrink: 0; font-size: var(--text-xs); text-transform: uppercase; letter-spacing: .05em; color: var(--text-muted); padding: 0 .5rem; white-space: nowrap; align-self: center; }
```

**Tab content + section:**
```css
/* OLD */
.tab-content { flex: 1; overflow-y: auto; padding: .75rem 1rem; }

	.section { margin-bottom: .75rem; }
	.section p { margin: .3rem 0; font-size: .85rem; color: rgba(255,255,255,.85); }
	.section-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: .4rem; font-size: .85rem; }
```
```css
/* NEW */
.tab-content { flex: 1; overflow-y: auto; padding: .75rem 1rem; }

.section { margin-bottom: .75rem; }
.section p { margin: .25rem 0; font-size: var(--text-sm); color: var(--text-2); }
.section-header { display: flex; justify-content: space-between; align-items: center; margin-top: 1.5rem; margin-bottom: .5rem; font-size: var(--text-xs); text-transform: uppercase; letter-spacing: .06em; color: var(--text-muted); }
```

**Buttons:**
```css
/* OLD */
.btn-primary { width: 100%; padding: .6rem; background: var(--color-primary); color: white; border: none; border-radius: 4px; font-weight: 600; cursor: pointer; font-size: .9rem; }
	.btn-primary:disabled { opacity: .5; cursor: not-allowed; }

	.btn-small { padding: .22rem .45rem; background: rgba(255,255,255,.15); border: 1px solid rgba(255,255,255,.25); color: white; border-radius: 4px; font-size: .75rem; cursor: pointer; }
```
```css
/* NEW */
.btn-primary { width: 100%; padding: .5rem 1rem; background: var(--color-primary); color: white; border: none; border-radius: 6px; font-weight: 600; cursor: pointer; font-size: var(--text-sm); }
.btn-primary:disabled { opacity: .5; cursor: not-allowed; }
.btn-primary:hover:not(:disabled) { background: var(--color-primary-hover); }

.btn-small { padding: .25rem .5rem; background: var(--surface-2); border: 1px solid var(--border); color: var(--text-2); border-radius: 4px; font-size: var(--text-xs); cursor: pointer; }
```

**Hint text:**
```css
/* OLD */
.hint { font-size: .78rem; color: rgba(255,255,255,.45); font-style: italic; margin: .25rem 0; }
```
```css
/* NEW */
.hint { font-size: var(--text-xs); color: var(--text-muted); font-style: italic; margin: .25rem 0; }
```

**Map actions:**
```css
/* OLD */
.map-actions { display: flex; flex-wrap: wrap; gap: .4rem; margin-bottom: .5rem; }
	.btn-map { padding: .35rem .55rem; background: rgba(255,255,255,.1); border: 1px solid rgba(255,255,255,.2); color: white; border-radius: 4px; font-size: .78rem; cursor: pointer; }
```
```css
/* NEW */
.map-actions { display: flex; flex-wrap: wrap; gap: .5rem; margin-bottom: .5rem; }
.btn-map { padding: .25rem .5rem; background: var(--surface-2); border: 1px solid var(--border); color: var(--text-2); border-radius: 4px; font-size: var(--text-xs); cursor: pointer; }
```

- [ ] **Step 4: Add sidebar footer CSS**

In the `<style>` block, append before the closing `</style>`:

```css
	.sidebar-footer { flex-shrink: 0; border-top: 1px solid var(--border); padding: .75rem 1rem; display: flex; align-items: center; justify-content: space-between; }
	.theme-toggle { display: flex; align-items: center; gap: .4rem; background: none; border: 1px solid var(--border); border-radius: 6px; color: var(--text-2); font-size: var(--text-sm); padding: .25rem .5rem; cursor: pointer; }
	.theme-toggle:hover { background: var(--surface-2); }
	.app-version { font-size: var(--text-xs); color: var(--text-muted); }
```

- [ ] **Step 5: Check for remaining hardcoded colors in plan page CSS**

```bash
grep -n "rgba(255,255,255\|#0F1B24\|#1a1a1a\|color: white\b" frontend/src/routes/plan/+page.svelte | grep -v "rgba(226,61,40\|STATUS_COLORS\|befehl-modal\|0F1B24.*modal\|'#" | head -20
```

For any remaining `rgba(255,255,255,...)` occurrences in the sidebar CSS that aren't in modals or map overlays, replace with appropriate token:
- `rgba(255,255,255,.85)` → `var(--text-1)`
- `rgba(255,255,255,.55)` → `var(--text-2)`
- `rgba(255,255,255,.4)` or lower → `var(--text-muted)`
- `rgba(255,255,255,.1)` borders → `var(--border)`
- `rgba(255,255,255,.08)` or `.12` backgrounds → `var(--surface-2)`
- `rgba(255,255,255,.15)` or `.2` backgrounds → `var(--surface-2)`

Note: `rgba(255,255,255,...)` values inside `.befehl-modal*` classes are intentional (dark modal header) — leave them.

- [ ] **Step 6: Run svelte-check**

```bash
cd frontend && npx svelte-check --tsconfig tsconfig.json 2>&1 | grep -E "^.*Error" | grep "plan" | head -10
```

Expected: no errors.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/routes/plan/+page.svelte
git commit -m "feat: redesign plan sidebar with tokens and theme toggle"
```

---

## Task 3: Admin Page Token Migration

**Files:**
- Modify: `frontend/src/routes/admin/+page.svelte`

The admin page is a light-on-dark page. In dark mode it keeps its current look; in light mode it gains a proper light background. The branding panel sub-section currently uses hardcoded `#555`/`#ddd` values.

- [ ] **Step 1: Migrate admin page global + main styles**

In `frontend/src/routes/admin/+page.svelte` `<style>` block, make these replacements:

```css
/* OLD */
:global(body) { margin: 0; font-family: system-ui, sans-serif; background: #0F1B24; color: white; }
.admin-page { max-width: 900px; margin: 0 auto; padding: 2rem 1rem; }
.admin-header { display: flex; align-items: center; justify-content: space-between; margin-bottom: 1rem; }
h1 { margin: 0; font-size: 1.4rem; }
.back-link { color: rgba(255,255,255,.6); font-size: .9rem; text-decoration: none; }
.back-link:hover { color: white; }
```
```css
/* NEW */
:global(body) { margin: 0; font-family: system-ui, sans-serif; background: var(--bg); color: var(--text-1); }
.admin-page { max-width: 900px; margin: 0 auto; padding: 2rem 1rem; }
.admin-header { display: flex; align-items: center; justify-content: space-between; margin-bottom: 1rem; }
h1 { margin: 0; font-size: var(--text-lg); }
.back-link { color: var(--text-2); font-size: var(--text-sm); text-decoration: none; }
.back-link:hover { color: var(--text-1); }
```

- [ ] **Step 2: Migrate tab bar**

```css
/* OLD */
.tab-bar { display: flex; gap: 0; border-bottom: 1px solid rgba(255,255,255,.15); margin-bottom: 1.5rem; }
.tab { padding: .5rem 1.2rem; background: none; border: none; cursor: pointer; font-size: .9rem; color: rgba(255,255,255,.5); border-bottom: 2px solid transparent; margin-bottom: -1px; }
.tab.active { color: var(--color-primary); border-bottom-color: var(--color-primary); font-weight: 600; }
```
```css
/* NEW */
.tab-bar { display: flex; gap: .25rem; border-bottom: 1px solid var(--border); margin-bottom: 1.5rem; padding: .25rem .25rem 0; }
.tab { padding: .5rem 1rem; background: none; border: none; cursor: pointer; font-size: var(--text-sm); color: var(--text-2); border-radius: 4px 4px 0 0; margin-bottom: -1px; }
.tab.active { color: var(--color-primary); background: var(--surface-2); font-weight: 600; border-bottom: 2px solid var(--color-primary); }
```

- [ ] **Step 3: Migrate section cards**

```css
/* OLD */
.section { background: rgba(255,255,255,.05); border-radius: 8px; padding: 1rem; margin-bottom: 1rem; }
.section-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: .75rem; }
```
```css
/* NEW */
.section { background: var(--surface-1); border: 1px solid var(--border); border-radius: 8px; padding: 1rem; margin-bottom: 1rem; box-shadow: var(--shadow); }
.section-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: .75rem; font-size: var(--text-sm); font-weight: 500; color: var(--text-1); }
```

- [ ] **Step 4: Migrate user table + create form**

```css
/* OLD */
.create-form { display: flex; flex-direction: column; gap: .5rem; margin-bottom: 1rem; padding: .75rem; background: rgba(255,255,255,.05); border-radius: 6px; }
.create-form input { padding: .4rem .6rem; border-radius: 4px; border: 1px solid rgba(255,255,255,.2); background: rgba(255,255,255,.1); color: white; font-size: .9rem; }
.create-form button { align-self: flex-start; padding: .4rem .9rem; background: #6B7F4D; color: white; border: none; border-radius: 4px; cursor: pointer; font-weight: 600; }
.checkbox-label { display: flex; align-items: center; gap: .4rem; font-size: .88rem; color: rgba(255,255,255,.8); cursor: pointer; }
.user-table { width: 100%; border-collapse: collapse; font-size: .85rem; }
.user-table th { text-align: left; padding: .4rem .5rem; color: rgba(255,255,255,.5); font-weight: 600; border-bottom: 1px solid rgba(255,255,255,.1); }
.user-table td { padding: .4rem .5rem; border-bottom: 1px solid rgba(255,255,255,.07); vertical-align: middle; }
.user-table tr.inactive td { opacity: .45; }
.hint { color: rgba(255,255,255,.4); font-size: .85rem; }
code { background: rgba(255,255,255,.1); padding: .1rem .3rem; border-radius: 3px; font-size: .82rem; font-family: monospace; }
```
```css
/* NEW */
.create-form { display: flex; flex-direction: column; gap: .5rem; margin-bottom: 1rem; padding: .75rem; background: var(--surface-2); border-radius: 6px; border: 1px solid var(--border); }
.create-form input { padding: .5rem .75rem; border-radius: 6px; border: 1px solid var(--border); background: var(--surface-1); color: var(--text-1); font-size: var(--text-sm); }
.create-form input:focus { outline: none; border-color: var(--color-primary); }
.create-form button { align-self: flex-start; padding: .5rem 1rem; background: #6B7F4D; color: white; border: none; border-radius: 6px; cursor: pointer; font-weight: 600; font-size: var(--text-sm); }
.checkbox-label { display: flex; align-items: center; gap: .4rem; font-size: var(--text-sm); color: var(--text-2); cursor: pointer; }
.user-table { width: 100%; border-collapse: collapse; font-size: var(--text-sm); }
.user-table th { text-align: left; padding: .5rem; color: var(--text-muted); font-size: var(--text-xs); text-transform: uppercase; letter-spacing: .04em; border-bottom: 1px solid var(--border); }
.user-table td { padding: .5rem; border-bottom: 1px solid var(--border); vertical-align: middle; color: var(--text-2); }
.user-table tr.inactive td { opacity: .45; }
.hint { color: var(--text-muted); font-size: var(--text-sm); }
code { background: var(--surface-2); padding: .1rem .3rem; border-radius: 3px; font-size: var(--text-xs); font-family: monospace; color: var(--text-1); }
```

- [ ] **Step 5: Migrate branding panel hardcoded colors**

```css
/* OLD */
.branding-panel h3 { margin: 0 0 .6rem; font-size: .9rem; color: #555; }
.bf-label { display: flex; flex-direction: column; gap: .3rem; font-size: .85rem; color: #555; }
.bf-label input[type="text"] { padding: .45rem .7rem; border: 1px solid #ddd; border-radius: 4px; font-size: .9rem; width: 100%; box-sizing: border-box; }
.bf-sublabel { font-size: .82rem; color: #555; margin-bottom: .25rem; display: block; }
.logo-thumb { max-height: 52px; max-width: 160px; border: 1px solid #ddd; border-radius: 4px; }
.color-label { display: flex; flex-direction: column; gap: .25rem; font-size: .8rem; color: #555; }
.color-swatch { width: 32px; height: 32px; padding: 0; border: 1px solid #ccc; border-radius: 4px; cursor: pointer; }
.color-hex { font-size: .75rem; font-family: monospace; color: #666; }
.bf-actions { display: flex; gap: .75rem; justify-content: flex-end; padding-top: .5rem; border-top: 1px solid #eee; margin-top: 1rem; }
```
```css
/* NEW */
.branding-panel h3 { margin: 0 0 .5rem; font-size: var(--text-sm); color: var(--text-2); font-weight: 600; }
.bf-label { display: flex; flex-direction: column; gap: .25rem; font-size: var(--text-sm); color: var(--text-2); }
.bf-label input[type="text"] { padding: .5rem .75rem; border: 1px solid var(--border); border-radius: 6px; font-size: var(--text-base); width: 100%; box-sizing: border-box; background: var(--surface-2); color: var(--text-1); }
.bf-label input[type="text"]:focus { outline: none; border-color: var(--color-primary); }
.bf-sublabel { font-size: var(--text-xs); color: var(--text-muted); margin-bottom: .25rem; display: block; }
.logo-thumb { max-height: 52px; max-width: 160px; border: 1px solid var(--border); border-radius: 4px; }
.color-label { display: flex; flex-direction: column; gap: .25rem; font-size: var(--text-xs); color: var(--text-2); }
.color-swatch { width: 32px; height: 32px; padding: 0; border: 1px solid var(--border); border-radius: 4px; cursor: pointer; }
.color-hex { font-size: var(--text-xs); font-family: monospace; color: var(--text-muted); }
.bf-actions { display: flex; gap: .75rem; justify-content: flex-end; padding-top: .5rem; border-top: 1px solid var(--border); margin-top: 1rem; }
```

- [ ] **Step 6: Migrate modal styles**

```css
/* OLD */
.modal { background: #1a2a35; border: 1px solid rgba(255,255,255,.15); border-radius: 8px; width: 600px; max-width: 95vw; max-height: 90vh; display: flex; flex-direction: column; color: white; }
.modal-header { display: flex; justify-content: space-between; align-items: center; padding: 1rem; border-bottom: 1px solid rgba(255,255,255,.1); }
.modal-footer { padding: .75rem 1rem; border-top: 1px solid rgba(255,255,255,.1); display: flex; justify-content: flex-end; gap: .5rem; }
.ls-form input { padding: .35rem .5rem; border: 1px solid rgba(255,255,255,.2); border-radius: 4px; background: rgba(255,255,255,.08); color: white; font-size: .88rem; font-weight: 400; }
.ls-form input::placeholder { color: rgba(255,255,255,.35); }
.zusatz-row input { flex: 1; padding: .3rem .4rem; border: 1px solid rgba(255,255,255,.2); border-radius: 3px; background: rgba(255,255,255,.08); color: white; font-size: .82rem; }
.poly-map { height: 280px; border-radius: 6px; overflow: hidden; border: 1px solid rgba(255,255,255,.2); }
```
```css
/* NEW */
.modal { background: var(--surface-1); border: 1px solid var(--border); border-radius: 8px; width: 600px; max-width: 95vw; max-height: 90vh; display: flex; flex-direction: column; color: var(--text-1); box-shadow: 0 8px 32px rgba(0,0,0,.3); }
.modal-header { display: flex; justify-content: space-between; align-items: center; padding: 1rem; border-bottom: 1px solid var(--border); }
.modal-footer { padding: .75rem 1rem; border-top: 1px solid var(--border); display: flex; justify-content: flex-end; gap: .5rem; }
.ls-form input { padding: .5rem .75rem; border: 1px solid var(--border); border-radius: 6px; background: var(--surface-2); color: var(--text-1); font-size: var(--text-sm); font-weight: 400; }
.ls-form input::placeholder { color: var(--text-muted); }
.zusatz-row input { flex: 1; padding: .25rem .5rem; border: 1px solid var(--border); border-radius: 4px; background: var(--surface-2); color: var(--text-1); font-size: var(--text-sm); }
.poly-map { height: 280px; border-radius: 6px; overflow: hidden; border: 1px solid var(--border); }
```

- [ ] **Step 7: Run svelte-check**

```bash
cd frontend && npx svelte-check --tsconfig tsconfig.json 2>&1 | grep -E "^.*Error" | grep "admin" | head -10
```

Expected: no errors.

- [ ] **Step 8: Commit**

```bash
git add frontend/src/routes/admin/+page.svelte
git commit -m "feat: admin page token migration"
```

---

## Task 4: Tracking + Login + Share Pages Token Migration

**Files:**
- Modify: `frontend/src/routes/tracking/[convoy_id]/+page.svelte`
- Modify: `frontend/src/routes/login/+page.svelte`
- Modify: `frontend/src/routes/share/[token]/+page.svelte`

- [ ] **Step 1: Migrate tracking page**

In `frontend/src/routes/tracking/[convoy_id]/+page.svelte` `<style>` block, make these replacements:

```css
/* OLD */
.sidebar { width: 320px; min-width: 280px; background: #0F1B24; color: white; display: flex; flex-direction: column; overflow: hidden; }
.sidebar-header { display: flex; justify-content: space-between; align-items: flex-start; padding: 0.75rem 1rem; border-bottom: 1px solid rgba(255,255,255,.15); background: var(--color-bg); }
.convoy-name { font-size: .78rem; color: rgba(255,255,255,.65); margin-top: .3rem; }
.org-name { font-size: .72rem; color: rgba(255,255,255,.4); margin-top: .1rem; }
.ws-indicator { display: flex; align-items: center; gap: .35rem; font-size: .72rem; color: rgba(255,255,255,.5); flex-shrink: 0; }
.position-block { padding: .75rem 1rem; border-bottom: 1px solid rgba(255,255,255,.1); display: flex; flex-direction: column; gap: .4rem; flex-shrink: 0; }
.position-label { font-size: .7rem; text-transform: uppercase; letter-spacing: .06em; color: rgba(255,255,255,.4); }
.position-block select { width: 100%; padding: .4rem; border-radius: 4px; border: none; background: rgba(255,255,255,.12); color: white; font-size: .83rem; }
.tabs { display: flex; overflow-x: auto; scrollbar-width: none; border-bottom: 1px solid rgba(255,255,255,.1); flex-shrink: 0; }
.tab { flex: 0 0 auto; padding: .55rem .75rem; background: none; border: none; color: rgba(255,255,255,.55); font-size: .8rem; cursor: pointer; border-bottom: 2px solid transparent; white-space: nowrap; }
.tab.active { color: white; border-bottom-color: var(--color-primary); font-weight: 600; }
.hint { font-size: .75rem; color: rgba(255,255,255,.45); font-style: italic; margin: 0; line-height: 1.4; }
.vehicle-row { display: flex; align-items: center; justify-content: space-between; padding: .35rem 0; border-bottom: 1px solid rgba(255,255,255,.08); gap: .4rem; }
.vname { font-size: .82rem; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.schedule-table th { color: rgba(255,255,255,.6); font-weight: 600; }
.schedule-table th, .schedule-table td { padding: .3rem .4rem; text-align: left; border-bottom: 1px solid rgba(255,255,255,.1); }
```
```css
/* NEW */
.sidebar { width: 320px; min-width: 280px; background: var(--sidebar-bg); color: var(--text-1); display: flex; flex-direction: column; overflow: hidden; }
.sidebar-header { display: flex; justify-content: space-between; align-items: flex-start; padding: 1rem; border-bottom: 1px solid var(--border); background: var(--sidebar-bg); }
.convoy-name { font-size: var(--text-xs); color: var(--text-2); margin-top: .25rem; }
.org-name { font-size: var(--text-xs); color: var(--text-muted); margin-top: .1rem; }
.ws-indicator { display: flex; align-items: center; gap: .35rem; font-size: var(--text-xs); color: var(--text-muted); flex-shrink: 0; }
.position-block { padding: .75rem 1rem; border-bottom: 1px solid var(--border); display: flex; flex-direction: column; gap: .5rem; flex-shrink: 0; }
.position-label { font-size: var(--text-xs); text-transform: uppercase; letter-spacing: .06em; color: var(--text-muted); }
.position-block select { width: 100%; padding: .5rem; border-radius: 6px; border: 1px solid var(--border); background: var(--surface-2); color: var(--text-1); font-size: var(--text-sm); }
.tabs { display: flex; overflow-x: auto; scrollbar-width: none; border-bottom: 1px solid var(--border); padding: .25rem .5rem; gap: .25rem; flex-shrink: 0; }
.tab { flex: 0 0 auto; padding: .5rem .75rem; background: none; border: none; color: var(--text-2); font-size: var(--text-sm); cursor: pointer; white-space: nowrap; border-radius: 4px; }
.tab.active { color: var(--text-1); background: var(--surface-2); font-weight: 600; }
.hint { font-size: var(--text-xs); color: var(--text-muted); font-style: italic; margin: 0; line-height: 1.4; }
.vehicle-row { display: flex; align-items: center; justify-content: space-between; padding: .35rem 0; border-bottom: 1px solid var(--border); gap: .4rem; }
.vname { font-size: var(--text-sm); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.schedule-table th { color: var(--text-muted); font-size: var(--text-xs); text-transform: uppercase; letter-spacing: .04em; }
.schedule-table th, .schedule-table td { padding: .5rem; text-align: left; border-bottom: 1px solid var(--border); }
```

Also update the mobile topbar:
```css
/* OLD */
.topbar { display: flex; align-items: center; gap: .75rem; padding: .6rem .9rem; background: #0F1B24; color: white; border-bottom: 1px solid rgba(255,255,255,.1); position: fixed; top: 0; left: 0; right: 0; z-index: 50; height: 48px; box-sizing: border-box; }
```
```css
/* NEW */
.topbar { display: flex; align-items: center; gap: .75rem; padding: .75rem 1rem; background: var(--sidebar-bg); color: var(--text-1); border-bottom: 1px solid var(--border); position: fixed; top: 0; left: 0; right: 0; z-index: 50; height: 48px; box-sizing: border-box; }
```

- [ ] **Step 2: Migrate login page**

Replace the entire `<style>` block in `frontend/src/routes/login/+page.svelte` with:

```css
<style>
	.login-container {
		display: flex;
		align-items: center;
		justify-content: center;
		min-height: 100vh;
		background: var(--bg);
	}
	.login-card {
		background: var(--surface-1);
		border: 1px solid var(--border);
		border-radius: 8px;
		padding: 2.5rem;
		width: 100%;
		max-width: 380px;
		box-shadow: var(--shadow);
	}
	.login-logo { display: flex; justify-content: center; margin-bottom: 1rem; }
	h1 { display: none; }
	.subtitle {
		color: var(--text-muted);
		margin: 0 0 1.5rem;
		font-size: var(--text-sm);
		letter-spacing: .08em;
	}
	.field { margin-bottom: 1rem; }
	label {
		display: block;
		font-size: var(--text-sm);
		font-weight: 500;
		margin-bottom: .25rem;
		color: var(--text-2);
	}
	input {
		width: 100%;
		padding: .5rem .75rem;
		border: 1px solid var(--border);
		border-radius: 6px;
		font-size: var(--text-base);
		box-sizing: border-box;
		background: var(--surface-2);
		color: var(--text-1);
	}
	input:focus {
		outline: none;
		border-color: var(--color-primary);
		box-shadow: 0 0 0 3px rgba(226, 61, 40, .15);
	}
	button {
		width: 100%;
		padding: .6rem;
		background: var(--color-primary);
		color: white;
		border: none;
		border-radius: 6px;
		font-size: var(--text-base);
		font-weight: 600;
		cursor: pointer;
		margin-top: .5rem;
	}
	button:hover:not(:disabled) { background: var(--color-primary-hover); }
	button:disabled {
		opacity: 0.6;
		cursor: not-allowed;
	}
	.error {
		color: var(--color-primary);
		font-size: var(--text-sm);
		margin-bottom: .5rem;
	}
</style>
```

- [ ] **Step 3: Migrate share page**

In `frontend/src/routes/share/[token]/+page.svelte` `<style>` block, make these replacements:

```css
/* OLD */
.share-sidebar { width: 300px; background: #0F1B24; color: white; padding: 1.5rem; overflow-y: auto; }
.share-header { display: flex; align-items: center; gap: .5rem; margin-bottom: .75rem; }
.convoy-info { margin-bottom: .75rem; border-bottom: 1px solid rgba(255,255,255,.1); padding-bottom: .75rem; }
.convoy-info h2 { margin: 0 0 .25rem; font-size: 1rem; }
.convoy-info p { margin: .2rem 0; font-size: .85rem; color: rgba(255,255,255,.75); }
.wp-section h3 { font-size: .9rem; margin: 1rem 0 .5rem; }
table { width: 100%; border-collapse: collapse; font-size: .8rem; }
th, td { padding: .3rem .4rem; border-bottom: 1px solid rgba(255,255,255,.1); text-align: left; }
th { color: rgba(255,255,255,.6); }
.error { color: #E23D28; font-size: .9rem; }
```
```css
/* NEW */
.share-sidebar { width: 300px; background: var(--sidebar-bg); color: var(--text-1); padding: 1.5rem; overflow-y: auto; }
.share-header { display: flex; align-items: center; gap: .5rem; margin-bottom: .75rem; }
.convoy-info { margin-bottom: .75rem; border-bottom: 1px solid var(--border); padding-bottom: .75rem; }
.convoy-info h2 { margin: 0 0 .25rem; font-size: var(--text-base); }
.convoy-info p { margin: .2rem 0; font-size: var(--text-sm); color: var(--text-2); }
.wp-section h3 { font-size: var(--text-sm); font-weight: 600; margin: 1rem 0 .5rem; color: var(--text-muted); text-transform: uppercase; letter-spacing: .06em; }
table { width: 100%; border-collapse: collapse; font-size: var(--text-sm); }
th, td { padding: .5rem; border-bottom: 1px solid var(--border); text-align: left; }
th { color: var(--text-muted); font-size: var(--text-xs); text-transform: uppercase; letter-spacing: .04em; }
.error { color: var(--color-primary); font-size: var(--text-sm); }
```

- [ ] **Step 4: Run svelte-check on all modified files**

```bash
cd frontend && npx svelte-check --tsconfig tsconfig.json 2>&1 | grep -E "^.*Error" | head -20
```

Expected: no errors.

- [ ] **Step 5: Final hardcoded color sweep**

```bash
grep -rn "#0F1B24\|#1a2a35\|color: white\b\|background: white\b" \
  frontend/src/routes/tracking frontend/src/routes/login frontend/src/routes/share \
  --include="*.svelte" | grep -v "rgba\|//"
```

Expected: no results (or only MapLibre-specific strings).

- [ ] **Step 6: Commit**

```bash
git add "frontend/src/routes/tracking/[convoy_id]/+page.svelte" \
    frontend/src/routes/login/+page.svelte \
    "frontend/src/routes/share/[token]/+page.svelte"
git commit -m "feat: token migration for tracking, login, and share pages"
```
