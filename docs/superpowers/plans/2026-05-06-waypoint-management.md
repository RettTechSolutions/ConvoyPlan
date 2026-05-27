# Wegpunkt-Verwaltung Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Wegpunkte per Drag & Drop umsortieren und inline bearbeiten (Typ, Haltezeit, Zweck, Notiz).

**Architecture:** Neuer Backend-Endpoint `PATCH /convoys/{id}/waypoints/reorder` nimmt eine Liste von `{id, order_index}`-Paaren entgegen und setzt alle Indizes in einer Transaktion. Frontend nutzt `svelte-dnd-action` für Touch+Maus-DnD mit optimistischem Update und Rollback. Inline-Edit expandiert ein Formular direkt unter dem Wegpunkt-Item — nur ein Item gleichzeitig offen.

**Tech Stack:** FastAPI, SQLAlchemy, Svelte 5 (`$state`, `$effect`), `svelte-dnd-action`.

---

## File Map

| Datei | Änderung |
|-------|----------|
| `backend/app/schemas/waypoint.py` | +`WaypointReorderItem` Schema |
| `backend/app/api/routes/convoys.py` | +`PATCH …/waypoints/reorder` Endpoint |
| `frontend/package.json` | +`svelte-dnd-action` dependency |
| `frontend/src/lib/api/index.ts` | +`reorderWaypoints` Methode |
| `frontend/src/routes/plan/+page.svelte` | DnD-State, Inline-Edit-State, neue Template-Sektion, CSS |

---

### Task 1: Backend — `WaypointReorderItem` Schema

**Files:**
- Modify: `backend/app/schemas/waypoint.py`

- [ ] **Step 1: Schema hinzufügen**

  In `backend/app/schemas/waypoint.py` am Ende der Datei einfügen:

  ```python
  class WaypointReorderItem(BaseModel):
      id: uuid.UUID
      order_index: int
  ```

- [ ] **Step 2: Prüfen dass keine Import-Fehler entstehen**

  ```bash
  docker compose exec backend python -c "from app.schemas.waypoint import WaypointReorderItem; print('ok')"
  ```

  Expected: `ok`

- [ ] **Step 3: Commit**

  ```bash
  git add backend/app/schemas/waypoint.py
  git commit -m "feat(waypoints): add WaypointReorderItem schema"
  ```

---

### Task 2: Backend — Reorder-Endpoint

**Files:**
- Modify: `backend/app/api/routes/convoys.py`

- [ ] **Step 1: Import ergänzen**

  In `backend/app/api/routes/convoys.py`, die Import-Zeile für Waypoint-Schemas erweitern:

  Bestehend:
  ```python
  from app.schemas.waypoint import WaypointCreate, WaypointResponse, WaypointUpdate
  ```

  Ersetzen durch:
  ```python
  from app.schemas.waypoint import WaypointCreate, WaypointReorderItem, WaypointResponse, WaypointUpdate
  ```

- [ ] **Step 2: Endpoint implementieren**

  Nach dem letzten Waypoint-Endpoint (`delete_waypoint`, Ende ca. Zeile 277) einfügen:

  ```python
  @router.patch("/{convoy_id}/waypoints/reorder", response_model=list[WaypointResponse])
  async def reorder_waypoints(
      convoy_id: uuid.UUID,
      items: list[WaypointReorderItem],
      current_user: User = Depends(get_current_user),
      db: AsyncSession = Depends(get_db),
  ):
      convoy = await _load_convoy(convoy_id, current_user, db)
      result = await db.execute(
          select(Waypoint).where(Waypoint.convoy_id == convoy.id)
      )
      existing = {wp.id: wp for wp in result.scalars().all()}

      for item in items:
          if item.id not in existing:
              raise HTTPException(status_code=404, detail=f"Waypoint {item.id} not found in convoy")
          existing[item.id].order_index = item.order_index

      await db.commit()

      result2 = await db.execute(
          select(Waypoint)
          .where(Waypoint.convoy_id == convoy.id)
          .order_by(Waypoint.order_index)
      )
      waypoints = result2.scalars().all()
      return [{**w.__dict__, **geo_svc.waypoint_coords(w)} for w in waypoints]
  ```

- [ ] **Step 3: Backend neu starten und Endpoint prüfen**

  ```bash
  docker compose restart backend
  curl -s http://localhost:8000/health
  ```

  Expected: `{"status":"ok","version":"0.2.0"}`

  Dann OpenAPI-Docs prüfen:
  ```bash
  curl -s http://localhost:8000/docs | grep -o "reorder" | head -3
  ```

  Expected: `reorder` erscheint.

- [ ] **Step 4: Commit**

  ```bash
  git add backend/app/api/routes/convoys.py
  git commit -m "feat(waypoints): PATCH reorder endpoint with convoy ownership check"
  ```

---

### Task 3: Frontend — `reorderWaypoints` API-Methode

**Files:**
- Modify: `frontend/src/lib/api/index.ts`

- [ ] **Step 1: Methode zu `convoysApi` hinzufügen**

  In `frontend/src/lib/api/index.ts`, nach der Zeile mit `deleteWaypoint`:

  Bestehend (ca. Zeile 118–119):
  ```typescript
  	deleteWaypoint: (id: string, wpId: string) =>
  		api.delete(`/api/convoys/${id}/waypoints/${wpId}`),
  ```

  Danach einfügen:
  ```typescript
  	reorderWaypoints: (id: string, items: { id: string; order_index: number }[]) =>
  		api.patch<Waypoint[]>(`/api/convoys/${id}/waypoints/reorder`, items),
  ```

- [ ] **Step 2: TypeScript prüfen**

  ```bash
  cd frontend && npx tsc --noEmit 2>&1 | head -20
  ```

  Expected: keine Fehler.

- [ ] **Step 3: Commit**

  ```bash
  git add frontend/src/lib/api/index.ts
  git commit -m "feat(waypoints): add reorderWaypoints API method"
  ```

---

### Task 4: Frontend — svelte-dnd-action installieren

**Files:**
- Modify: `frontend/package.json`

- [ ] **Step 1: Dependency installieren**

  ```bash
  cd frontend && npm install svelte-dnd-action
  ```

  Expected: `added 1 package` (oder ähnlich, kein Fehler).

- [ ] **Step 2: Prüfen dass der Build weiterhin funktioniert**

  ```bash
  cd frontend && npx tsc --noEmit 2>&1 | head -20
  ```

  Expected: keine neuen Fehler.

- [ ] **Step 3: Commit**

  ```bash
  git add frontend/package.json frontend/package-lock.json
  git commit -m "feat(waypoints): add svelte-dnd-action dependency"
  ```

---

### Task 5: Frontend — Drag & Drop + Inline-Edit

**Files:**
- Modify: `frontend/src/routes/plan/+page.svelte`

- [ ] **Step 1: Imports hinzufügen**

  In `frontend/src/routes/plan/+page.svelte`, die bestehende API-Import-Zeile (ca. Zeile 14–18):
  ```typescript
  import {
  	convoysApi, vehiclesApi, orgsApi, overpassApi,
  	type Convoy, type Vehicle, type Organization, type LageLayer,
  	type FuelAnalysis, type FuelStation,
  } from '$lib/api';
  ```

  Ersetzen durch:
  ```typescript
  import {
  	convoysApi, vehiclesApi, orgsApi, overpassApi,
  	type Convoy, type Vehicle, type Organization, type LageLayer,
  	type FuelAnalysis, type FuelStation, type Waypoint,
  } from '$lib/api';
  ```

  Dann nach den bestehenden Imports (ca. Zeile 19–20) hinzufügen:
  ```typescript
  import { dndzone } from 'svelte-dnd-action';
  ```

- [ ] **Step 2: DnD- und Edit-State hinzufügen**

  Im `// ── State ──` Block (ca. Zeile 22), nach `let loading = $state(false);` einfügen:

  ```typescript
  let dndWaypoints = $state<Waypoint[]>([]);
  let editingWpId = $state<string | null>(null);
  let editWpForm = $state({ name: '', type: 'waypoint', hold_duration_min: 0, halt_purpose: '', notes: '' });
  ```

- [ ] **Step 3: `$effect` für DnD-Sync hinzufügen**

  Nach den bestehenden `$effect`-Blöcken (suche nach dem letzten `$effect(` im Script-Block) einfügen:

  ```typescript
  $effect(() => {
    if (selected) {
      dndWaypoints = [...selected.waypoints].sort((a, b) => a.order_index - b.order_index);
    }
  });
  ```

- [ ] **Step 4: DnD-Handler-Funktionen hinzufügen**

  Nach der `deleteWaypoint`-Funktion (ca. Zeile 196) einfügen:

  ```typescript
  function handleDndConsider(e: CustomEvent) {
    dndWaypoints = e.detail.items;
  }

  async function handleDndFinalize(e: CustomEvent) {
    const reordered = e.detail.items;
    dndWaypoints = reordered;
    const prevWaypoints = selected!.waypoints;
    selected = { ...selected!, waypoints: reordered };
    activeConvoy.set(selected!);
    try {
      await convoysApi.reorderWaypoints(
        selected!.id,
        reordered.map((wp: Waypoint, i: number) => ({ id: wp.id, order_index: i })),
      );
    } catch {
      selected = { ...selected!, waypoints: prevWaypoints };
      activeConvoy.set(selected!);
    }
  }

  function startEditWp(wp: Waypoint) {
    editingWpId = wp.id;
    editWpForm = {
      name: wp.name,
      type: wp.type,
      hold_duration_min: wp.hold_duration_min,
      halt_purpose: wp.halt_purpose ?? '',
      notes: wp.notes ?? '',
    };
  }

  async function saveWp(wpId: string) {
    await convoysApi.updateWaypoint(selected!.id, wpId, {
      name: editWpForm.name,
      type: editWpForm.type,
      hold_duration_min: editWpForm.hold_duration_min,
      halt_purpose: editWpForm.type === 'technical_stop' ? (editWpForm.halt_purpose || null) : null,
      notes: editWpForm.notes || null,
    });
    editingWpId = null;
    await refreshConvoy();
  }
  ```

- [ ] **Step 5: Wegpunkt-Liste im Template ersetzen**

  Den bestehenden Block (ca. Zeile 543–555):
  ```svelte
  						<ul class="wp-list">
  							{#each selected.waypoints as wp}
  								<li class="wp-item">
  									<div>
  										<strong>{wp.name}</strong>
  										<span class="tag">{WP_TYPE_LABELS[wp.type] ?? wp.type}</span>
  										{#if wp.halt_purpose}<span class="tag orange">{wp.halt_purpose}</span>{/if}
  										{#if wp.hold_duration_min > 0}<span class="tag">{wp.hold_duration_min} min</span>{/if}
  									</div>
  									<button class="btn-small danger" onclick={() => deleteWaypoint(wp.id)}>✕</button>
  								</li>
  							{/each}
  						</ul>
  ```

  Ersetzen durch:
  ```svelte
  						<ul
  							class="wp-list"
  							use:dndzone={{ items: dndWaypoints, flipDurationMs: 200 }}
  							onconsider={handleDndConsider}
  							onfinalize={handleDndFinalize}
  						>
  							{#each dndWaypoints as wp (wp.id)}
  								<li class="wp-item">
  									<div class="wp-main">
  										<strong>{wp.name}</strong>
  										<span class="tag">{WP_TYPE_LABELS[wp.type] ?? wp.type}</span>
  										{#if wp.halt_purpose}<span class="tag orange">{wp.halt_purpose}</span>{/if}
  										{#if wp.hold_duration_min > 0}<span class="tag">{wp.hold_duration_min} min</span>{/if}
  									</div>
  									<div class="wp-actions">
  										<button class="btn-small" onclick={() => startEditWp(wp)} title="Bearbeiten">✎</button>
  										<button class="btn-small danger" onclick={() => deleteWaypoint(wp.id)}>✕</button>
  									</div>
  								</li>
  								{#if editingWpId === wp.id}
  									<li class="wp-edit-form">
  										<input bind:value={editWpForm.name} placeholder="Name" />
  										<select bind:value={editWpForm.type}>
  											<option value="waypoint">Wegpunkt</option>
  											<option value="stop">Halt</option>
  											<option value="checkpoint">Kontrollpunkt</option>
  											<option value="technical_stop">Techn. Halt</option>
  										</select>
  										{#if editWpForm.type === 'technical_stop'}
  											<select bind:value={editWpForm.halt_purpose}>
  												<option value="">Zweck wählen…</option>
  												<option value="fuel">Tanken</option>
  												<option value="rest">Pause</option>
  												<option value="maintenance">Wartung</option>
  												<option value="other">Sonstiges</option>
  											</select>
  										{/if}
  										<input type="number" bind:value={editWpForm.hold_duration_min} min="0" placeholder="Haltezeit (min)" />
  										<input bind:value={editWpForm.notes} placeholder="Notiz (optional)" />
  										<div class="wp-edit-actions">
  											<button class="btn-small" onclick={() => saveWp(wp.id)}>Speichern</button>
  											<button class="btn-small" onclick={() => (editingWpId = null)}>Abbrechen</button>
  										</div>
  									</li>
  								{/if}
  							{/each}
  						</ul>
  ```

- [ ] **Step 6: CSS hinzufügen**

  Im `<style>`-Block, nach der bestehenden `.wp-item`-Regel (ca. Zeile 814):
  ```css
  .wp-item { display: flex; justify-content: space-between; align-items: center; padding: .35rem 0; border-bottom: 1px solid rgba(255,255,255,.08); font-size: .83rem; }
  ```

  Diese Zeile ersetzen durch:
  ```css
  .wp-item { display: flex; justify-content: space-between; align-items: center; padding: .35rem 0; border-bottom: 1px solid rgba(255,255,255,.08); font-size: .83rem; cursor: grab; }
  .wp-main { flex: 1; }
  .wp-actions { display: flex; gap: .25rem; }
  .wp-edit-form {
    display: flex; flex-direction: column; gap: .3rem;
    padding: .4rem .5rem;
    background: rgba(255,255,255,.05);
    border-radius: 4px;
    margin-bottom: .25rem;
  }
  .wp-edit-form input, .wp-edit-form select {
    padding: .3rem .4rem; border: none; border-radius: 3px;
    background: rgba(255,255,255,.12); color: white; font-size: .82rem;
  }
  .wp-edit-actions { display: flex; gap: .3rem; }
  ```

- [ ] **Step 7: Frontend neu bauen und testen**

  ```bash
  docker compose build frontend && docker compose up -d --no-deps frontend
  ```

  Prüfen:
  - Wegpunkte können per Drag & Drop umsortiert werden (auch Touch auf Mobile)
  - Nach Drop: Reihenfolge bleibt nach Browser-Reload erhalten (Backend wurde aktualisiert)
  - ✎-Button öffnet Edit-Form direkt unter dem Item
  - Öffnen eines zweiten ✎ schließt das erste automatisch
  - `type = technical_stop` → Zweck-Select erscheint
  - `type != technical_stop` → kein Zweck-Select
  - Speichern: Daten aktualisiert, Form verschwindet
  - Abbrechen: Form verschwindet ohne Änderung

- [ ] **Step 8: Commit**

  ```bash
  git add frontend/src/routes/plan/+page.svelte
  git commit -m "feat(waypoints): drag & drop reorder and inline edit"
  ```
