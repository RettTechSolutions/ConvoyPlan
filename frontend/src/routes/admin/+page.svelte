<script lang="ts">
    import { onMount } from 'svelte';
    import { goto } from '$app/navigation';
    import maplibregl from 'maplibre-gl';
    import 'maplibre-gl/dist/maplibre-gl.css';
    import { auth } from '$lib/stores/auth';
    import { adminApi, leistellenApi, licenseApi, type AdminUser, type AdminOrg, type Leitstelle, type LeistelleDetail, type ZusatzKanal, type LicenseStatus } from '$lib/api';
    import { brandingStore, applyBranding, BRANDING_DEFAULTS } from '$lib/stores/branding';
    import { brandingApi, type BrandingUpdate } from '$lib/api';

    // ── Tab ──────────────────────────────────────────────────────────────────
    let activeTab = $state<'benutzer' | 'organisationen' | 'leitstellen' | 'branding' | 'system'>('benutzer');

    // ── Users ────────────────────────────────────────────────────────────────
    let users = $state<AdminUser[]>([]);
    let loading = $state(true);
    let error = $state('');
    let showCreateForm = $state(false);
    let newUser = $state({ email: '', password: '', is_superadmin: false });

    onMount(async () => {
        if (!$auth.is_superadmin) { goto('/'); return; }
        await loadUsers();
        await loadLeitstellen();
        await loadBranding();
    });

    // ── Edit User Modal ───────────────────────────────────────────────────────
    let showEditUserModal = $state(false);
    let editingUser = $state<AdminUser | null>(null);
    let editUserForm = $state({ email: '', password: '' });
    let editUserError = $state('');
    let editUserSaving = $state(false);
    let allOrgsForModal = $state<AdminOrg[]>([]);
    let addOrgForm = $state({ org_id: '', role: 'beobachter' });
    let addOrgWorking = $state(false);

    async function openEditUser(user: AdminUser) {
        editingUser = user;
        editUserForm = { email: user.email, password: '' };
        editUserError = '';
        addOrgForm = { org_id: '', role: 'beobachter' };
        showEditUserModal = true;
        // Load all orgs for the assignment dropdown
        try {
            allOrgsForModal = await adminApi.listOrgs();
        } catch { /* ignore */ }
    }

    async function saveEditUser() {
        if (!editingUser) return;
        editUserError = '';
        editUserSaving = true;
        try {
            const patch: { email?: string; password?: string } = {};
            if (editUserForm.email !== editingUser.email) patch.email = editUserForm.email;
            if (editUserForm.password) patch.password = editUserForm.password;
            if (Object.keys(patch).length > 0) {
                await adminApi.updateUser(editingUser.id, patch);
            }
            showEditUserModal = false;
            await loadUsers();
        } catch (e: unknown) {
            editUserError = e instanceof Error ? e.message : 'Fehler beim Speichern';
        } finally {
            editUserSaving = false;
        }
    }

    async function addUserToOrg() {
        if (!editingUser || !addOrgForm.org_id) return;
        addOrgWorking = true;
        editUserError = '';
        try {
            await adminApi.addUserToOrg(editingUser.id, addOrgForm.org_id, addOrgForm.role);
            // Refresh user list so modal reflects new membership
            await loadUsers();
            // Update editingUser reference from the refreshed list
            const updated = users.find(u => u.id === editingUser!.id);
            if (updated) editingUser = updated;
            addOrgForm = { org_id: '', role: 'beobachter' };
        } catch (e: unknown) {
            editUserError = e instanceof Error ? e.message : 'Fehler beim Zuordnen';
        } finally {
            addOrgWorking = false;
        }
    }

    async function removeUserFromOrg(orgId: string) {
        if (!editingUser) return;
        editUserError = '';
        try {
            await adminApi.removeUserFromOrg(editingUser.id, orgId);
            await loadUsers();
            const updated = users.find(u => u.id === editingUser!.id);
            if (updated) editingUser = updated;
        } catch (e: unknown) {
            editUserError = e instanceof Error ? e.message : 'Fehler beim Entfernen';
        }
    }

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

    // ── Organisationen ───────────────────────────────────────────────────────
    let orgs = $state<AdminOrg[]>([]);
    let orgsLoading = $state(false);
    let orgsError = $state('');

    async function loadOrgs() {
        orgsLoading = true;
        orgsError = '';
        try {
            orgs = await adminApi.listOrgs();
        } catch { orgsError = 'Organisationen konnten nicht geladen werden'; }
        finally { orgsLoading = false; }
    }

    async function deleteOrg(org: AdminOrg) {
        if (!confirm(`Organisation "${org.name}" (${org.slug}) wirklich löschen?\n\nAlle Mitglieder-Zuordnungen und Daten dieser Organisation werden entfernt.`)) return;
        try {
            await adminApi.deleteOrg(org.id);
            await loadOrgs();
        } catch { orgsError = 'Organisation konnte nicht gelöscht werden'; }
    }

    // Create org
    let showCreateOrgModal = $state(false);
    let createOrgForm = $state({ name: '', slug: '', slugManual: false });
    let createOrgError = $state('');
    let createOrgSaving = $state(false);

    function autoSlug(name: string): string {
        const norm = name
            .replace(/ä/g, 'ae').replace(/ö/g, 'oe').replace(/ü/g, 'ue').replace(/ß/g, 'ss');
        const words = norm.match(/[a-zA-Z0-9]+/g) ?? [];
        let code = words.map(w => w.slice(0, 2)).join('').toLowerCase().slice(0, 8);
        if (code.length < 2) code = norm.toLowerCase().replace(/[^a-z0-9]/g, '').slice(0, 4);
        return code;
    }

    function onOrgNameInput() {
        if (!createOrgForm.slugManual) {
            createOrgForm.slug = autoSlug(createOrgForm.name);
        }
    }

    async function createOrg() {
        createOrgError = '';
        createOrgSaving = true;
        try {
            await adminApi.createOrg({ name: createOrgForm.name.trim(), slug: createOrgForm.slug.trim() });
            showCreateOrgModal = false;
            createOrgForm = { name: '', slug: '', slugManual: false };
            await loadOrgs();
        } catch (e: unknown) {
            createOrgError = e instanceof Error ? e.message : 'Fehler beim Anlegen';
        } finally {
            createOrgSaving = false;
        }
    }

    // ── Leitstellen ──────────────────────────────────────────────────────────
    let leitstellen = $state<Leitstelle[]>([]);
    let lsError = $state('');
    let showLsModal = $state(false);
    let editingLs = $state<LeistelleDetail | null>(null);
    let lsForm = $state({ name: '', anrufgruppe: '', zusatz_kanaele: [] as ZusatzKanal[] });

    // ── Lizenz ───────────────────────────────────────────────────────────────────
    let licenseStatus = $state<LicenseStatus | null>(null);
    let licenseLoading = $state(false);
    let licenseError = $state('');
    let licenseSuccess = $state('');
    let licenseKeyInput = $state('');
    let licenseActivating = $state(false);
    let licenseRemoving = $state(false);
    let showLicenseKey = $state(false);

    async function removeLicense() {
        if (!confirm('Lizenz wirklich entfernen? Die Installation wechselt zurück in den Demo-Modus.')) return;
        licenseRemoving = true;
        licenseError = '';
        try {
            await licenseApi.remove();
            licenseStatus = await licenseApi.getStatus();
            licenseSuccess = 'Lizenz entfernt. Demo-Modus aktiv.';
            setTimeout(() => { licenseSuccess = ''; }, 5000);
        } catch (e: unknown) {
            licenseError = e instanceof Error ? e.message : 'Lizenz konnte nicht entfernt werden';
        } finally {
            licenseRemoving = false;
        }
    }

    async function loadLicenseStatus() {
        licenseLoading = true;
        licenseError = '';
        try {
            licenseStatus = await licenseApi.getStatus();
        } catch {
            licenseError = 'Lizenzstatus konnte nicht geladen werden';
        } finally {
            licenseLoading = false;
        }
    }

    async function activateLicense() {
        licenseError = '';
        licenseSuccess = '';
        if (!licenseKeyInput.trim()) return;
        licenseActivating = true;
        try {
            licenseStatus = await licenseApi.activate(licenseKeyInput.trim());
            licenseKeyInput = '';
            licenseSuccess = `Lizenz aktiviert für ${licenseStatus.customer ?? 'Unbekannt'}`;
            setTimeout(() => { licenseSuccess = ''; }, 5000);
        } catch (e: unknown) {
            licenseError = e instanceof Error ? e.message : 'Ungültiger Lizenzschlüssel';
        } finally {
            licenseActivating = false;
        }
    }

    // ── System / Update ──────────────────────────────────────────────────────────
    let updateStatus = $state<import('$lib/api').UpdateStatus | null>(null);
    let updateLoading = $state(false);
    let updateTriggering = $state(false);
    let updateError = $state('');
    let updateSuccess = $state('');

    async function loadUpdateStatus() {
        updateLoading = true;
        updateError = '';
        try {
            updateStatus = await adminApi.getUpdateStatus();
        } catch {
            updateError = 'Status konnte nicht geladen werden';
        } finally {
            updateLoading = false;
        }
    }

    async function triggerUpdate() {
        updateError = '';
        updateSuccess = '';
        updateTriggering = true;
        try {
            await adminApi.triggerUpdate();
        } catch (e: unknown) {
            const msg = e instanceof Error ? e.message : 'Fehler beim Trigger';
            if (msg.includes('409') || msg.includes('already')) {
                updateError = 'Update läuft bereits';
            } else {
                updateError = msg;
            }
            updateTriggering = false;
            return;
        }

        // Poll every 3s until deployed_sha changes or 3min timeout
        const startSha = updateStatus?.deployed_sha ?? null;
        const deadline = Date.now() + 3 * 60 * 1000;
        const poll = async () => {
            if (Date.now() > deadline) {
                updateTriggering = false;
                updateError = 'Timeout — bitte Server-Logs prüfen';
                return;
            }
            try {
                const fresh = await adminApi.getUpdateStatus();
                updateStatus = fresh;
                if (!fresh.update_available && fresh.deployed_sha !== startSha) {
                    updateTriggering = false;
                    updateSuccess = `Aktualisiert auf ${fresh.deployed_sha?.slice(0, 7) ?? '?'}`;
                    return;
                }
            } catch { /* ignore transient errors during polling */ }
            setTimeout(poll, 3000);
        };
        setTimeout(poll, 3000);
    }

    // ── GitHub-Token Konfiguration ────────────────────────────────────────────
    let githubTokenSet = $state<{ set: boolean; source: string | null } | null>(null);
    let githubTokenInput = $state('');
    let githubTokenSaving = $state(false);
    let githubTokenSuccess = $state('');
    let githubTokenError = $state('');
    let showGithubToken = $state(false);

    async function loadGithubTokenStatus() {
        try {
            githubTokenSet = await adminApi.getGithubTokenStatus();
        } catch { /* ignore */ }
    }

    async function saveGithubToken() {
        if (!githubTokenInput.trim()) return;
        githubTokenSaving = true;
        githubTokenError = '';
        githubTokenSuccess = '';
        try {
            await adminApi.setGithubToken(githubTokenInput.trim());
            githubTokenSet = { set: true, source: 'db' };
            githubTokenInput = '';
            githubTokenSuccess = 'Token gespeichert. GitHub-Check wird beim nächsten Laden aktiv.';
            setTimeout(() => { githubTokenSuccess = ''; }, 5000);
        } catch (e: unknown) {
            githubTokenError = e instanceof Error ? e.message : 'Fehler beim Speichern';
        } finally {
            githubTokenSaving = false;
        }
    }

    async function clearGithubToken() {
        if (!confirm('GitHub-Token entfernen?')) return;
        githubTokenSaving = true;
        try {
            await adminApi.setGithubToken('');
            githubTokenSet = { set: false, source: null };
            githubTokenSuccess = 'Token entfernt.';
            setTimeout(() => { githubTokenSuccess = ''; }, 3000);
        } catch { githubTokenError = 'Fehler beim Entfernen'; }
        finally { githubTokenSaving = false; }
    }

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
        <h1>Admin</h1>
        <a href="/plan" class="back-link">← Plan</a>
    </div>

    <div class="tab-bar">
        <button class="tab" class:active={activeTab === 'benutzer'} onclick={() => (activeTab = 'benutzer')}>Benutzer</button>
        <button class="tab" class:active={activeTab === 'organisationen'} onclick={() => { activeTab = 'organisationen'; loadOrgs(); }}>Organisationen</button>
        <button class="tab" class:active={activeTab === 'leitstellen'} onclick={() => (activeTab = 'leitstellen')}>Leitstellen</button>
        <button class="tab" class:active={activeTab === 'branding'} onclick={() => activeTab = 'branding'}>Branding</button>
        <button class="tab" class:active={activeTab === 'system'} onclick={() => { activeTab = 'system'; loadUpdateStatus(); loadLicenseStatus(); loadGithubTokenStatus(); }}>System</button>
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
                                <td>
                                    <div class="orgs-cell">
                                        {#each user.orgs as org}
                                            <span class="tag">{org.name} ({org.role})</span>
                                        {/each}
                                        {#if user.orgs.length === 0}
                                            <span class="hint">—</span>
                                        {/if}
                                    </div>
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
                                <td class="actions-cell">
                                    <div><button class="btn-small" onclick={() => openEditUser(user)} title="Bearbeiten">✎</button>
                                    <button class="btn-small danger" onclick={() => deleteUser(user)} title="Löschen">🗑</button></div>
                                </td>
                            </tr>
                        {/each}
                    </tbody>
                </table>
            {/if}
        </div>
    {/if}

    <!-- ── Organisationen ── -->
    {#if activeTab === 'organisationen'}
        {#if orgsError}
            <div class="error-bar">{orgsError} <button onclick={() => (orgsError = '')}>✕</button></div>
        {/if}

        <div class="section">
            <div class="section-header">
                <strong>Organisationen ({orgs.length})</strong>
                <div style="display:flex;gap:.4rem">
                    <button class="btn-small" onclick={() => { createOrgForm = { name: '', slug: '', slugManual: false }; createOrgError = ''; showCreateOrgModal = true; }}>+ Neu</button>
                    <button class="btn-small" onclick={loadOrgs}>↺</button>
                </div>
            </div>

            {#if orgsLoading}
                <p class="hint">Lade…</p>
            {:else}
                <table class="user-table">
                    <thead>
                        <tr>
                            <th>Name</th>
                            <th>Code (Slug)</th>
                            <th>Inhaber</th>
                            <th>Mitglieder</th>
                            <th></th>
                        </tr>
                    </thead>
                    <tbody>
                        {#each orgs as org}
                            <tr>
                                <td>{org.name}</td>
                                <td><code>{org.slug}</code></td>
                                <td class="hint">{org.owner_email ?? '–'}</td>
                                <td>{org.member_count}</td>
                                <td class="actions-cell">
                                    <div><button class="btn-small danger" onclick={() => deleteOrg(org)} title="Löschen">🗑</button></div>
                                </td>
                            </tr>
                        {/each}
                        {#if orgs.length === 0}
                            <tr><td colspan="5" class="hint" style="text-align:center">Keine Organisationen vorhanden.</td></tr>
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
                                    <div><button class="btn-small" onclick={() => openEditLs(ls)}>✎</button>
                                    <button class="btn-small danger" onclick={() => deleteLs(ls)}>✕</button></div>
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

    {#if activeTab === 'system'}
        <!-- ── Lizenz-Sektion ── -->
        <div class="section">
            <div class="section-header">
                <strong>Lizenz</strong>
                <button class="btn-small" onclick={loadLicenseStatus}>↺</button>
            </div>

            {#if licenseError}
                <div class="error-bar">{licenseError} <button onclick={() => licenseError = ''}>✕</button></div>
            {/if}
            {#if licenseSuccess}
                <div class="success-bar">{licenseSuccess}</div>
            {/if}

            {#if licenseLoading}
                <p class="hint">Lade…</p>
            {:else if licenseStatus}
                <!-- Status-Badge -->
                <div class="license-status-row">
                    {#if licenseStatus.valid}
                        <span class="badge badge-ok">Lizenziert ✓</span>
                        <span class="hint" style="margin-left:.5rem">{licenseStatus.customer ?? ''}</span>
                        <button
                            class="btn-danger-small"
                            onclick={removeLicense}
                            disabled={licenseRemoving}
                            style="margin-left:auto"
                        >
                            {licenseRemoving ? '…' : 'Lizenz entfernen'}
                        </button>
                    {:else}
                        <span class="badge badge-warn">Demo-Modus — keine gültige Lizenz</span>
                    {/if}
                </div>

                <!-- Lizenz-Details wenn aktiv -->
                {#if licenseStatus.valid}
                    <div class="update-grid" style="margin-top:.75rem">
                        {#if licenseStatus.customer}
                            <div class="update-row">
                                <span class="update-label">Kunde</span>
                                <span>{licenseStatus.customer}</span>
                            </div>
                        {/if}
                        {#if licenseStatus.expires}
                            <div class="update-row">
                                <span class="update-label">Gültig bis</span>
                                <span>{licenseStatus.expires}</span>
                            </div>
                        {/if}
                        {#if licenseStatus.max_users}
                            <div class="update-row">
                                <span class="update-label">Max. Benutzer</span>
                                <span>{licenseStatus.max_users}</span>
                            </div>
                        {/if}
                        {#if licenseStatus.license_id}
                            <div class="update-row">
                                <span class="update-label">Lizenz-ID</span>
                                <code>{licenseStatus.license_id}</code>
                            </div>
                        {/if}
                    </div>
                {/if}

                <!-- Instanz-UUID -->
                <div class="update-grid" style="margin-top:.75rem">
                    <div class="update-row">
                        <span class="update-label">Instanz-UUID</span>
                        <code class="uuid-code">{licenseStatus.instance_id}</code>
                        <button class="btn-small" onclick={() => navigator.clipboard.writeText(licenseStatus!.instance_id)} title="Kopieren">⎘</button>
                    </div>
                </div>

                <!-- Lizenzschlüssel eingeben -->
                <div class="license-input-section">
                    <label class="license-input-label">
                        {licenseStatus.valid ? 'Lizenzschlüssel ersetzen' : 'Lizenzschlüssel eingeben'}
                    </label>
                    <div class="license-input-row">
                        <input
                            type={showLicenseKey ? 'text' : 'password'}
                            class="license-input"
                            placeholder="eyJ…"
                            bind:value={licenseKeyInput}
                            onkeydown={(e) => { if (e.key === 'Enter') activateLicense(); }}
                        />
                        <button class="btn-small" onclick={() => showLicenseKey = !showLicenseKey} title="Anzeigen/Verstecken">
                            {showLicenseKey ? '🙈' : '👁'}
                        </button>
                        <button
                            class="btn-primary"
                            onclick={activateLicense}
                            disabled={licenseActivating || !licenseKeyInput.trim()}
                        >
                            {licenseActivating ? '…' : 'Aktivieren'}
                        </button>
                    </div>
                    {#if !licenseStatus.valid}
                        <p class="hint" style="margin-top:.4rem">
                            Im Demo-Modus sind Schreiboperationen gesperrt. Geben Sie die Instanz-UUID an den Entwickler weiter, um einen Lizenzschlüssel zu erhalten.
                        </p>
                    {/if}
                </div>
            {:else}
                <p class="hint">Lizenzstatus nicht verfügbar</p>
            {/if}
        </div>

        <!-- ── Software-Update ── -->
        <div class="section">
            <div class="section-header">
                <strong>Software-Update</strong>
                {#if !updateTriggering}
                    <button class="btn-small" onclick={loadUpdateStatus}>↺ Aktualisieren</button>
                {/if}
            </div>

            {#if updateError}
                <div class="error-bar">{updateError} <button onclick={() => updateError = ''}>✕</button></div>
            {/if}
            {#if updateSuccess}
                <div class="success-bar">{updateSuccess}</div>
            {/if}

            {#if updateLoading}
                <p class="hint">Lade Status…</p>
            {:else if updateStatus}
                <div class="update-grid">
                    <div class="update-row">
                        <span class="update-label">Installiert</span>
                        <code>{updateStatus.deployed_sha?.slice(0, 7) ?? '—'}</code>
                        {#if updateStatus.deployed_at}
                            <span class="hint">{new Date(updateStatus.deployed_at).toLocaleString('de-DE')}</span>
                        {/if}
                    </div>
                    <div class="update-row">
                        <span class="update-label">GitHub (main)</span>
                        {#if updateStatus.github_reachable}
                            <code>{updateStatus.remote_sha?.slice(0, 7) ?? '—'}</code>
                        {:else}
                            <span class="hint">nicht erreichbar</span>
                        {/if}
                    </div>
                    <div class="update-row">
                        <span class="update-label">Status</span>
                        {#if !updateStatus.github_reachable}
                            <span class="badge badge-warn">GitHub nicht erreichbar</span>
                        {:else if updateStatus.update_available}
                            <span class="badge badge-update">Update verfügbar ↑</span>
                        {:else}
                            <span class="badge badge-ok">Aktuell ✓</span>
                        {/if}
                    </div>
                </div>

                <div style="margin-top: 1rem; display:flex; align-items:center; gap:.75rem; flex-wrap:wrap;">
                    {#if updateTriggering}
                        <button class="btn-primary" disabled>
                            <span class="spinner"></span> Update wird durchgeführt…
                        </button>
                    {:else if updateStatus.github_reachable}
                        <!-- GitHub erreichbar: Button nur aktiv wenn Update vorhanden -->
                        <button
                            class="btn-primary"
                            disabled={!updateStatus.update_available}
                            onclick={triggerUpdate}
                        >
                            Jetzt updaten
                        </button>
                    {:else}
                        <!-- GitHub nicht erreichbar: Manuelles Auslösen immer erlaubt -->
                        <button class="btn-primary" onclick={triggerUpdate}>
                            Manuell aktualisieren
                        </button>
                        <span class="hint" style="font-size:var(--text-xs)">GitHub nicht erreichbar — zieht trotzdem neueste Images</span>
                    {/if}
                </div>
            {:else}
                <p class="hint">Status nicht verfügbar</p>
            {/if}
        </div>

        <!-- ── GitHub-Konfiguration ── -->
        <div class="section">
            <div class="section-header">
                <strong>GitHub-Konfiguration</strong>
            </div>

            {#if githubTokenError}
                <div class="error-bar">{githubTokenError} <button onclick={() => githubTokenError = ''}>✕</button></div>
            {/if}
            {#if githubTokenSuccess}
                <div class="success-bar">{githubTokenSuccess}</div>
            {/if}

            <div class="update-grid" style="margin-bottom:.75rem">
                <div class="update-row">
                    <span class="update-label">GitHub-Token</span>
                    {#if githubTokenSet?.set}
                        <span class="badge badge-ok">Gesetzt ({githubTokenSet.source === 'env' ? 'Umgebungsvariable' : 'Datenbank'}) ✓</span>
                        {#if githubTokenSet.source === 'db'}
                            <button class="btn-small danger" onclick={clearGithubToken} disabled={githubTokenSaving}>Entfernen</button>
                        {/if}
                    {:else}
                        <span class="badge badge-warn">Nicht konfiguriert</span>
                    {/if}
                </div>
            </div>

            <p class="hint" style="margin-bottom:.6rem">
                Ohne GitHub-Token ist die GitHub-API auf 60 Requests/Stunde limitiert.
                Token erstellen unter <a href="https://github.com/settings/tokens" target="_blank" rel="noopener" style="color:var(--color-primary)">github.com/settings/tokens</a>
                (nur <code>public_repo</code> Scope nötig).
            </p>

            <div class="license-input-row">
                <input
                    type={showGithubToken ? 'text' : 'password'}
                    class="license-input"
                    placeholder={githubTokenSet?.set ? '••• Token ersetzen •••' : 'ghp_xxxxxxxxxxxx'}
                    bind:value={githubTokenInput}
                    onkeydown={(e) => { if (e.key === 'Enter') saveGithubToken(); }}
                    autocomplete="off"
                />
                <button class="btn-small" onclick={() => showGithubToken = !showGithubToken} title="Anzeigen/Verstecken">
                    {showGithubToken ? '🙈' : '👁'}
                </button>
                <button
                    class="btn-primary"
                    onclick={saveGithubToken}
                    disabled={githubTokenSaving || !githubTokenInput.trim()}
                >
                    {githubTokenSaving ? '…' : 'Speichern'}
                </button>
            </div>
        </div>
    {/if}
</div>

<!-- ── Benutzer bearbeiten Modal ── -->
{#if showEditUserModal && editingUser}
    <div class="modal-backdrop" onclick={() => (showEditUserModal = false)}>
        <div class="modal" onclick={(e) => e.stopPropagation()}>
            <div class="modal-header">
                <h2>Benutzer bearbeiten</h2>
                <button onclick={() => (showEditUserModal = false)}>✕</button>
            </div>
            <div class="modal-body">
                {#if editUserError}
                    <div class="error-bar" style="margin-bottom:.75rem">{editUserError} <button onclick={() => (editUserError = '')}>✕</button></div>
                {/if}

                <!-- Zugangsdaten -->
                <div class="edit-section">
                    <p class="edit-section-title">Zugangsdaten</p>
                    <div class="ls-form">
                        <label>E-Mail
                            <input type="email" bind:value={editUserForm.email} placeholder="E-Mail" required />
                        </label>
                        <label>Neues Passwort <span class="hint" style="font-weight:400">(leer = nicht ändern)</span>
                            <input type="password" bind:value={editUserForm.password} placeholder="Neues Passwort" autocomplete="new-password" />
                        </label>
                    </div>
                </div>

                <!-- Organisationen -->
                <div class="edit-section">
                    <p class="edit-section-title">Organisationen</p>

                    <!-- Bestehende Mitgliedschaften -->
                    {#if editingUser.orgs.length > 0}
                        <div class="org-memberships">
                            {#each editingUser.orgs as org}
                                <div class="org-membership-row">
                                    <span class="org-name">{org.name}</span>
                                    <span class="tag">{org.role}</span>
                                    <button class="btn-small danger" onclick={() => removeUserFromOrg(org.id)} title="Entfernen">✕</button>
                                </div>
                            {/each}
                        </div>
                    {:else}
                        <p class="hint" style="margin-bottom:.5rem">Noch keiner Organisation zugeordnet.</p>
                    {/if}

                    <!-- Neue Zuordnung -->
                    {#if allOrgsForModal.length > 0}
                        {@const availableOrgs = allOrgsForModal.filter(o => !editingUser!.orgs.some(m => m.id === o.id))}
                        {#if availableOrgs.length > 0}
                            <div class="add-org-row">
                                <select bind:value={addOrgForm.org_id} class="org-select">
                                    <option value="">Organisation wählen…</option>
                                    {#each availableOrgs as o}
                                        <option value={o.id}>{o.name} ({o.slug})</option>
                                    {/each}
                                </select>
                                <select bind:value={addOrgForm.role} class="role-select">
                                    <option value="beobachter">Beobachter</option>
                                    <option value="fahrer">Fahrer</option>
                                    <option value="planer">Planer</option>
                                    <option value="admin">Admin</option>
                                </select>
                                <button class="btn-small" onclick={addUserToOrg} disabled={addOrgWorking || !addOrgForm.org_id}>
                                    {addOrgWorking ? '…' : '+ Zuordnen'}
                                </button>
                            </div>
                        {/if}
                    {/if}
                </div>
            </div>
            <div class="modal-footer">
                <button onclick={() => (showEditUserModal = false)}>Schließen</button>
                <button class="btn-primary" onclick={saveEditUser} disabled={editUserSaving || !editUserForm.email}>
                    {editUserSaving ? 'Speichern…' : 'Zugangsdaten speichern'}
                </button>
            </div>
        </div>
    </div>
{/if}

<!-- ── Organisation anlegen Modal ── -->
{#if showCreateOrgModal}
    <div class="modal-backdrop" onclick={() => (showCreateOrgModal = false)}>
        <div class="modal" style="max-width:440px" onclick={(e) => e.stopPropagation()}>
            <div class="modal-header">
                <h2>Organisation anlegen</h2>
                <button onclick={() => (showCreateOrgModal = false)}>✕</button>
            </div>
            <div class="modal-body">
                {#if createOrgError}
                    <div class="error-bar" style="margin-bottom:.75rem">{createOrgError} <button onclick={() => (createOrgError = '')}>✕</button></div>
                {/if}
                <div class="ls-form">
                    <label>Name *
                        <input
                            type="text"
                            bind:value={createOrgForm.name}
                            placeholder="z.B. Johanniter Peißenberg"
                            oninput={onOrgNameInput}
                            required
                        />
                    </label>
                    <label>Code (Slug) *
                        <input
                            type="text"
                            bind:value={createOrgForm.slug}
                            placeholder="z.B. jpbg"
                            maxlength="8"
                            oninput={(e) => {
                                createOrgForm.slugManual = true;
                                createOrgForm.slug = (e.target as HTMLInputElement).value
                                    .toLowerCase().replace(/[^a-z0-9-]/g, '');
                            }}
                            required
                        />
                        <span class="hint" style="font-weight:400;margin-top:.15rem">4–8 Zeichen, wie bei HiOrg (wird automatisch aus dem Namen generiert)</span>
                    </label>
                </div>
            </div>
            <div class="modal-footer">
                <button onclick={() => (showCreateOrgModal = false)}>Abbrechen</button>
                <button class="btn-primary" onclick={createOrg}
                    disabled={createOrgSaving || !createOrgForm.name.trim() || !createOrgForm.slug.trim()}>
                    {createOrgSaving ? 'Anlegen…' : 'Organisation anlegen'}
                </button>
            </div>
        </div>
    </div>
{/if}

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

    .create-form { display: flex; flex-direction: column; gap: .5rem; margin-bottom: 1rem; padding: .75rem; background: var(--surface-2); border-radius: 6px; border: 1px solid var(--border); }
    .create-form input { padding: .5rem .75rem; border-radius: 6px; border: 1px solid var(--border); background: var(--surface-1); color: var(--text-1); font-size: var(--text-sm); }
    .create-form input:focus { outline: none; border-color: var(--color-primary); }
    .create-form button { align-self: flex-start; padding: .5rem 1rem; background: #6B7F4D; color: white; border: none; border-radius: 6px; cursor: pointer; font-weight: 600; font-size: var(--text-sm); }
    .checkbox-label { display: flex; align-items: center; gap: .4rem; font-size: var(--text-sm); color: var(--text-2); cursor: pointer; }
    .user-table { width: 100%; border-collapse: collapse; font-size: var(--text-sm); }
    .user-table th { text-align: left; padding: .5rem; color: var(--text-muted); font-size: var(--text-xs); text-transform: uppercase; letter-spacing: .04em; border-bottom: 1px solid var(--border); }
    .user-table td { padding: .5rem; border-bottom: 1px solid var(--border); vertical-align: middle; color: var(--text-2); }
    .user-table tr.inactive td { opacity: .45; }
    .orgs-cell { display: flex; flex-wrap: wrap; gap: .25rem; align-items: center; min-height: 1.4rem; }
    .tag { display: inline-block; padding: .1rem .35rem; background: var(--surface-2); border: 1px solid var(--border); border-radius: 3px; font-size: var(--text-xs); color: var(--text-2); }
    .toggle-btn { padding: .2rem .5rem; border-radius: 3px; border: 1px solid var(--border); background: var(--surface-2); color: var(--text-2); font-size: var(--text-xs); cursor: pointer; }
    .toggle-btn.on { background: rgba(107,127,77,.3); border-color: #6B7F4D; color: #a8c070; }
    .actions-cell { white-space: nowrap; }
    .actions-cell > div { display: flex; gap: .3rem; }
    .hint { color: var(--text-muted); font-size: var(--text-sm); }
    code { background: var(--surface-2); padding: .1rem .3rem; border-radius: 3px; font-size: var(--text-xs); font-family: monospace; color: var(--text-1); }

    .btn-small { padding: .2rem .5rem; font-size: var(--text-xs); border-radius: 3px; border: 1px solid var(--border); background: var(--surface-2); color: var(--text-2); cursor: pointer; }
    .btn-small:hover { background: var(--surface-1); }
    .btn-small.danger { border-color: var(--color-primary); color: var(--color-primary); }
    .btn-small.active { background: #e74c3c; color: white; border-color: #e74c3c; }
    .btn-primary { padding: .5rem 1rem; background: var(--color-primary); color: white; border: none; border-radius: 6px; font-weight: 600; cursor: pointer; font-size: var(--text-sm); }
    .btn-primary:disabled { opacity: .5; cursor: not-allowed; }
    .btn-primary:hover:not(:disabled) { background: var(--color-primary-hover); }
    .btn-danger-small { padding: .2rem .6rem; font-size: var(--text-xs); border-radius: 3px; border: 1px solid #e74c3c; background: transparent; color: #e74c3c; cursor: pointer; }
    .btn-danger-small:hover:not(:disabled) { background: #e74c3c; color: white; }
    .btn-danger-small:disabled { opacity: .5; cursor: not-allowed; }

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
    .update-grid { display: flex; flex-direction: column; gap: .6rem; }
    .update-row { display: flex; align-items: center; gap: .75rem; font-size: var(--text-sm); }
    .update-label { width: 130px; color: var(--text-muted); font-size: var(--text-xs); text-transform: uppercase; letter-spacing: .04em; flex-shrink: 0; }
    .badge { display: inline-block; padding: .15rem .5rem; border-radius: 3px; font-size: var(--text-xs); font-weight: 600; }
    .badge-ok { background: rgba(107,127,77,.2); color: #a8c070; border: 1px solid rgba(107,127,77,.4); }
    .badge-update { background: rgba(210,120,30,.2); color: #e8a050; border: 1px solid rgba(210,120,30,.4); }
    .badge-warn { background: rgba(180,60,40,.15); color: var(--color-primary); border: 1px solid rgba(180,60,40,.3); }
    .spinner { display: inline-block; width: 12px; height: 12px; border: 2px solid rgba(255,255,255,.3); border-top-color: white; border-radius: 50%; animation: spin .7s linear infinite; vertical-align: middle; margin-right: .3rem; }
    @keyframes spin { to { transform: rotate(360deg); } }

    .license-status-row { display: flex; align-items: center; margin-bottom: .25rem; }
    .uuid-code { font-size: var(--text-xs); font-family: monospace; word-break: break-all; background: var(--surface-2); padding: .1rem .3rem; border-radius: 3px; color: var(--text-1); }
    .license-input-section { margin-top: 1rem; padding-top: .75rem; border-top: 1px solid var(--border); display: flex; flex-direction: column; gap: .3rem; }
    .license-input-label { font-size: var(--text-xs); font-weight: 600; color: var(--text-muted); text-transform: uppercase; letter-spacing: .04em; }
    .license-input-row { display: flex; gap: .4rem; align-items: center; }
    .license-input { flex: 1; padding: .45rem .65rem; border: 1px solid var(--border); border-radius: 6px; background: var(--surface-2); color: var(--text-1); font-size: var(--text-sm); font-family: monospace; }
    .license-input:focus { outline: none; border-color: var(--color-primary); }

    /* Edit user modal */
    .edit-section { margin-bottom: 1.25rem; }
    .edit-section:last-child { margin-bottom: 0; }
    .edit-section-title { font-size: var(--text-xs); font-weight: 600; color: var(--text-muted); text-transform: uppercase; letter-spacing: .05em; margin: 0 0 .6rem; }
    .org-memberships { display: flex; flex-direction: column; gap: .3rem; margin-bottom: .5rem; }
    .org-membership-row { display: flex; align-items: center; gap: .5rem; padding: .3rem .5rem; background: var(--surface-2); border-radius: 4px; border: 1px solid var(--border); }
    .org-name { flex: 1; font-size: var(--text-sm); color: var(--text-1); }
    .add-org-row { display: flex; gap: .4rem; align-items: center; margin-top: .3rem; flex-wrap: wrap; }
    .org-select { flex: 1; min-width: 140px; padding: .35rem .5rem; border: 1px solid var(--border); border-radius: 4px; background: var(--surface-2); color: var(--text-1); font-size: var(--text-sm); }
    .role-select { padding: .35rem .5rem; border: 1px solid var(--border); border-radius: 4px; background: var(--surface-2); color: var(--text-1); font-size: var(--text-sm); }
    .org-select:focus, .role-select:focus { outline: none; border-color: var(--color-primary); }
</style>
