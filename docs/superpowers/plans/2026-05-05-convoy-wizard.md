# Convoy-Wizard Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Geführter 3-Schritt-Wizard zum Anlegen eines Marschverbands mit Kartenklick und Adresssuche für Start, Ziel und Wegpunkte.

**Architecture:** Neues `LocationSearch.svelte` (Nominatim-Geocoding), Wizard-State in `+page.svelte` (`wizardStep: 0|1|2|3`), vereinfachtes Erstell-Modal (nur Name + Startzeit). Der Wizard ersetzt den Tab-Bereich der Sidebar solange er aktiv ist.

**Tech Stack:** SvelteKit 2 / Svelte 5 Runes, MapLibre GL, Nominatim REST API

---

## Dateiübersicht

| Datei | Aktion | Inhalt |
|---|---|---|
| `frontend/src/lib/components/LocationSearch.svelte` | **NEU** | Debounced Nominatim-Suche mit Dropdown |
| `frontend/src/routes/plan/+page.svelte` | **ÄNDERN** | wizardStep-State, Wizard-UI, schlankes Modal, handleMapClick-Erweiterung |

---

## Task 1: LocationSearch-Komponente erstellen

**Dateien:**
- Erstellen: `frontend/src/lib/components/LocationSearch.svelte`

- [ ] **Schritt 1: Datei erstellen**

```svelte
<!-- frontend/src/lib/components/LocationSearch.svelte -->
<script lang="ts">
	interface NominatimResult {
		lat: string;
		lon: string;
		display_name: string;
	}

	interface Props {
		placeholder?: string;
		onSelect: (lat: number, lon: number, label: string) => void;
	}

	let { placeholder = 'Adresse suchen…', onSelect }: Props = $props();

	let query = $state('');
	let results = $state<NominatimResult[]>([]);
	let timer: ReturnType<typeof setTimeout>;

	function onInput() {
		clearTimeout(timer);
		if (!query.trim()) { results = []; return; }
		timer = setTimeout(async () => {
			try {
				const url = `https://nominatim.openstreetmap.org/search?q=${encodeURIComponent(query)}&format=json&limit=5&addressdetails=0`;
				const res = await fetch(url, { headers: { 'User-Agent': 'MarschPlan/1.0' } });
				results = await res.json();
			} catch { results = []; }
		}, 300);
	}

	function select(r: NominatimResult) {
		onSelect(parseFloat(r.lat), parseFloat(r.lon), r.display_name);
		query = r.display_name;
		results = [];
	}

	function onKeydown(e: KeyboardEvent) {
		if (e.key === 'Escape') { results = []; query = ''; }
	}
</script>

<div class="search-wrap">
	<input
		bind:value={query}
		oninput={onInput}
		onkeydown={onKeydown}
		{placeholder}
		autocomplete="off"
		type="search"
	/>
	{#if results.length}
		<ul class="results">
			{#each results as r}
				<li onclick={() => select(r)}>{r.display_name}</li>
			{/each}
		</ul>
	{/if}
</div>

<style>
	.search-wrap { position: relative; margin-bottom: .5rem; }
	input {
		width: 100%; padding: .45rem .6rem; border-radius: 4px;
		border: 1px solid rgba(255,255,255,.25); background: rgba(255,255,255,.1);
		color: white; font-size: .85rem; box-sizing: border-box;
	}
	input::placeholder { color: rgba(255,255,255,.45); }
	input:focus { outline: none; border-color: rgba(255,255,255,.5); }
	.results {
		position: absolute; z-index: 200; width: 100%;
		background: #1e3160; border: 1px solid rgba(255,255,255,.2);
		border-radius: 4px; margin: 2px 0 0; padding: 0; list-style: none;
		max-height: 200px; overflow-y: auto;
	}
	li {
		padding: .4rem .6rem; font-size: .78rem; cursor: pointer;
		border-bottom: 1px solid rgba(255,255,255,.08); color: rgba(255,255,255,.9);
		line-height: 1.3;
	}
	li:hover { background: rgba(255,255,255,.1); }
	li:last-child { border-bottom: none; }
</style>
```

- [ ] **Schritt 2: Commit**

```bash
git add frontend/src/lib/components/LocationSearch.svelte
git commit -m "feat: LocationSearch component with Nominatim geocoding"
```

---

## Task 2: Wizard-State und handleMapClick erweitern

**Dateien:**
- Ändern: `frontend/src/routes/plan/+page.svelte` — Script-Bereich

- [ ] **Schritt 1: Import und State hinzufügen**

In `+page.svelte` Zeile 4 (nach `import MapView`) folgende Zeile einfügen:

```typescript
import LocationSearch from '$lib/components/LocationSearch.svelte';
```

Nach Zeile 41 (`let pendingWpClick = $state(false);`) folgende Zeile einfügen:

```typescript
let wizardStep = $state<0 | 1 | 2 | 3>(0);
let wizardWpName = $state('');
```

- [ ] **Schritt 2: createConvoy() — wizardStep nach Erstellung setzen**

Den `createConvoy()`-Block (Zeilen 74–99) so ändern, dass nach `showConvoyForm = false;` der Wizard gestartet wird:

```typescript
async function createConvoy() {
    try {
        const c = await convoysApi.create({
            name: newConvoy.name,
            organization: newConvoy.organization || undefined,
            organization_id: newConvoy.organization_id || undefined,
            start_time: newConvoy.start_time || undefined,
            speed_urban_kmh: newConvoy.speed_urban_kmh,
            speed_rural_kmh: newConvoy.speed_rural_kmh,
        });
        convoyList = [...convoyList, c];
        convoys.set(convoyList);
        selectConvoy(c);
        showConvoyForm = false;
        newConvoy = { name:'', organization:'', organization_id:'', start_time:'', speed_urban_kmh:40, speed_rural_kmh:65, lage:'', auftrag:'', marschform:'geschlossener_verband', ablaufpunkt:'', ablaufzeit:'', ablaufführer:'', versorgung:'', funkgruppe:'', anlagen:'' };
        wizardStep = 1;
        mapMode.set('set-start');
    } catch { error = 'Konvoi konnte nicht erstellt werden'; }
}
```

- [ ] **Schritt 3: handleMapClick() — Wizard auto-advance**

Den `handleMapClick()`-Block (Zeilen 139–162) so ändern:

```typescript
async function handleMapClick(lat: number, lon: number) {
    if (!selected) return;
    const mode = $mapMode;
    if (mode === 'set-start') {
        await convoysApi.update(selected.id, { start_point: { lat, lon } });
        mapMode.set('idle');
        if (wizardStep === 1) { wizardStep = 2; mapMode.set('set-end'); }
    } else if (mode === 'set-end') {
        await convoysApi.update(selected.id, { end_point: { lat, lon } });
        mapMode.set('idle');
        if (wizardStep === 2) { wizardStep = 3; mapMode.set('add-waypoint'); }
    } else if (mode === 'add-waypoint') {
        const name = wizardStep === 3
            ? (wizardWpName.trim() || `WP ${(selected.waypoints.length + 1)}`)
            : (newWpForm.name || prompt('Wegpunktname:') || `WP ${(selected.waypoints.length + 1)}`);
        await convoysApi.createWaypoint(selected.id, {
            name,
            type: wizardStep === 3 ? 'waypoint' : newWpForm.type,
            lat,
            lon,
            hold_duration_min: wizardStep === 3 ? 0 : newWpForm.hold_duration_min,
            halt_purpose: wizardStep === 3 ? undefined : (newWpForm.halt_purpose || undefined),
            order_index: selected.waypoints.length,
        });
        wizardWpName = '';
        if (wizardStep !== 3) mapMode.set('idle');
        // Im Wizard-Schritt 3 bleibt mapMode auf 'add-waypoint'
    }
    await refreshConvoy();
}
```

- [ ] **Schritt 4: Wizard-Hilfsfunktionen hinzufügen**

Nach `handleMapMove` (nach Zeile 166) einfügen:

```typescript
function wizardSetPoint(lat: number, lon: number, label: string) {
    handleMapClick(lat, lon);
}

function wizardSkip() {
    if (wizardStep === 1) { wizardStep = 2; mapMode.set('set-end'); }
    else if (wizardStep === 2) { wizardStep = 3; mapMode.set('add-waypoint'); }
    else if (wizardStep === 3) { wizardStep = 0; mapMode.set('idle'); }
}

function wizardFinish() {
    wizardStep = 0;
    mapMode.set('idle');
}
```

- [ ] **Schritt 5: Commit**

```bash
git add frontend/src/routes/plan/+page.svelte
git commit -m "feat: wizard state, handleMapClick auto-advance, wizard helpers"
```

---

## Task 3: Wizard-UI in der Sidebar

**Dateien:**
- Ändern: `frontend/src/routes/plan/+page.svelte` — Template-Bereich

- [ ] **Schritt 1: Tabs und tab-content bedingt ausblenden**

Den Block ab Zeile 286 (`<!-- Tabs -->`) so umschließen:

```svelte
{#if wizardStep === 0}
    <!-- Tabs -->
    <div class="tabs">
        {#each [['convoy','Plan'],['fahrzeuge','Fahrzeuge'],['wegpunkte','Wegpunkte'],['zeitplan','Zeitplan'],['export','Export'],['lage','Lage'],['org','Org']] as [tab, label]}
            <button class="tab" class:active={activeTab === tab} onclick={() => (activeTab = tab as typeof activeTab)}>{label}</button>
        {/each}
    </div>

    <div class="tab-content">
        <!-- ... gesamter bestehender Tab-Inhalt bleibt unverändert ... -->
    </div>
{:else}
    <!-- Wizard -->
    <div class="wizard">
        <div class="wizard-steps">
            <span class:active={wizardStep === 1}>1</span>
            <span class="sep">›</span>
            <span class:active={wizardStep === 2}>2</span>
            <span class="sep">›</span>
            <span class:active={wizardStep === 3}>3</span>
        </div>

        {#if wizardStep === 1}
            <h3 class="wizard-title">Startpunkt setzen</h3>
            <LocationSearch
                placeholder="Startort suchen…"
                onSelect={wizardSetPoint}
            />
            <p class="hint">oder direkt auf die Karte klicken ↗</p>
            <button class="btn-skip" onclick={wizardSkip}>Überspringen →</button>

        {:else if wizardStep === 2}
            <h3 class="wizard-title">Zielpunkt setzen</h3>
            <LocationSearch
                placeholder="Zielort suchen…"
                onSelect={wizardSetPoint}
            />
            <p class="hint">oder direkt auf die Karte klicken ↗</p>
            <button class="btn-skip" onclick={wizardSkip}>Überspringen →</button>

        {:else if wizardStep === 3}
            <h3 class="wizard-title">Wegpunkte hinzufügen</h3>
            <input
                class="wp-name-input"
                placeholder="Name (optional)"
                bind:value={wizardWpName}
            />
            <LocationSearch
                placeholder="Wegpunkt suchen…"
                onSelect={wizardSetPoint}
            />
            <p class="hint">oder auf die Karte klicken ↗</p>
            {#if selected?.waypoints?.length}
                <ul class="wizard-wp-list">
                    {#each selected.waypoints as wp}
                        <li>📍 {wp.name}</li>
                    {/each}
                </ul>
            {/if}
            <button class="btn-primary" onclick={wizardFinish}>Fertig ✓</button>
            <button class="btn-skip" onclick={wizardSkip}>Überspringen →</button>
        {/if}
    </div>
{/if}
```

**Wichtig:** Der gesamte bestehende `<div class="tab-content">` Block (Zeilen 293–617) bleibt unverändert innerhalb des `{#if wizardStep === 0}` Blocks.

- [ ] **Schritt 2: Wizard-CSS am Ende des `<style>`-Blocks ergänzen**

Am Ende des `<style>`-Blocks (nach der letzten CSS-Regel, vor `</style>`) einfügen:

```css
.wizard { flex: 1; overflow-y: auto; padding: .75rem 1rem; display: flex; flex-direction: column; gap: .5rem; }
.wizard-steps { display: flex; align-items: center; gap: .3rem; font-size: .75rem; color: rgba(255,255,255,.4); margin-bottom: .25rem; }
.wizard-steps span.active { color: white; font-weight: 700; }
.wizard-steps .sep { color: rgba(255,255,255,.25); }
.wizard-title { margin: 0 0 .5rem; font-size: .95rem; font-weight: 600; color: white; }
.btn-skip { background: none; border: none; color: rgba(255,255,255,.45); font-size: .78rem; cursor: pointer; padding: .2rem 0; text-align: left; }
.btn-skip:hover { color: rgba(255,255,255,.7); }
.wp-name-input { width: 100%; padding: .4rem .6rem; border-radius: 4px; border: 1px solid rgba(255,255,255,.2); background: rgba(255,255,255,.08); color: white; font-size: .85rem; box-sizing: border-box; }
.wp-name-input::placeholder { color: rgba(255,255,255,.35); }
.wizard-wp-list { list-style: none; padding: 0; margin: 0; max-height: 120px; overflow-y: auto; }
.wizard-wp-list li { font-size: .8rem; color: rgba(255,255,255,.75); padding: .2rem 0; border-bottom: 1px solid rgba(255,255,255,.07); }
```

- [ ] **Schritt 3: Commit**

```bash
git add frontend/src/routes/plan/+page.svelte
git commit -m "feat: wizard UI in sidebar with step indicator"
```

---

## Task 4: Convoy-Modal vereinfachen

**Dateien:**
- Ändern: `frontend/src/routes/plan/+page.svelte` — Modal-Block (Zeilen 642–684)

- [ ] **Schritt 1: Modal-Inhalt ersetzen**

Den gesamten Modal-Block (Zeilen 642–684) ersetzen mit:

```svelte
<!-- ── Modal: Neuer Marschverband ─────────────────────────────────── -->
{#if showConvoyForm}
    <div class="modal-backdrop" onclick={() => (showConvoyForm = false)}>
        <div class="modal" onclick={(e) => e.stopPropagation()}>
            <h2>Neuer Marschverband</h2>
            <form onsubmit={(e) => { e.preventDefault(); createConvoy(); }}>
                <label>Name *<input bind:value={newConvoy.name} required placeholder="z.B. KatS-Verband Bayern 1" /></label>
                <label>Startzeit (optional)<input type="datetime-local" bind:value={newConvoy.start_time} /></label>
                <label>Geschw. innerorts (km/h)<input type="number" bind:value={newConvoy.speed_urban_kmh} min="10" max="60" /></label>
                <label>Geschw. außerorts (km/h)<input type="number" bind:value={newConvoy.speed_rural_kmh} min="30" max="100" /></label>
                <p class="hint" style="margin:.25rem 0">Weitere Felder (Lage, Auftrag, Funkgruppe…) kannst du nach dem Erstellen im Plan-Tab ergänzen.</p>
                <div class="modal-actions">
                    <button type="button" onclick={() => (showConvoyForm = false)}>Abbrechen</button>
                    <button type="submit" class="btn-primary">Erstellen & Punkte setzen →</button>
                </div>
            </form>
        </div>
    </div>
{/if}
```

- [ ] **Schritt 2: Commit**

```bash
git add frontend/src/routes/plan/+page.svelte
git commit -m "feat: simplify convoy creation modal, start wizard after create"
```

---

## Task 5: Docker-Build und End-to-End-Test

**Dateien:**
- Kein Code

- [ ] **Schritt 1: Frontend neu bauen und starten**

```bash
docker compose build frontend && docker compose up -d frontend
```

Erwartetes Ergebnis: Build ohne Fehler, Container läuft auf Port 3000.

- [ ] **Schritt 2: Manueller Test — Vollständiger Flow**

1. Browser öffnen: `http://localhost:3000`
2. Login mit `christoph@zeitler.tech` / `MarschPlan2026!`
3. Klick auf `+ Neu` → Modal erscheint (nur Name, Startzeit, Geschwindigkeit)
4. Name eingeben → `Erstellen & Punkte setzen →` klicken
5. Wizard erscheint in Sidebar: **Schritt 1 – Startpunkt**
   - Adresse in Suchfeld eingeben (z.B. "München Hauptbahnhof") → Ergebnisse erscheinen → Klick setzt grünen Marker auf Karte
   - Wizard springt automatisch zu **Schritt 2 – Zielpunkt**
6. Direkt auf Karte klicken → roter Marker erscheint → Wizard springt zu **Schritt 3 – Wegpunkte**
7. Optional: Name eingeben, Karte klicken → Waypoint in Liste sichtbar
8. `Fertig ✓` klicken → Wizard beendet, normaler Plan-Tab sichtbar
9. Verify: `🗺 Route berechnen` Button funktioniert und zeigt Route

- [ ] **Schritt 3: Überspringen-Flow testen**

1. Neuen Marschverband anlegen
2. In Schritt 1: `Überspringen →` klicken → Schritt 2 erscheint
3. In Schritt 2: `Überspringen →` klicken → Schritt 3 erscheint
4. In Schritt 3: `Überspringen →` klicken → Wizard beendet
5. Verify: Convoy ohne Punkte in Dropdown auswählbar

- [ ] **Schritt 4: Abschluss-Commit**

```bash
git add .
git commit -m "feat: convoy wizard complete - guided start/end/waypoint setup"
```
