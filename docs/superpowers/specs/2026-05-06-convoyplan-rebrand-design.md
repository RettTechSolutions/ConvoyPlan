# ConvoyPlan Rebrand — Design

## Goal

Rename the product from "MarschPlan" to "ConvoyPlan", apply the ConvoyPlan brand color palette, update the login tagline, and replace the favicon. No layout or feature changes.

## Scope

Pure cosmetic changes: text, colors, favicon SVG. Every file touched is in `frontend/src/`.

---

## Text Changes

| File | Location | From | To |
|---|---|---|---|
| `src/routes/+layout.svelte` | `<title>` | MarschPlan | ConvoyPlan |
| `src/routes/login/+page.svelte` | `<h1>` | MarschPlan | ConvoyPlan |
| `src/routes/login/+page.svelte` | subtitle `<p>` | Marschverbandsplanung für BOS | PLAN. MOVE. CONNECT. |
| `src/routes/plan/+page.svelte` | sidebar `.logo` span | MarschPlan | ConvoyPlan |
| `src/routes/plan/+page.svelte` | topbar fallback | `'MarschPlan'` | `'ConvoyPlan'` |
| `src/routes/share/[token]/+page.svelte` | `<h1>` | MarschPlan | ConvoyPlan |
| `src/lib/components/LocationSearch.svelte` | Nominatim `User-Agent` header | `MarschPlan/1.0` | `ConvoyPlan/1.0` |

---

## Color Changes

| Old value | New value | Semantic role |
|---|---|---|
| `#1a2744` | `#0F1B24` | Dark background (sidebar, login bg, modals, share sidebar) |
| `#e74c3c` | `#E23D28` | Red accent (active states, primary buttons, danger) |
| `#c0392b` | `#C23020` | Error bar background (slightly darker red) |
| `rgba(26,39,68,…)` | `rgba(15,27,36,…)` | Transparent dark overlays (map hint bar) |
| `#1a2744` (login `h1`, `input:focus`, button) | `#0F1B24` (dark), `#6B7F4D` (CTA button) | Login card: title + focus border stay dark, submit button switches to olive primary |

Full brand palette for reference:
- `#0F1B24` — dark background
- `#6B7F4D` — olive primary (CTA)
- `#A8B99A` — light green secondary
- `#6B7177` — grey muted
- `#D9DDE0` — light surface
- `#E23D28` — red accent

---

## Favicon

Replace `static/favicon.svg` (currently the Svelte logo) with a minimal convoy-themed SVG:
- Background: `#0F1B24` rounded rect
- Three horizontal lines (convoy silhouette) in `#6B7F4D`
- Viewbox 32×32

---

## Out of Scope

- No backend changes
- No route or layout restructuring
- No new components
- No Docker / CI changes
