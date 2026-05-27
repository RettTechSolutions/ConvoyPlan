# Wegpunkt-Verwaltung Design

## Ziel

Wegpunkte per Drag & Drop umsortieren und inline bearbeiten (Typ, Haltezeit, Zweck, Notiz).

---

## Backend — Reorder-Endpoint

**Datei:** `backend/app/api/routes/convoys.py`

Neuer Endpoint:

```
PATCH /convoys/{convoy_id}/waypoints/reorder
```

**Request Body:**
```json
[
  {"id": "uuid", "order_index": 0},
  {"id": "uuid", "order_index": 1}
]
```

**Verhalten:**
- Owner-Check via `_load_convoy` (bestehende Hilfsfunktion)
- Alle `order_index`-Werte werden in einer DB-Transaktion gesetzt
- Gibt `list[WaypointResponse]` der aktualisierten Wegpunkte zurück
- 404 wenn ein gesendetes `id` nicht zum Convoy gehört

**Schema:** Neues Pydantic-Schema `WaypointReorderItem` in `backend/app/schemas/waypoint.py`:
```python
class WaypointReorderItem(BaseModel):
    id: uuid.UUID
    order_index: int
```

Bestehende Endpoints (`POST`, `PUT`, `DELETE` auf Waypoints) bleiben unverändert.

---

## Frontend — Drag & Drop

**Datei:** `frontend/src/routes/plan/+page.svelte`

**Dependency:** `svelte-dnd-action` (`npm install svelte-dnd-action`)

### Template

Die `<ul class="wp-list">` im Wegpunkte-Tab wird durch eine `dndzone`-Liste ersetzt:

```svelte
<ul
  class="wp-list"
  use:dndzone={{ items: dndWaypoints, flipDurationMs: 200 }}
  onconsider={handleDndConsider}
  onfinalize={handleDndFinalize}
>
```

`dndWaypoints` ist eine separate `$state`-Kopie der Wegpunkte, die `dndzone` benötigt (erfordert ein `id`-Feld, das bei Waypoints bereits vorhanden ist).

### State & Handlers

```typescript
let dndWaypoints = $state<typeof selected.waypoints>([]);

// Sync wenn selected.waypoints sich ändert
$effect(() => {
  if (selected) dndWaypoints = [...selected.waypoints].sort((a, b) => a.order_index - b.order_index);
});

function handleDndConsider(e: CustomEvent) {
  dndWaypoints = e.detail.items;
}

async function handleDndFinalize(e: CustomEvent) {
  const reordered = e.detail.items;
  dndWaypoints = reordered;
  // Optimistisch in selected aktualisieren
  selected = { ...selected!, waypoints: reordered };
  activeConvoy.set(selected!);
  try {
    await convoysApi.reorderWaypoints(
      selected!.id,
      reordered.map((wp, i) => ({ id: wp.id, order_index: i }))
    );
  } catch {
    // Rollback
    await refreshConvoy();
  }
}
```

### API-Client

Neue Methode in `frontend/src/lib/api/convoys.ts` (oder dem bestehenden API-Modul):

```typescript
reorderWaypoints: (convoyId: string, items: { id: string; order_index: number }[]) =>
  api.patch(`/convoys/${convoyId}/waypoints/reorder`, items),
```

---

## Frontend — Inline-Edit

**Datei:** `frontend/src/routes/plan/+page.svelte`

### State

```typescript
let editingWpId = $state<string | null>(null);
let editWpForm = $state({ name: '', type: 'waypoint', hold_duration_min: 0, halt_purpose: '', notes: '' });
```

Nur ein Wegpunkt gleichzeitig offen. Öffnen eines anderen schließt das vorherige.

### Edit öffnen

```typescript
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
```

### Speichern

```typescript
async function saveWp(wpId: string) {
  await convoysApi.updateWaypoint(selected!.id, wpId, {
    name: editWpForm.name,
    type: editWpForm.type,
    hold_duration_min: editWpForm.hold_duration_min,
    halt_purpose: editWpForm.type === 'technical_stop' ? editWpForm.halt_purpose : null,
    notes: editWpForm.notes || null,
  });
  editingWpId = null;
  await refreshConvoy();
}
```

### Template

```svelte
{#each dndWaypoints as wp (wp.id)}
  <li class="wp-item">
    <div class="wp-main">
      <strong>{wp.name}</strong>
      <span class="tag">{WP_TYPE_LABELS[wp.type] ?? wp.type}</span>
      {#if wp.halt_purpose}<span class="tag orange">{wp.halt_purpose}</span>{/if}
      {#if wp.hold_duration_min > 0}<span class="tag">{wp.hold_duration_min} min</span>{/if}
    </div>
    <div class="wp-actions">
      <button class="btn-small" onclick={() => startEditWp(wp)}>✎</button>
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
```

### CSS (neue Klassen)

```css
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

---

## Nicht im Scope

- Wegpunkt-Koordinaten per Inline-Edit ändern (Verschieben weiter über die Karte)
- Zeitplan-Einträge editieren
- Neue Wegpunkte über das Edit-Formular anlegen (weiterhin über Karte)
