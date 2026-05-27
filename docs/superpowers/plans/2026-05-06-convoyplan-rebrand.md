# ConvoyPlan Rebrand Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rename MarschPlan → ConvoyPlan, apply brand colors, update tagline, replace favicon.

**Architecture:** Pure cosmetic edits across 6 frontend files + 1 SVG asset. No new files except the favicon SVG replacement.

**Tech Stack:** SvelteKit 5, plain CSS (inline `<style>` blocks per component)

---

### Task 1: Update page title and text in layout + login + share pages

**Files:**
- Modify: `frontend/src/routes/+layout.svelte`
- Modify: `frontend/src/routes/login/+page.svelte`
- Modify: `frontend/src/routes/share/[token]/+page.svelte`

- [ ] **Step 1: Update `+layout.svelte` title**

  Change line 24 from:
  ```html
  <title>MarschPlan</title>
  ```
  to:
  ```html
  <title>ConvoyPlan</title>
  ```

- [ ] **Step 2: Update login page text + subtitle**

  In `login/+page.svelte` change:
  ```html
  <h1>MarschPlan</h1>
  <p class="subtitle">Marschverbandsplanung für BOS</p>
  ```
  to:
  ```html
  <h1>ConvoyPlan</h1>
  <p class="subtitle">PLAN. MOVE. CONNECT.</p>
  ```

- [ ] **Step 3: Update share page heading**

  In `share/[token]/+page.svelte` change:
  ```html
  <h1>MarschPlan</h1>
  ```
  to:
  ```html
  <h1>ConvoyPlan</h1>
  ```

- [ ] **Step 4: Update Nominatim User-Agent**

  In `src/lib/components/LocationSearch.svelte` line 26, change:
  ```ts
  headers: { 'User-Agent': 'MarschPlan/1.0' }
  ```
  to:
  ```ts
  headers: { 'User-Agent': 'ConvoyPlan/1.0' }
  ```

- [ ] **Step 5: Commit**

  ```bash
  git add frontend/src/routes/+layout.svelte \
          frontend/src/routes/login/+page.svelte \
          frontend/src/routes/share/\[token\]/+page.svelte \
          frontend/src/lib/components/LocationSearch.svelte
  git commit -m "rebrand: rename MarschPlan → ConvoyPlan in text and title"
  ```

---

### Task 2: Update sidebar + topbar in plan page

**Files:**
- Modify: `frontend/src/routes/plan/+page.svelte`

- [ ] **Step 1: Update sidebar logo text**

  Find (line ~382):
  ```html
  <span class="logo">MarschPlan</span>
  ```
  Change to:
  ```html
  <span class="logo">ConvoyPlan</span>
  ```

- [ ] **Step 2: Update topbar fallback name**

  Find (line ~366):
  ```svelte
  <span class="topbar-name">{selected?.name ?? 'MarschPlan'}</span>
  ```
  Change to:
  ```svelte
  <span class="topbar-name">{selected?.name ?? 'ConvoyPlan'}</span>
  ```

- [ ] **Step 3: Commit**

  ```bash
  git add frontend/src/routes/plan/+page.svelte
  git commit -m "rebrand: update sidebar logo and topbar fallback to ConvoyPlan"
  ```

---

### Task 3: Apply brand colors to login page

**Files:**
- Modify: `frontend/src/routes/login/+page.svelte`

The login page `<style>` block uses `#1a2744` for background, h1 color, focus border, and button. The submit button CTA should become olive (`#6B7F4D`); dark accents become `#0F1B24`.

- [ ] **Step 1: Replace dark navy with brand dark in login styles**

  Find and replace all occurrences of `#1a2744` in `login/+page.svelte`:

  ```css
  /* .login-container background */
  background: #0F1B24;

  /* h1 color */
  color: #0F1B24;

  /* input:focus border */
  border-color: #0F1B24;

  /* button background */
  background: #6B7F4D;
  ```

  Specifically, the style block changes are:
  - `.login-container { background: #0F1B24; }` (was `#1a2744`)
  - `h1 { color: #0F1B24; }` (was `#1a2744`)
  - `input:focus { border-color: #0F1B24; }` (was `#1a2744`)
  - `button { background: #6B7F4D; }` (was `#1a2744`)
  - `.modal-actions .btn-primary { background: #0F1B24; border-color: #0F1B24; }` — this is in `plan/+page.svelte`, handled in Task 4

- [ ] **Step 2: Commit**

  ```bash
  git add frontend/src/routes/login/+page.svelte
  git commit -m "rebrand: apply ConvoyPlan brand colors to login page"
  ```

---

### Task 4: Apply brand colors to plan page

**Files:**
- Modify: `frontend/src/routes/plan/+page.svelte`

- [ ] **Step 1: Replace `#1a2744` with `#0F1B24`**

  In the `<style>` block of `plan/+page.svelte`, replace every occurrence of `#1a2744` with `#0F1B24`. This covers:
  - `.sidebar { background: #0F1B24; }`
  - `.modal-actions .btn-primary { background: #0F1B24; border-color: #0F1B24; }`
  - `.map-hint-bar { background: rgba(15,27,36,.9); }` (was `rgba(26,39,68,.9)`)

- [ ] **Step 2: Replace `#e74c3c` with `#E23D28`**

  Replace all occurrences of `#e74c3c` in `plan/+page.svelte` with `#E23D28`. This covers:
  - `.btn-map.active { background: #E23D28; border-color: #E23D28; }`
  - `.btn-primary { background: #E23D28; }`
  - `.btn-small.danger { background: rgba(226,61,40,.3); border-color: #E23D28; }`
  - `.btn-small.active { background: #E23D28; }`
  - `.btn-export.active { background: rgba(226,61,40,.3); border-color: #E23D28; }`

- [ ] **Step 3: Replace `#c0392b` with `#C23020`**

  Replace `#c0392b` in `plan/+page.svelte` with `#C23020`:
  - `.error-bar { background: #C23020; }`

  Also replace the `rgba(231,76,60,.3)` / `rgba(231,76,60,0.3)` occurrences (derived from `#e74c3c`) with `rgba(226,61,40,.3)`.

- [ ] **Step 4: Commit**

  ```bash
  git add frontend/src/routes/plan/+page.svelte
  git commit -m "rebrand: apply ConvoyPlan brand colors to plan page"
  ```

---

### Task 5: Apply brand colors to share page + InfoPill

**Files:**
- Modify: `frontend/src/routes/share/[token]/+page.svelte`
- Modify: `frontend/src/lib/components/InfoPill.svelte`

- [ ] **Step 1: Update share page sidebar color**

  In `share/[token]/+page.svelte`, find:
  ```css
  .share-sidebar { ... background: #1a2744; ... }
  ```
  Change `#1a2744` to `#0F1B24`.

- [ ] **Step 2: Update InfoPill colors**

  In `src/lib/components/InfoPill.svelte`, replace:
  - `rgba(20, 32, 60, 0.92)` → `rgba(15, 27, 36, 0.92)` (pill background)
  - `rgba(15, 27, 53, 0.97)` → `rgba(15, 27, 36, 0.97)` (panel background)
  - `background: #c0392b` (users badge / closures badge) → `background: #C23020`
  - `rgba(243,156,18,.6)` / `rgba(243,156,18,0)` — keep as-is (warning pulse, no change needed)

- [ ] **Step 3: Commit**

  ```bash
  git add frontend/src/routes/share/\[token\]/+page.svelte \
          frontend/src/lib/components/InfoPill.svelte
  git commit -m "rebrand: apply brand colors to share page and InfoPill"
  ```

---

### Task 6: Replace favicon

**Files:**
- Modify: `frontend/static/favicon.svg`

- [ ] **Step 1: Write new favicon SVG**

  Replace the entire content of `frontend/static/favicon.svg` with:

  ```svg
  <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32" width="32" height="32">
    <rect width="32" height="32" rx="6" fill="#0F1B24"/>
    <rect x="5" y="9" width="22" height="3" rx="1.5" fill="#6B7F4D"/>
    <rect x="5" y="14.5" width="22" height="3" rx="1.5" fill="#6B7F4D"/>
    <rect x="5" y="20" width="22" height="3" rx="1.5" fill="#A8B99A"/>
  </svg>
  ```

  Three horizontal bars represent the convoy (stacked vehicles / formation), using olive primary and light green secondary on the dark background.

- [ ] **Step 2: Commit**

  ```bash
  git add frontend/static/favicon.svg
  git commit -m "rebrand: replace favicon with ConvoyPlan brand SVG"
  ```
