# GUI Overhaul — Modern Design System

## Goal

Modernize and structure the MarschPlan UI by introducing a consistent design token system, a clean typography/spacing scale, and a manual light/dark mode toggle. Layout (dark sidebar + map) is unchanged.

## Architecture

CSS custom properties serve as the design token layer on top of the existing branding variables. A `data-theme` attribute on `<html>` switches token values between light and dark palettes. The sidebar gains a fixed footer with the theme toggle. All hardcoded color and spacing values across pages are replaced with tokens.

## Tech Stack

SvelteKit 5 (runes), CSS custom properties, localStorage for theme persistence

---

## 1. Color Token System

New semantic tokens defined in `app.html` (and as `:root` fallbacks). These sit alongside the existing `--color-*` branding variables — they are structural, not brand colors.

### Dark Mode (default)

```css
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
```

### Light Mode

```css
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
```

The sidebar background stays `--surface-1` (`#161f2e` dark / stays dark in light mode too — sidebar is always dark).

**Note:** The existing `--color-bg`, `--color-surface`, `--color-text`, `--color-text-muted`, `--color-nav-bg`, `--color-nav-text` branding vars remain for backward compatibility with branding-customized deployments. The new structural tokens override layout behavior; branding vars control brand identity.

---

## 2. Typography Scale

Four sizes, three weights — nothing else.

```css
:root {
  --text-xs:   .72rem;   /* Hints, timestamps, muted labels */
  --text-sm:   .82rem;   /* Sidebar items, form labels, tags */
  --text-base: .92rem;   /* Body text, tables */
  --text-lg:   1.05rem;  /* Section titles, modal headers */
}
```

Font weights: `400` (normal), `500` (medium — labels), `600` (bold — actions, headings).

All existing ad-hoc sizes (`.55rem`, `.7rem`, `.88rem`, etc.) are replaced with the nearest token value.

---

## 3. Spacing

4px-grid: `0.25rem`, `0.5rem`, `0.75rem`, `1rem`, `1.5rem`, `2rem`. Non-grid values (`.4rem`, `.6rem`, `.7rem`, `.55rem`) are replaced with the nearest grid value. Applied consistently to padding, margin, gap.

---

## 4. Sidebar Redesign

**Header:** Logo area with `1rem` padding, clear bottom border (`1px solid --border`).

**Tabs:** Active tab uses `--surface-2` background pill instead of just an underline. Tab text uses `--text-sm`, active tab `--text-1` weight `600`, inactive `--text-2`.

**Section headers inside sidebar:** `--text-xs`, `text-transform: uppercase`, `letter-spacing: .06em`, color `--text-muted`, `margin-top: 1.5rem`, `margin-bottom: .5rem`.

**Sidebar footer (new):** Fixed at bottom of sidebar, `border-top: 1px solid --border`, `padding: .75rem 1rem`. Contains:
- Theme toggle button: sun icon (☀) in light mode, moon icon (☾) in dark mode
- App version string in `--text-muted`

---

## 5. Component Patterns

Applied consistently across all pages.

### Buttons

| Variant   | Background       | Border                  | Text        |
|-----------|-----------------|-------------------------|-------------|
| Primary   | `--color-primary` | none                   | white, `600` |
| Secondary | transparent      | `1px solid --border`   | `--text-2`  |
| Danger    | transparent      | `1px solid --color-primary` | `--color-primary` |

All buttons: `border-radius: 6px`, padding `0.5rem 1rem`, `font-size: var(--text-sm)`, `font-weight: 600`.
Primary hover: `--color-primary-hover`. Secondary hover: background `--surface-2`.
No `width: 100%` except inside forms.

### Inputs / Form Fields

- Background: `--surface-2`
- Border: `1px solid --border`
- Border-radius: `6px`
- Padding: `0.5rem 0.75rem`
- Font-size: `--text-base`
- Color: `--text-1`
- Focus: border-color `--color-primary`, no outline, `box-shadow: 0 0 0 3px rgba(226, 61, 40, .15)` (hardcoded alpha of primary — no RGB split variable needed)
- Label: `--text-sm`, `--text-2`, `font-weight: 500`, `margin-bottom: .25rem`

### Cards / Panels

- Background: `--surface-1`
- Border: `1px solid --border`
- Border-radius: `8px`
- Padding: `1rem` or `1.5rem`
- Box-shadow: `var(--shadow)` (none in dark, subtle in light)

### Section Headers

```css
.section-header {
  font-size: var(--text-xs);
  text-transform: uppercase;
  letter-spacing: .06em;
  color: var(--text-muted);
  margin-top: 1.5rem;
  margin-bottom: .5rem;
}
```

---

## 6. Theme Toggle Implementation

**Storage:** `localStorage` key `marschplan-theme`, values `"dark"` | `"light"`. Default: `"dark"`.

**Application:** `data-theme` attribute on `<html>` element, set before first paint (inline script in `app.html` to avoid FOUC).

**Toggle component:** Button in sidebar footer. On click: reads current `data-theme`, toggles, writes to `localStorage`, updates `<html>` attribute.

**Location:** `+layout.svelte` reads `localStorage` on mount and applies the saved theme.

---

## 7. Scope of Changes

### Files modified

- `frontend/src/app.html` — add `data-theme` init script + new CSS tokens
- `frontend/src/routes/+layout.svelte` — theme init on mount, pass theme state to sidebar
- `frontend/src/routes/plan/+page.svelte` — replace hardcoded colors/sizes with tokens
- `frontend/src/routes/admin/+page.svelte` — replace hardcoded colors/sizes with tokens
- `frontend/src/routes/tracking/[convoy_id]/+page.svelte` — replace hardcoded colors/sizes with tokens
- `frontend/src/routes/login/+page.svelte` — token migration
- `frontend/src/routes/share/[token]/+page.svelte` — token migration

### Not changed

- Backend, API, routing logic
- Layout structure (sidebar + map)
- Branding variables (`--color-primary` etc.)
- MapLibre layer colors (JS constants)
- Setup wizard (dark-on-dark design is intentional for that page)

---

## 8. Testing

- Visual check: toggle light/dark mode on each page, verify no hardcoded colors remain visible
- `grep -rn "#[0-9A-Fa-f]\{3,6\}" frontend/src/routes --include="*.svelte"` should return only MapLibre constants, setup page intentional darks, and rgba() values
- TypeScript: `svelte-check` zero errors after changes
