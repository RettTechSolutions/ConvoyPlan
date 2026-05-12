<script lang="ts">
    import { onMount } from 'svelte';
    import { goto } from '$app/navigation';
    import maplibregl from 'maplibre-gl';
    import 'maplibre-gl/dist/maplibre-gl.css';
    import { auth } from '$lib/stores/auth';
    import { adminApi, leistellenApi, type AdminUser, type Leitstelle, type LeistelleDetail, type ZusatzKanal } from '$lib/api';

    // ── Tab ──────────────────────────────────────────────────────────────────
    let activeTab = $state<'benutzer' | 'leitstellen'>('benutzer');

    // ── Users ────────────────────────────────────────────────────────────────
    let users = $state<AdminUser[]>([]);
    let loading = $state(true);
    let error = $state('');
    let showCreateForm = $state(false);
    let newUser = $state({ email: '', password: '', is_superadmin: false });

    onMount(async () => {
        if (!$auth.is_superadmin) { goto('/plan'); return; }
        await loadUsers();
        await loadLeitstellen();
    });

    async function loadUsers() {
        try {
            loading = true;
            users = await adminApi.listUsers();
        } catch { error = 'Benutzer konnten nicht geladen werden'; }
        finally { loading = false; }
    }

    async function createUser() {
        try {
            await adminApi.createUser(newUser);
            newUser = { email: '', password: '', is_superadmin: false };
            showCreateForm = false;
            await loadUsers();
        } catch (e: unknown) {
            error = e instanceof Error ? e.message : 'Fehler beim Erstellen';
        }
    }

    async function toggleActive(user: AdminUser) {
        try {
            await adminApi.updateUser(user.id, { is_active: !user.is_active });
            await loadUsers();
        } catch { error = 'Konnte Status nicht ändern'; }
    }

    async function toggleSuperadmin(user: AdminUser) {
        try {
            await adminApi.updateUser(user.id, { is_superadmin: !user.is_superadmin });
            await loadUsers();
        } catch { error = 'Konnte Rolle nicht ändern'; }
    }

    async function deleteUser(user: AdminUser) {
        if (!confirm(`${user.email} wirklich löschen?`)) return;
        try {
            await adminApi.deleteUser(user.id);
            await loadUsers();
        } catch { error = 'Benutzer konnte nicht gelöscht werden'; }
    }

    // ── Leitstellen ──────────────────────────────────────────────────────────
    let leitstellen = $state<Leitstelle[]>([]);
    let lsError = $state('');
    let showLsModal = $state(false);
    let editingLs = $state<LeistelleDetail | null>(null);
    let lsForm = $state({ name: '', anrufgruppe: '', zusatz_kanaele: [] as ZusatzKanal[] });

    // Polygon drawing state
    let polyMapContainer: HTMLDivElement | undefined;
    let polyMap: maplibregl.Map | undefined;
    let polygonCoords = $state<[number, number][]>([]);
    let drawingMode = $state(false);

    async function loadLeitstellen() {
        try {
            leitstellen = await leistellenApi.list();
        } catch { lsError = 'Leitstellen konnten nicht geladen werden'; }
    }

    function openCreateLs() {
        editingLs = null;
        lsForm = { name: '', anrufgruppe: '', zusatz_kanaele: [] };
        polygonCoords = [];
        drawingMode = false;
        showLsModal = true;
        initPolyMap();
    }

    async function openEditLs(ls: Leitstelle) {
        try {
            editingLs = await leistellenApi.get(ls.id);
            lsForm = {
                name: editingLs.name,
                anrufgruppe: editingLs.anrufgruppe,
                zusatz_kanaele: [...editingLs.zusatz_kanaele],
            };
            polygonCoords = [];
            drawingMode = false;
            showLsModal = true;
            initPolyMap(editingLs.geometry_geojson);
        } catch { lsError = 'Leitstelle konnte nicht geladen werden'; }
    }

    function initPolyMap(existingGeo?: object | null) {
        setTimeout(() => {
            if (!polyMapContainer) return;
            if (polyMap) { polyMap.remove(); polyMap = undefined; }

            polyMap = new maplibregl.Map({
                container: polyMapContainer,
                style: {
                    version: 8,
                    sources: { osm: { type: 'raster', tiles: ['https://tile.openstreetmap.org/{z}/{x}/{y}.png'], tileSize: 256, attribution: '© OpenStreetMap' } },
                    layers: [{ id: 'osm', type: 'raster', source: 'osm' }],
                },
                center: [10.5, 48.5],
                zoom: 6,
            });

            polyMap.on('load', () => {
                polyMap!.addSource('draft', { type: 'geojson', data: { type: 'FeatureCollection', features: [] } });
                polyMap!.addLayer({ id: 'draft-fill', type: 'fill', source: 'draft', paint: { 'fill-color': '#e74c3c', 'fill-opacity': 0.2 } });
                polyMap!.addLayer({ id: 'draft-line', type: 'line', source: 'draft', paint: { 'line-color': '#e74c3c', 'line-width': 2 } });

                if (existingGeo) {
                    updatePolySource(existingGeo as GeoJSON.Geometry);
                    const coords = (existingGeo as { coordinates?: [number, number][][] }).coordinates?.[0] ?? [];
                    if (coords.length) {
                        const lons = coords.map((c: [number, number]) => c[0]);
                        const lats = coords.map((c: [number, number]) => c[1]);
                        polyMap!.fitBounds(
                            [[Math.min(...lons), Math.min(...lats)], [Math.max(...lons), Math.max(...lats)]],
                            { padding: 40 }
                        );
                    }
                }

            });
        }, 100);
    }

    function updatePolySource(existingGeo?: GeoJSON.Geometry) {
        if (!polyMap) return;
        const src = polyMap.getSource('draft') as maplibregl.GeoJSONSource | undefined;
        if (!src) return;

        if (existingGeo) {
            src.setData({ type: 'Feature', geometry: existingGeo, properties: {} } as GeoJSON.Feature);
            return;
        }
        if (polygonCoords.length < 2) {
            src.setData({ type: 'FeatureCollection', features: [] });
            return;
        }
        if (drawingMode) {
            src.setData({ type: 'Feature', geometry: { type: 'LineString', coordinates: polygonCoords }, properties: {} } as GeoJSON.Feature);
        } else {
            const closed: [number, number][] = [...polygonCoords, polygonCoords[0]];
            src.setData({ type: 'Feature', geometry: { type: 'Polygon', coordinates: [closed] }, properties: {} } as GeoJSON.Feature);
        }
    }

    $effect(() => {
        // Reactive re-wiring of map handlers when drawingMode changes
        const drawing = drawingMode;
        if (!polyMap) return;

        const clickHandler = (e: maplibregl.MapMouseEvent) => {
            if (!drawing) return;
            polygonCoords = [...polygonCoords, [e.lngLat.lng, e.lngLat.lat]];
            updatePolySource();
        };

        const dblClickHandler = (e: maplibregl.MapMouseEvent) => {
            if (!drawing || polygonCoords.length < 3) return;
            e.preventDefault();
            drawingMode = false;
            updatePolySource();
        };

        polyMap.on('click', clickHandler);
        polyMap.on('dblclick', dblClickHandler);

        return () => {
            polyMap?.off('click', clickHandler);
            polyMap?.off('dblclick', dblClickHandler);
        };
    });

    function resetPolygon() {
        polygonCoords = [];
        drawingMode = false;
        const src = polyMap?.getSource('draft') as maplibregl.GeoJSONSource | undefined;
        src?.setData({ type: 'FeatureCollection', features: [] });
    }

    function addZusatzKanal() {
        lsForm.zusatz_kanaele = [...lsForm.zusatz_kanaele, { name: '', kanal: '' }];
    }

    function removeZusatzKanal(idx: number) {
        lsForm.zusatz_kanaele = lsForm.zusatz_kanaele.filter((_, i) => i !== idx);
    }

    async function saveLs() {
        if (!lsForm.name || !lsForm.anrufgruppe) return;
        try {
            let saved: Leitstelle;
            if (editingLs) {
                saved = await leistellenApi.update(editingLs.id, lsForm);
            } else {
                saved = await leistellenApi.create(lsForm);
            }
            // Upload drawn polygon if present
            if (!drawingMode && polygonCoords.length >= 3) {
                const closed: [number, number][] = [...polygonCoords, polygonCoords[0]];
                const geo = { type: 'Feature', geometry: { type: 'Polygon', coordinates: [closed] }, properties: {} };
                const blob = new Blob([JSON.stringify(geo)], { type: 'application/json' });
                const file = new File([blob], 'polygon.geojson', { type: 'application/json' });
                await leistellenApi.importBoundary(saved.id, file);
            }
            showLsModal = false;
            polyMap?.remove(); polyMap = undefined;
            await loadLeitstellen();
        } catch (e: unknown) {
            lsError = e instanceof Error ? e.message : 'Fehler beim Speichern';
        }
    }

    async function deleteLs(ls: Leitstelle) {
        if (!confirm(`${ls.name} wirklich löschen?`)) return;
        try {
            await leistellenApi.delete(ls.id);
            await loadLeitstellen();
        } catch { lsError = 'Leitstelle konnte nicht gelöscht werden'; }
    }
</script>

<div class="admin-page">
    <div class="admin-header">
        <h1>Admin</h1>
        <a href="/plan" class="back-link">← Plan</a>
    </div>

    <div class="tab-bar">
        <button class="tab" class:active={activeTab === 'benutzer'} onclick={() => (activeTab = 'benutzer')}>Benutzer</button>
        <button class="tab" class:active={activeTab === 'leitstellen'} onclick={() => (activeTab = 'leitstellen')}>Leitstellen</button>
    </div>

    <!-- ── Benutzer ── -->
    {#if activeTab === 'benutzer'}
        {#if error}
            <div class="error-bar">{error} <button onclick={() => (error = '')}>✕</button></div>
        {/if}

        <div class="section">
            <div class="section-header">
                <strong>Benutzer ({users.length})</strong>
                <button class="btn-small" onclick={() => (showCreateForm = !showCreateForm)}>+ Neu</button>
            </div>

            {#if showCreateForm}
                <form class="create-form" onsubmit={(e) => { e.preventDefault(); createUser(); }}>
                    <input placeholder="E-Mail *" type="email" bind:value={newUser.email} required />
                    <input placeholder="Passwort *" type="password" bind:value={newUser.password} required />
                    <label class="checkbox-label">
                        <input type="checkbox" bind:checked={newUser.is_superadmin} />
                        Superadmin
                    </label>
                    <button type="submit">Anlegen</button>
                </form>
            {/if}

            {#if loading}
                <p class="hint">Lade…</p>
            {:else}
                <table class="user-table">
                    <thead>
                        <tr>
                            <th>E-Mail</th>
                            <th>Organisationen</th>
                            <th>Aktiv</th>
                            <th>Superadmin</th>
                            <th></th>
                        </tr>
                    </thead>
                    <tbody>
                        {#each users as user}
                            <tr class:inactive={!user.is_active}>
                                <td>{user.email}</td>
                                <td class="orgs-cell">
                                    {#each user.orgs as org}
                                        <span class="tag">{org.name} ({org.role})</span>
                                    {/each}
                                </td>
                                <td>
                                    <button class="toggle-btn" class:on={user.is_active} onclick={() => toggleActive(user)}>
                                        {user.is_active ? 'Aktiv' : 'Inaktiv'}
                                    </button>
                                </td>
                                <td>
                                    <button class="toggle-btn" class:on={user.is_superadmin} onclick={() => toggleSuperadmin(user)}>
                                        {user.is_superadmin ? 'Ja' : 'Nein'}
                                    </button>
                                </td>
                                <td>
                                    <button class="btn-small danger" onclick={() => deleteUser(user)}>🗑</button>
                                </td>
                            </tr>
                        {/each}
                    </tbody>
                </table>
            {/if}
        </div>
    {/if}

    <!-- ── Leitstellen ── -->
    {#if activeTab === 'leitstellen'}
        {#if lsError}
            <div class="error-bar">{lsError} <button onclick={() => (lsError = '')}>✕</button></div>
        {/if}

        <div class="section">
            <div class="section-header">
                <strong>Leitstellen ({leitstellen.length})</strong>
                {#if $auth.is_superadmin}
                    <button class="btn-small" onclick={openCreateLs}>+ Neu</button>
                {/if}
            </div>

            <table class="user-table">
                <thead>
                    <tr>
                        <th>Name</th>
                        <th>Anrufgruppe</th>
                        <th>Zusatzkanäle</th>
                        <th>Grenzen</th>
                        {#if $auth.is_superadmin}<th></th>{/if}
                    </tr>
                </thead>
                <tbody>
                    {#each leitstellen as ls}
                        <tr>
                            <td>{ls.name}</td>
                            <td><code>{ls.anrufgruppe}</code></td>
                            <td>{ls.zusatz_kanaele.length > 0 ? ls.zusatz_kanaele.length : '–'}</td>
                            <td>{ls.has_geometry ? '✓' : '✗'}</td>
                            {#if $auth.is_superadmin}
                                <td class="actions-cell">
                                    <button class="btn-small" onclick={() => openEditLs(ls)}>✎</button>
                                    <button class="btn-small danger" onclick={() => deleteLs(ls)}>✕</button>
                                </td>
                            {/if}
                        </tr>
                    {/each}
                    {#if leitstellen.length === 0}
                        <tr><td colspan="5" class="hint" style="text-align:center">Noch keine Leitstellen erfasst.</td></tr>
                    {/if}
                </tbody>
            </table>
        </div>
    {/if}
</div>

<!-- ── Leitstelle Modal ── -->
{#if showLsModal}
    <div class="modal-backdrop" onclick={() => { showLsModal = false; polyMap?.remove(); polyMap = undefined; }}>
        <div class="modal" onclick={(e) => e.stopPropagation()}>
            <div class="modal-header">
                <h2>{editingLs ? 'Leitstelle bearbeiten' : 'Neue Leitstelle'}</h2>
                <button onclick={() => { showLsModal = false; polyMap?.remove(); polyMap = undefined; }}>✕</button>
            </div>

            <div class="modal-body">
                <div class="ls-form">
                    <label>Name *
                        <input bind:value={lsForm.name} placeholder="z.B. ILS München" required />
                    </label>
                    <label>Anrufgruppe *
                        <input bind:value={lsForm.anrufgruppe} placeholder="z.B. 468" required />
                    </label>

                    <div class="zusatz-section">
                        <div class="zusatz-header">
                            <strong>Zusatzkanäle</strong>
                            <button class="btn-small" onclick={addZusatzKanal}>+ Hinzufügen</button>
                        </div>
                        {#each lsForm.zusatz_kanaele as kanal, idx}
                            <div class="zusatz-row">
                                <input bind:value={kanal.name} placeholder="Bezeichnung" />
                                <input bind:value={kanal.kanal} placeholder="Kanal" />
                                <button class="btn-small danger" onclick={() => removeZusatzKanal(idx)}>✕</button>
                            </div>
                        {/each}
                    </div>

                    <div class="map-section">
                        <strong>Zuständigkeitsgebiet</strong>
                        <div class="poly-controls">
                            <button
                                class="btn-small"
                                class:active={drawingMode}
                                onclick={() => { drawingMode = !drawingMode; }}
                            >
                                {drawingMode ? '✓ Zeichnen aktiv (Doppelklick = fertig)' : '✏ Polygon zeichnen'}
                            </button>
                            <button class="btn-small" onclick={resetPolygon}>↺ Zurücksetzen</button>
                        </div>
                        <div class="poly-map" bind:this={polyMapContainer}></div>
                        {#if editingLs}
                            <div class="import-row">
                                <label class="btn-small file-label">
                                    📂 GeoJSON/KML importieren
                                    <input
                                        type="file"
                                        accept=".geojson,.json,.kml"
                                        style="display:none"
                                        onchange={async (e) => {
                                            const input = e.target as HTMLInputElement;
                                            const file = input.files?.[0];
                                            if (!file || !editingLs) return;
                                            await leistellenApi.importBoundary(editingLs.id, file);
                                            editingLs = await leistellenApi.get(editingLs.id);
                                            if (editingLs.geometry_geojson) {
                                                updatePolySource(editingLs.geometry_geojson as GeoJSON.Geometry);
                                            }
                                            input.value = '';
                                            await loadLeitstellen();
                                        }}
                                    />
                                </label>
                            </div>
                        {/if}
                    </div>
                </div>
            </div>

            <div class="modal-footer">
                <button onclick={() => { showLsModal = false; polyMap?.remove(); polyMap = undefined; }}>Abbrechen</button>
                <button class="btn-primary" onclick={saveLs} disabled={!lsForm.name || !lsForm.anrufgruppe}>Speichern</button>
            </div>
        </div>
    </div>
{/if}

<style>
    :global(body) { margin: 0; font-family: system-ui, sans-serif; background: #0F1B24; color: white; }
    .admin-page { max-width: 900px; margin: 0 auto; padding: 2rem 1rem; }
    .admin-header { display: flex; align-items: center; justify-content: space-between; margin-bottom: 1rem; }
    h1 { margin: 0; font-size: 1.4rem; }
    .back-link { color: rgba(255,255,255,.6); font-size: .9rem; text-decoration: none; }
    .back-link:hover { color: white; }

    .tab-bar { display: flex; gap: 0; border-bottom: 1px solid rgba(255,255,255,.15); margin-bottom: 1.5rem; }
    .tab { padding: .5rem 1.2rem; background: none; border: none; cursor: pointer; font-size: .9rem; color: rgba(255,255,255,.5); border-bottom: 2px solid transparent; margin-bottom: -1px; }
    .tab.active { color: var(--color-primary); border-bottom-color: var(--color-primary); font-weight: 600; }

    .error-bar { background: var(--color-primary-hover); color: white; padding: .4rem .75rem; border-radius: 4px; margin-bottom: 1rem; display: flex; justify-content: space-between; }
    .error-bar button { background: none; border: none; color: white; cursor: pointer; }
    .section { background: rgba(255,255,255,.05); border-radius: 8px; padding: 1rem; margin-bottom: 1rem; }
    .section-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: .75rem; }

    /* User table (original styles preserved) */
    .create-form { display: flex; flex-direction: column; gap: .5rem; margin-bottom: 1rem; padding: .75rem; background: rgba(255,255,255,.05); border-radius: 6px; }
    .create-form input { padding: .4rem .6rem; border-radius: 4px; border: 1px solid rgba(255,255,255,.2); background: rgba(255,255,255,.1); color: white; font-size: .9rem; }
    .create-form button { align-self: flex-start; padding: .4rem .9rem; background: #6B7F4D; color: white; border: none; border-radius: 4px; cursor: pointer; font-weight: 600; }
    .checkbox-label { display: flex; align-items: center; gap: .4rem; font-size: .88rem; color: rgba(255,255,255,.8); cursor: pointer; }
    .user-table { width: 100%; border-collapse: collapse; font-size: .85rem; }
    .user-table th { text-align: left; padding: .4rem .5rem; color: rgba(255,255,255,.5); font-weight: 600; border-bottom: 1px solid rgba(255,255,255,.1); }
    .user-table td { padding: .4rem .5rem; border-bottom: 1px solid rgba(255,255,255,.07); vertical-align: middle; }
    .user-table tr.inactive td { opacity: .45; }
    .orgs-cell { display: flex; flex-wrap: wrap; gap: .25rem; }
    .tag { display: inline-block; padding: .1rem .35rem; background: rgba(255,255,255,.12); border-radius: 3px; font-size: .72rem; }
    .toggle-btn { padding: .2rem .5rem; border-radius: 3px; border: 1px solid rgba(255,255,255,.25); background: rgba(255,255,255,.08); color: rgba(255,255,255,.6); font-size: .75rem; cursor: pointer; }
    .toggle-btn.on { background: rgba(107,127,77,.3); border-color: #6B7F4D; color: #a8c070; }
    .actions-cell { display: flex; gap: .3rem; }
    .hint { color: rgba(255,255,255,.4); font-size: .85rem; }
    code { background: rgba(255,255,255,.1); padding: .1rem .3rem; border-radius: 3px; font-size: .82rem; font-family: monospace; }

    .btn-small { padding: .2rem .5rem; font-size: .78rem; border-radius: 3px; border: 1px solid rgba(255,255,255,.2); background: rgba(255,255,255,.08); color: white; cursor: pointer; }
    .btn-small:hover { background: rgba(255,255,255,.15); }
    .btn-small.danger { border-color: var(--color-primary); color: var(--color-primary); }
    .btn-small.active { background: #e74c3c; color: white; border-color: #e74c3c; }
    .btn-primary { padding: .45rem 1rem; background: var(--color-primary); color: white; border: none; border-radius: 4px; font-weight: 600; cursor: pointer; }
    .btn-primary:disabled { opacity: .5; cursor: not-allowed; }

    /* Modal */
    .modal-backdrop { position: fixed; inset: 0; background: rgba(0,0,0,.6); display: flex; align-items: center; justify-content: center; z-index: 100; }
    .modal { background: #1a2a35; border: 1px solid rgba(255,255,255,.15); border-radius: 8px; width: 600px; max-width: 95vw; max-height: 90vh; display: flex; flex-direction: column; color: white; }
    .modal-header { display: flex; justify-content: space-between; align-items: center; padding: 1rem; border-bottom: 1px solid rgba(255,255,255,.1); }
    .modal-header h2 { margin: 0; font-size: 1.1rem; }
    .modal-header button { background: none; border: none; font-size: 1.1rem; cursor: pointer; color: rgba(255,255,255,.6); }
    .modal-body { padding: 1rem; overflow-y: auto; flex: 1; }
    .modal-footer { padding: .75rem 1rem; border-top: 1px solid rgba(255,255,255,.1); display: flex; justify-content: flex-end; gap: .5rem; }
    .ls-form { display: flex; flex-direction: column; gap: .75rem; }
    .ls-form label { display: flex; flex-direction: column; gap: .3rem; font-size: .85rem; font-weight: 600; }
    .ls-form input { padding: .35rem .5rem; border: 1px solid rgba(255,255,255,.2); border-radius: 4px; background: rgba(255,255,255,.08); color: white; font-size: .88rem; font-weight: 400; }
    .ls-form input::placeholder { color: rgba(255,255,255,.35); }
    .zusatz-section { display: flex; flex-direction: column; gap: .4rem; }
    .zusatz-header { display: flex; justify-content: space-between; align-items: center; font-size: .85rem; font-weight: 600; }
    .zusatz-row { display: flex; gap: .4rem; align-items: center; }
    .zusatz-row input { flex: 1; padding: .3rem .4rem; border: 1px solid rgba(255,255,255,.2); border-radius: 3px; background: rgba(255,255,255,.08); color: white; font-size: .82rem; }
    .map-section { display: flex; flex-direction: column; gap: .4rem; font-size: .85rem; font-weight: 600; }
    .poly-controls { display: flex; gap: .4rem; font-weight: 400; }
    .poly-map { height: 280px; border-radius: 6px; overflow: hidden; border: 1px solid rgba(255,255,255,.2); }
    .import-row { display: flex; gap: .5rem; align-items: center; font-weight: 400; }
    .file-label { cursor: pointer; }
</style>
