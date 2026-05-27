<script lang="ts">
    import { onMount } from 'svelte';
    import { goto } from '$app/navigation';
    import { page } from '$app/stores';
    import maplibregl from 'maplibre-gl';
    import 'maplibre-gl/dist/maplibre-gl.css';
    import { orgStore } from '$lib/stores/org';
    import { leistellenApi, orgsApi, type Leitstelle, type LeistelleDetail, type ZusatzKanal, type OrgMember } from '$lib/api';
    import { brandingStore, applyBranding, BRANDING_DEFAULTS } from '$lib/stores/branding';
    import { brandingApi, type BrandingUpdate } from '$lib/api';

    // ── Slug ─────────────────────────────────────────────────────────────────
    const slug = $derived(($page.params as Record<string, string>).slug);

    // ── Tab ──────────────────────────────────────────────────────────────────
    let activeTab = $state<'mitglieder' | 'leitstellen' | 'branding'>('mitglieder');

    // ── Auth guard ───────────────────────────────────────────────────────────
    onMount(async () => {
        const s = ($page.params as Record<string, string>).slug;
        if ($orgStore?.user_role !== 'admin') {
            goto(`/o/${s}/plan`);
            return;
        }
        await loadMembers();
        await loadLeitstellen();
        await loadBranding();
    });

    // ── Mitglieder ───────────────────────────────────────────────────────────
    let members = $state<OrgMember[]>([]);
    let membersLoading = $state(false);
    let membersError = $state('');
    let addMemberForm = $state({ email: '', role: 'beobachter' });
    let addMemberWorking = $state(false);
    let inviteForm = $state({ email: '', password: '', role: 'beobachter' });
    let inviteWorking = $state(false);
    let showInviteForm = $state(false);

    async function loadMembers() {
        if (!$orgStore?.org_id) return;
        membersLoading = true;
        try { members = await orgsApi.listMembers($orgStore.org_id); }
        catch { membersError = 'Mitglieder konnten nicht geladen werden'; }
        finally { membersLoading = false; }
    }

    async function addMember() {
        if (!$orgStore?.org_id || !addMemberForm.email) return;
        addMemberWorking = true;
        membersError = '';
        try {
            await orgsApi.addMember($orgStore.org_id, addMemberForm.email, addMemberForm.role);
            addMemberForm = { email: '', role: 'beobachter' };
            await loadMembers();
        } catch (e: unknown) {
            membersError = e instanceof Error ? e.message : 'Fehler beim Hinzufügen';
        } finally { addMemberWorking = false; }
    }

    async function inviteMember() {
        if (!$orgStore?.org_id || !inviteForm.email || !inviteForm.password) return;
        inviteWorking = true;
        membersError = '';
        try {
            await orgsApi.inviteMember($orgStore.org_id, inviteForm.email, inviteForm.password);
            // After invite, also set the role if not default
            if (inviteForm.role !== 'beobachter') {
                const fresh = await orgsApi.listMembers($orgStore.org_id);
                const invited = fresh.find(m => m.email === inviteForm.email);
                if (invited) await orgsApi.updateMemberRole($orgStore.org_id, invited.user_id, inviteForm.role);
            }
            inviteForm = { email: '', password: '', role: 'beobachter' };
            showInviteForm = false;
            await loadMembers();
        } catch (e: unknown) {
            membersError = e instanceof Error ? e.message : 'Fehler beim Einladen';
        } finally { inviteWorking = false; }
    }

    async function updateRole(userId: string, role: string) {
        if (!$orgStore?.org_id) return;
        try { await orgsApi.updateMemberRole($orgStore.org_id, userId, role); await loadMembers(); }
        catch { membersError = 'Rolle konnte nicht geändert werden'; }
    }

    async function removeMember(userId: string, email: string) {
        if (!confirm(`${email} aus der Organisation entfernen?`)) return;
        if (!$orgStore?.org_id) return;
        try { await orgsApi.removeMember($orgStore.org_id, userId); await loadMembers(); }
        catch { membersError = 'Mitglied konnte nicht entfernt werden'; }
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

    // ── Branding ──────────────────────────────────────────────────────────────
    let brandingForm = $state<BrandingUpdate>({
        app_name: BRANDING_DEFAULTS.app_name,
        color_primary: BRANDING_DEFAULTS.color_primary,
        color_primary_hover: BRANDING_DEFAULTS.color_primary_hover,
        color_accent: BRANDING_DEFAULTS.color_accent,
        color_bg: BRANDING_DEFAULTS.color_bg,
        color_surface: BRANDING_DEFAULTS.color_surface,
        color_nav_bg: BRANDING_DEFAULTS.color_nav_bg,
        color_nav_text: BRANDING_DEFAULTS.color_nav_text,
        color_text: BRANDING_DEFAULTS.color_text,
        color_text_muted: BRANDING_DEFAULTS.color_text_muted,
    });
    let logoMainPreview = $state<string | null>(null);
    let logoHorizPreview = $state<string | null>(null);
    let brandingSaving = $state(false);
    let brandingError = $state('');
    let brandingSuccess = $state(false);

    $effect(() => {
        if (activeTab !== 'branding') {
            applyBranding($brandingStore);
            return;
        }
        const root = document.documentElement;
        root.style.setProperty('--color-primary', brandingForm.color_primary);
        root.style.setProperty('--color-primary-hover', brandingForm.color_primary_hover);
        root.style.setProperty('--color-accent', brandingForm.color_accent);
        root.style.setProperty('--color-bg', brandingForm.color_bg);
        root.style.setProperty('--color-surface', brandingForm.color_surface);
        root.style.setProperty('--color-nav-bg', brandingForm.color_nav_bg);
        root.style.setProperty('--color-nav-text', brandingForm.color_nav_text);
        root.style.setProperty('--color-text', brandingForm.color_text);
        root.style.setProperty('--color-text-muted', brandingForm.color_text_muted);
    });

    async function loadBranding() {
        try {
            const data = await brandingApi.get();
            brandingForm = {
                app_name: data.app_name,
                color_primary: data.color_primary,
                color_primary_hover: data.color_primary_hover,
                color_accent: data.color_accent,
                color_bg: data.color_bg,
                color_surface: data.color_surface,
                color_nav_bg: data.color_nav_bg,
                color_nav_text: data.color_nav_text,
                color_text: data.color_text,
                color_text_muted: data.color_text_muted,
            };
            logoMainPreview = data.logo_main_url;
            logoHorizPreview = data.logo_horizontal_url;
        } catch { /* keep defaults */ }
    }

    async function saveBranding() {
        brandingError = '';
        brandingSuccess = false;
        brandingSaving = true;
        try {
            const result = await brandingApi.update(brandingForm);
            brandingStore.set({ ...result });
            applyBranding({ ...result });
            brandingForm = {
                app_name: result.app_name,
                color_primary: result.color_primary,
                color_primary_hover: result.color_primary_hover,
                color_accent: result.color_accent,
                color_bg: result.color_bg,
                color_surface: result.color_surface,
                color_nav_bg: result.color_nav_bg,
                color_nav_text: result.color_nav_text,
                color_text: result.color_text,
                color_text_muted: result.color_text_muted,
            };
            logoMainPreview = result.logo_main_url;
            logoHorizPreview = result.logo_horizontal_url;
            brandingSuccess = true;
            setTimeout(() => { brandingSuccess = false; }, 3000);
        } catch (e: unknown) {
            brandingError = e instanceof Error ? e.message : 'Fehler beim Speichern';
        } finally {
            brandingSaving = false;
        }
    }

    function resetBrandingDefaults() {
        brandingForm = {
            app_name: BRANDING_DEFAULTS.app_name,
            color_primary: BRANDING_DEFAULTS.color_primary,
            color_primary_hover: BRANDING_DEFAULTS.color_primary_hover,
            color_accent: BRANDING_DEFAULTS.color_accent,
            color_bg: BRANDING_DEFAULTS.color_bg,
            color_surface: BRANDING_DEFAULTS.color_surface,
            color_nav_bg: BRANDING_DEFAULTS.color_nav_bg,
            color_nav_text: BRANDING_DEFAULTS.color_nav_text,
            color_text: BRANDING_DEFAULTS.color_text,
            color_text_muted: BRANDING_DEFAULTS.color_text_muted,
        };
        logoMainPreview = null;
        logoHorizPreview = null;
    }

    function onAdminLogoMainChange(e: Event) {
        const file = (e.target as HTMLInputElement).files?.[0];
        if (!file) return;
        logoMainPreview = URL.createObjectURL(file);
        brandingApi.uploadLogo('main', file)
            .then(result => { brandingStore.set({ ...result }); applyBranding({ ...result }); })
            .catch(() => { brandingError = 'Logo-Upload fehlgeschlagen'; });
    }

    function onAdminLogoHorizChange(e: Event) {
        const file = (e.target as HTMLInputElement).files?.[0];
        if (!file) return;
        logoHorizPreview = URL.createObjectURL(file);
        brandingApi.uploadLogo('horizontal', file)
            .then(result => { brandingStore.set({ ...result }); applyBranding({ ...result }); })
            .catch(() => { brandingError = 'Logo-Upload fehlgeschlagen'; });
    }
</script>

<div class="admin-page">
    <div class="admin-header">
        <h1>Org-Admin — {$orgStore?.org_name ?? ''}</h1>
        <a href="/o/{slug}/plan" class="back-link">← Plan</a>
    </div>

    <div class="tab-bar">
        <button class="tab" class:active={activeTab === 'mitglieder'} onclick={() => { activeTab = 'mitglieder'; loadMembers(); }}>Mitglieder</button>
        <button class="tab" class:active={activeTab === 'leitstellen'} onclick={() => (activeTab = 'leitstellen')}>Leitstellen</button>
        <button class="tab" class:active={activeTab === 'branding'} onclick={() => activeTab = 'branding'}>Branding</button>
    </div>

    <!-- ── Mitglieder ── -->
    {#if activeTab === 'mitglieder'}
        {#if membersError}
            <div class="error-bar">{membersError} <button onclick={() => (membersError = '')}>✕</button></div>
        {/if}

        <div class="section">
            <div class="section-header">
                <strong>Mitglieder ({members.length})</strong>
                <div style="display:flex;gap:.4rem">
                    <button class="btn-small" onclick={() => (showInviteForm = !showInviteForm)}>+ Einladen</button>
                    <button class="btn-small" onclick={loadMembers}>↺</button>
                </div>
            </div>

            <!-- Neuen einladen (Konto anlegen + hinzufügen) -->
            {#if showInviteForm}
                <div class="invite-section">
                    <p class="invite-label">Neuen Benutzer einladen (Konto wird angelegt)</p>
                    <div class="invite-row">
                        <input type="email" placeholder="E-Mail *" bind:value={inviteForm.email} />
                        <input type="password" placeholder="Passwort *" bind:value={inviteForm.password} autocomplete="new-password" />
                        <select bind:value={inviteForm.role}>
                            <option value="beobachter">Beobachter</option>
                            <option value="fahrer">Fahrer</option>
                            <option value="planer">Planer</option>
                            <option value="admin">Admin</option>
                        </select>
                        <button class="btn-small" onclick={inviteMember} disabled={inviteWorking || !inviteForm.email || !inviteForm.password}>
                            {inviteWorking ? '…' : 'Einladen'}
                        </button>
                        <button class="btn-small" onclick={() => (showInviteForm = false)}>✕</button>
                    </div>
                </div>
            {/if}

            <!-- Bestehenden User hinzufügen -->
            <div class="add-member-row">
                <input type="email" placeholder="E-Mail (bestehendes Konto)" bind:value={addMemberForm.email} class="add-email" />
                <select bind:value={addMemberForm.role} class="add-role">
                    <option value="beobachter">Beobachter</option>
                    <option value="fahrer">Fahrer</option>
                    <option value="planer">Planer</option>
                    <option value="admin">Admin</option>
                </select>
                <button class="btn-small" onclick={addMember} disabled={addMemberWorking || !addMemberForm.email}>
                    {addMemberWorking ? '…' : '+ Hinzufügen'}
                </button>
            </div>

            {#if membersLoading}
                <p class="hint">Lade…</p>
            {:else}
                <table class="user-table">
                    <thead>
                        <tr>
                            <th>E-Mail</th>
                            <th>Rolle</th>
                            <th></th>
                        </tr>
                    </thead>
                    <tbody>
                        {#each members as m}
                            <tr>
                                <td>{m.email}</td>
                                <td>
                                    <select class="role-select-inline" value={m.role}
                                        onchange={(e) => updateRole(m.user_id, (e.target as HTMLSelectElement).value)}>
                                        <option value="beobachter">Beobachter</option>
                                        <option value="fahrer">Fahrer</option>
                                        <option value="planer">Planer</option>
                                        <option value="admin">Admin</option>
                                    </select>
                                </td>
                                <td class="actions-cell">
                                    <button class="btn-small danger" onclick={() => removeMember(m.user_id, m.email)}>✕</button>
                                </td>
                            </tr>
                        {/each}
                        {#if members.length === 0}
                            <tr><td colspan="3" class="hint" style="text-align:center">Noch keine Mitglieder.</td></tr>
                        {/if}
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
                <button class="btn-small" onclick={openCreateLs}>+ Neu</button>
            </div>

            <table class="user-table">
                <thead>
                    <tr>
                        <th>Name</th>
                        <th>Anrufgruppe</th>
                        <th>Zusatzkanäle</th>
                        <th>Grenzen</th>
                        <th></th>
                    </tr>
                </thead>
                <tbody>
                    {#each leitstellen as ls}
                        <tr>
                            <td>{ls.name}</td>
                            <td><code>{ls.anrufgruppe}</code></td>
                            <td>{ls.zusatz_kanaele.length > 0 ? ls.zusatz_kanaele.length : '–'}</td>
                            <td>{ls.has_geometry ? '✓' : '✗'}</td>
                            <td class="actions-cell">
                                <button class="btn-small" onclick={() => openEditLs(ls)}>✎</button>
                                <button class="btn-small danger" onclick={() => deleteLs(ls)}>✕</button>
                            </td>
                        </tr>
                    {/each}
                    {#if leitstellen.length === 0}
                        <tr><td colspan="5" class="hint" style="text-align:center">Noch keine Leitstellen erfasst.</td></tr>
                    {/if}
                </tbody>
            </table>
        </div>
    {/if}

    <!-- ── Branding ── -->
    {#if activeTab === 'branding'}
    <div class="branding-panel">
        <h2>Branding</h2>

        {#if brandingError}
            <div class="error-bar">{brandingError} <button onclick={() => brandingError = ''}>✕</button></div>
        {/if}
        {#if brandingSuccess}
            <div class="success-bar">Gespeichert.</div>
        {/if}

        <div class="bf-section">
            <label class="bf-label">App-Name
                <input type="text" bind:value={brandingForm.app_name} placeholder="z.B. Feuerwehr München" />
            </label>
        </div>

        <div class="bf-section">
            <h3>Logos</h3>
            <div class="logo-row">
                <div class="logo-slot">
                    <span class="bf-sublabel">Hauptlogo</span>
                    {#if logoMainPreview}
                        <img src={logoMainPreview} alt="Hauptlogo" class="logo-thumb" />
                    {/if}
                    <input type="file" accept=".png,.jpg,.jpeg,.svg" onchange={onAdminLogoMainChange} />
                </div>
                <div class="logo-slot">
                    <span class="bf-sublabel">Horizontales Logo</span>
                    {#if logoHorizPreview}
                        <img src={logoHorizPreview} alt="Horizontales Logo" class="logo-thumb" />
                    {/if}
                    <input type="file" accept=".png,.jpg,.jpeg,.svg" onchange={onAdminLogoHorizChange} />
                </div>
            </div>
        </div>

        <div class="bf-section">
            <h3>Farben</h3>
            <div class="colors-grid">
                <label class="color-label">Primärfarbe
                    <div class="color-row">
                        <input type="color" bind:value={brandingForm.color_primary} class="color-swatch" />
                        <span class="color-hex">{brandingForm.color_primary}</span>
                    </div>
                </label>
                <label class="color-label">Hover
                    <div class="color-row">
                        <input type="color" bind:value={brandingForm.color_primary_hover} class="color-swatch" />
                        <span class="color-hex">{brandingForm.color_primary_hover}</span>
                    </div>
                </label>
                <label class="color-label">Akzent
                    <div class="color-row">
                        <input type="color" bind:value={brandingForm.color_accent} class="color-swatch" />
                        <span class="color-hex">{brandingForm.color_accent}</span>
                    </div>
                </label>
                <label class="color-label">Hintergrund
                    <div class="color-row">
                        <input type="color" bind:value={brandingForm.color_bg} class="color-swatch" />
                        <span class="color-hex">{brandingForm.color_bg}</span>
                    </div>
                </label>
                <label class="color-label">Oberfläche
                    <div class="color-row">
                        <input type="color" bind:value={brandingForm.color_surface} class="color-swatch" />
                        <span class="color-hex">{brandingForm.color_surface}</span>
                    </div>
                </label>
                <label class="color-label">Nav-Hintergrund
                    <div class="color-row">
                        <input type="color" bind:value={brandingForm.color_nav_bg} class="color-swatch" />
                        <span class="color-hex">{brandingForm.color_nav_bg}</span>
                    </div>
                </label>
                <label class="color-label">Nav-Text
                    <div class="color-row">
                        <input type="color" bind:value={brandingForm.color_nav_text} class="color-swatch" />
                        <span class="color-hex">{brandingForm.color_nav_text}</span>
                    </div>
                </label>
                <label class="color-label">Text
                    <div class="color-row">
                        <input type="color" bind:value={brandingForm.color_text} class="color-swatch" />
                        <span class="color-hex">{brandingForm.color_text}</span>
                    </div>
                </label>
                <label class="color-label">Gedämpfter Text
                    <div class="color-row">
                        <input type="color" bind:value={brandingForm.color_text_muted} class="color-swatch" />
                        <span class="color-hex">{brandingForm.color_text_muted}</span>
                    </div>
                </label>
            </div>
        </div>

        <div class="bf-actions">
            <button class="btn-secondary" onclick={resetBrandingDefaults}>Defaults wiederherstellen</button>
            <button class="btn-primary" onclick={saveBranding} disabled={brandingSaving}>
                {brandingSaving ? 'Wird gespeichert…' : 'Speichern'}
            </button>
        </div>
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
    :global(body) { margin: 0; font-family: system-ui, sans-serif; background: var(--bg); color: var(--text-1); }
    .admin-page { max-width: 900px; margin: 0 auto; padding: 2rem 1rem; }
    .admin-header { display: flex; align-items: center; justify-content: space-between; margin-bottom: 1rem; }
    h1 { margin: 0; font-size: var(--text-lg); }
    .back-link { color: var(--text-2); font-size: var(--text-sm); text-decoration: none; }
    .back-link:hover { color: var(--text-1); }

    .tab-bar { display: flex; gap: .25rem; border-bottom: 1px solid var(--border); margin-bottom: 1.5rem; padding: .25rem .25rem 0; }
    .tab { padding: .5rem 1rem; background: none; border: none; cursor: pointer; font-size: var(--text-sm); color: var(--text-2); border-radius: 4px 4px 0 0; margin-bottom: -1px; }
    .tab.active { color: var(--color-primary); background: var(--surface-2); font-weight: 600; border-bottom: 2px solid var(--color-primary); }

    .error-bar { background: var(--color-primary-hover); color: white; padding: .4rem .75rem; border-radius: 4px; margin-bottom: 1rem; display: flex; justify-content: space-between; }
    .error-bar button { background: none; border: none; color: white; cursor: pointer; }
    .section { background: var(--surface-1); border: 1px solid var(--border); border-radius: 8px; padding: 1rem; margin-bottom: 1rem; box-shadow: var(--shadow); }
    .section-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: .75rem; font-size: var(--text-sm); font-weight: 500; color: var(--text-1); }

    .user-table { width: 100%; border-collapse: collapse; font-size: var(--text-sm); }
    .user-table th { text-align: left; padding: .5rem; color: var(--text-muted); font-size: var(--text-xs); text-transform: uppercase; letter-spacing: .04em; border-bottom: 1px solid var(--border); }
    .user-table td { padding: .5rem; border-bottom: 1px solid var(--border); vertical-align: middle; color: var(--text-2); }
    .actions-cell { display: flex; gap: .3rem; }
    .hint { color: var(--text-muted); font-size: var(--text-sm); }
    code { background: var(--surface-2); padding: .1rem .3rem; border-radius: 3px; font-size: var(--text-xs); font-family: monospace; color: var(--text-1); }

    .btn-small { padding: .2rem .5rem; font-size: var(--text-xs); border-radius: 3px; border: 1px solid var(--border); background: var(--surface-2); color: var(--text-2); cursor: pointer; }
    .btn-small:hover { background: var(--surface-1); }
    .btn-small.danger { border-color: var(--color-primary); color: var(--color-primary); }
    .btn-small.active { background: #e74c3c; color: white; border-color: #e74c3c; }
    .btn-primary { padding: .5rem 1rem; background: var(--color-primary); color: white; border: none; border-radius: 6px; font-weight: 600; cursor: pointer; font-size: var(--text-sm); }
    .btn-primary:disabled { opacity: .5; cursor: not-allowed; }
    .btn-primary:hover:not(:disabled) { background: var(--color-primary-hover); }

    /* Modal */
    .modal-backdrop { position: fixed; inset: 0; background: rgba(0,0,0,.6); display: flex; align-items: center; justify-content: center; z-index: 100; }
    .modal { background: var(--surface-1); border: 1px solid var(--border); border-radius: 8px; width: 600px; max-width: 95vw; max-height: 90vh; display: flex; flex-direction: column; color: var(--text-1); box-shadow: 0 8px 32px rgba(0,0,0,.3); }
    .modal-header { display: flex; justify-content: space-between; align-items: center; padding: 1rem; border-bottom: 1px solid var(--border); }
    .modal-header h2 { margin: 0; font-size: var(--text-base); }
    .modal-header button { background: none; border: none; font-size: 1.1rem; cursor: pointer; color: var(--text-muted); }
    .modal-header button:hover { color: var(--text-1); }
    .modal-body { padding: 1rem; overflow-y: auto; flex: 1; }
    .modal-footer { padding: .75rem 1rem; border-top: 1px solid var(--border); display: flex; justify-content: flex-end; gap: .5rem; }
    .ls-form { display: flex; flex-direction: column; gap: .75rem; }
    .ls-form label { display: flex; flex-direction: column; gap: .3rem; font-size: var(--text-sm); font-weight: 600; color: var(--text-2); }
    .ls-form input { padding: .5rem .75rem; border: 1px solid var(--border); border-radius: 6px; background: var(--surface-2); color: var(--text-1); font-size: var(--text-sm); font-weight: 400; }
    .ls-form input::placeholder { color: var(--text-muted); }
    .ls-form input:focus { outline: none; border-color: var(--color-primary); }
    .zusatz-section { display: flex; flex-direction: column; gap: .4rem; }
    .zusatz-header { display: flex; justify-content: space-between; align-items: center; font-size: var(--text-sm); font-weight: 600; color: var(--text-2); }
    .zusatz-row { display: flex; gap: .4rem; align-items: center; }
    .zusatz-row input { flex: 1; padding: .25rem .5rem; border: 1px solid var(--border); border-radius: 4px; background: var(--surface-2); color: var(--text-1); font-size: var(--text-sm); }
    .map-section { display: flex; flex-direction: column; gap: .4rem; font-size: var(--text-sm); font-weight: 600; color: var(--text-2); }
    .poly-controls { display: flex; gap: .4rem; font-weight: 400; }
    .poly-map { height: 280px; border-radius: 6px; overflow: hidden; border: 1px solid var(--border); }
    .import-row { display: flex; gap: .5rem; align-items: center; font-weight: 400; }
    .file-label { cursor: pointer; }

    .branding-panel { padding: 1.5rem; max-width: 700px; }
    .branding-panel h2 { margin: 0 0 1rem; font-size: var(--text-base); font-weight: 600; color: var(--text-1); }
    .branding-panel h3 { margin: 0 0 .5rem; font-size: var(--text-sm); color: var(--text-2); font-weight: 600; }
    .bf-section { margin-bottom: 1.5rem; }
    .bf-label { display: flex; flex-direction: column; gap: .25rem; font-size: var(--text-sm); color: var(--text-2); }
    .bf-label input[type="text"] { padding: .5rem .75rem; border: 1px solid var(--border); border-radius: 6px; font-size: var(--text-base); width: 100%; box-sizing: border-box; background: var(--surface-2); color: var(--text-1); }
    .bf-label input[type="text"]:focus { outline: none; border-color: var(--color-primary); }
    .bf-sublabel { font-size: var(--text-xs); color: var(--text-muted); margin-bottom: .25rem; display: block; }
    .success-bar { background: rgba(107,127,77,.15); border: 1px solid rgba(107,127,77,.4); color: #a8c070; padding: .4rem .75rem; border-radius: 4px; margin-bottom: 1rem; font-size: var(--text-sm); }
    .logo-row { display: flex; gap: 1.5rem; flex-wrap: wrap; }
    .logo-slot { display: flex; flex-direction: column; gap: .3rem; }
    .logo-thumb { max-height: 52px; max-width: 160px; border: 1px solid var(--border); border-radius: 4px; }
    .colors-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: .75rem 1rem; }
    .color-label { display: flex; flex-direction: column; gap: .25rem; font-size: var(--text-xs); color: var(--text-2); }
    .color-row { display: flex; align-items: center; gap: .4rem; }
    .color-swatch { width: 32px; height: 32px; padding: 0; border: 1px solid var(--border); border-radius: 4px; cursor: pointer; }
    .color-hex { font-size: var(--text-xs); font-family: monospace; color: var(--text-muted); }
    .bf-actions { display: flex; gap: .75rem; justify-content: flex-end; padding-top: .5rem; border-top: 1px solid var(--border); margin-top: 1rem; }
    .btn-secondary { padding: .5rem 1rem; background: transparent; color: var(--text-2); border: 1px solid var(--border); border-radius: 6px; font-weight: 600; cursor: pointer; font-size: var(--text-sm); }
    .btn-secondary:hover { background: var(--surface-2); }

    /* Mitglieder tab */
    .invite-section { background: var(--surface-2); border: 1px solid var(--border); border-radius: 6px; padding: .75rem; margin-bottom: .75rem; }
    .invite-label { margin: 0 0 .5rem; font-size: var(--text-xs); color: var(--text-muted); }
    .invite-row { display: flex; gap: .4rem; align-items: center; flex-wrap: wrap; }
    .invite-row input, .invite-row select { flex: 1; min-width: 120px; padding: .3rem .5rem; border: 1px solid var(--border); border-radius: 4px; background: var(--surface-1); color: var(--text-1); font-size: var(--text-sm); }
    .invite-row input:focus, .invite-row select:focus { outline: none; border-color: var(--color-primary); }
    .add-member-row { display: flex; gap: .4rem; align-items: center; margin-bottom: .75rem; flex-wrap: wrap; }
    .add-email { flex: 1; min-width: 160px; padding: .3rem .5rem; border: 1px solid var(--border); border-radius: 4px; background: var(--surface-2); color: var(--text-1); font-size: var(--text-sm); }
    .add-email:focus { outline: none; border-color: var(--color-primary); }
    .add-role { padding: .3rem .5rem; border: 1px solid var(--border); border-radius: 4px; background: var(--surface-2); color: var(--text-1); font-size: var(--text-sm); }
    .add-role:focus { outline: none; border-color: var(--color-primary); }
    .role-select-inline { padding: .2rem .4rem; border: 1px solid var(--border); border-radius: 4px; background: var(--surface-2); color: var(--text-1); font-size: var(--text-xs); }
    .role-select-inline:focus { outline: none; border-color: var(--color-primary); }
</style>
