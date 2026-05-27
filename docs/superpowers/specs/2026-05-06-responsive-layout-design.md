# Responsive Layout Design

## Ziel

Die Plan-Seite (`/plan`) responsiv machen: Desktop bleibt unverändert (Sidebar links + Karte rechts). Auf Mobilgeräten erscheint eine Top-Bar mit Hamburger-Menü; die Sidebar öffnet sich als Overlay von links.

---

## Architektur

Alle Änderungen beschränken sich auf `frontend/src/routes/plan/+page.svelte`. Keine neuen Komponenten — nur CSS-Breakpoints und eine kleine State-Variable für den Sidebar-Zustand.

Breakpoint: `@media (max-width: 768px)` für alle mobilen Anpassungen.

---

## Desktop (> 768px) — unverändert

- `.app`: `display: flex; height: 100vh`
- `.sidebar`: `width: 340px`, immer sichtbar, nicht verschiebbar
- Karte füllt den Rest
- Keine Änderung am bestehenden Verhalten

---

## Mobil (≤ 768px)

### Top-Bar

Neue `.topbar`-Leiste, `position: fixed; top: 0; left: 0; right: 0; z-index: 200; height: 48px`.

Inhalte von links nach rechts:
1. **Hamburger-Button** (☰) — öffnet/schließt Sidebar
2. **Verbandname** — Name des aktiven Convoy, `flex: 1`, abgeschnitten mit Ellipsis
3. **Schnellaktionen** — kompakte Buttons: `📍 Start`, `🏁 Ziel`, `➕ WP` (dieselbe Logik wie die bestehenden `btn-map`-Buttons, nur in der Top-Bar platziert)

### Karte

- Füllt den gesamten Bildschirm unterhalb der Top-Bar (`padding-top: 48px` auf `.app` auf Mobil)
- Route-Button wird als Floating-Button (`position: fixed; bottom: 1.5rem; right: 1rem`) auf der Karte angezeigt

### Sidebar als Overlay

- `.sidebar` auf Mobil: `position: fixed; left: 0; top: 48px; bottom: 0; width: 300px; z-index: 300; transform: translateX(-100%); transition: transform 0.25s ease`
- Wenn offen: `transform: translateX(0)`
- Backdrop: `position: fixed; inset: 0; background: rgba(0,0,0,0.45); z-index: 299` — Tippen schließt Sidebar
- Backdrop nur sichtbar wenn Sidebar offen (`sidebarOpen`-State)

### State

Eine neue `$state`-Variable `let sidebarOpen = $state(false)` steuert:
- CSS-Klasse `open` auf `.sidebar`
- Sichtbarkeit des Backdrops
- Hamburger-Tooltip

### ServiceStatus

Bleibt `position: fixed; bottom: 1.25rem; left: 1rem` — funktioniert auf Mobil ohne Änderung. Kein Konflikt mit Sidebar da diese `top: 48px` beginnt.

### Convoy-Selektor und Tabs

Bleiben in der Sidebar — auf Mobil also nur über die offene Sidebar zugänglich. Die Top-Bar zeigt nur den aktuellen Namen (read-only, kein Wechsel direkt in der Bar). Wer wechseln will, öffnet die Sidebar.

---

## Änderungen im Detail

**Datei:** `frontend/src/routes/plan/+page.svelte`

1. State hinzufügen: `let sidebarOpen = $state(false)`
2. Template: Top-Bar-Block (nur sichtbar auf Mobil via CSS) mit Hamburger, Name, Schnellaktionen
3. Template: Backdrop-`<div>` mit `onclick={() => sidebarOpen = false}`
4. Template: Klasse `class:open={sidebarOpen}` auf `<aside class="sidebar">`
5. CSS: Media Query `@media (max-width: 768px)` mit allen Mobil-Regeln
6. CSS: Route-Button als FAB auf Mobil (`position: fixed`)

---

## Nicht im Scope

- Login-Seite, Share-Seite, Tracking-Seite — werden nicht angefasst
- Desktop-Layout bleibt pixel-genau identisch
- Keine neue Komponente, kein neuer Store
- Keine Änderung am Backend
