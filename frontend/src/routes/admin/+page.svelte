<script lang="ts">
    import { onMount } from 'svelte';
    import LeitstelleAreaPicker, { type AreaSelection } from '$lib/components/LeitstelleAreaPicker.svelte';
    import LeitstellenOverviewMap from '$lib/components/LeitstellenOverviewMap.svelte';
    import LeitstellenTable from '$lib/components/LeitstellenTable.svelte';
    import { auth } from '$lib/stores/auth';
    import { getStreamTicket } from '$lib/api/client';
    import { adminApi, mfaApi, leistellenApi, licenseApi, emailTemplateApi, type AdminUser, type AdminUserCreate, type AdminOrg, type Leitstelle, type LeistelleDetail, type ZusatzKanal, type LicenseStatus, type SmtpConfig, type SmtpConfigResponse, type EmailTemplate, type ApiKey, type ApiKeyCreated, type DemoSettings, type DemoSessionInfo } from '$lib/api';
    import { brandingStore, applyBranding, BRANDING_DEFAULTS } from '$lib/stores/branding';
    import { brandingApi, type BrandingUpdate } from '$lib/api';
    import SuperadminLogin from '$lib/components/SuperadminLogin.svelte';
    import QRCode from 'qrcode';

    // ── Auth gate ──────────────────────────────────────────────────────────────
    // /admin is self-gated: when not logged in as a superadmin we render the
    // login form inline and only load the portal once authenticated.
    let authed = $state(false);

    // ── Tab ──────────────────────────────────────────────────────────────────
    let activeTab = $state<'benutzer' | 'organisationen' | 'api-keys' | 'leitstellen' | 'branding' | 'system'>('benutzer');

    // ── Users ────────────────────────────────────────────────────────────────
    let users = $state<AdminUser[]>([]);
    // Reguläre Benutzer zuerst, Demo-Sitzungen als abgesetzte Gruppe darunter
    const sortedUsers = $derived([...users.filter(u => !u.is_demo), ...users.filter(u => u.is_demo)]);
    const demoUserCount = $derived(users.filter(u => u.is_demo).length);
    let loading = $state(true);
    let error = $state('');
    let showCreateForm = $state(false);
    let newUser = $state({ email: '', first_name: '', last_name: '', is_superadmin: false, org_id: '', org_role: 'beobachter' });
    let createOrgs = $state<AdminOrg[]>([]);
    let createAndEmailWorking = $state(false);

    /** Load orgs for the create-user org dropdown (once). */
    async function loadCreateOrgs() {
        if (createOrgs.length) return;
        try {
            createOrgs = await adminApi.listOrgs();
        } catch { /* ignore — dropdown just stays empty */ }
    }

    function toggleCreateForm() {
        showCreateForm = !showCreateForm;
        if (showCreateForm) loadCreateOrgs();
    }

    onMount(async () => {
        if ($auth.is_superadmin) {
            authed = true;
            await initPortal();
        }
    });

    /** Load all portal data — called on mount (if already authed) and after login. */
    async function initPortal() {
        await loadUsers();
        await loadLeitstellen();
        await loadBranding();
        await Promise.all([loadGithubTokenStatus(), loadTrafficKeys(), loadUpdateStatus(), loadUpdateChannel(), loadUpdateMode(), loadMfaStatus(), loadSmtpSettings(), loadEmailTemplate(), loadDemoSettings()]);
    }

    async function handleAuthenticated() {
        authed = true;
        await initPortal();
    }

    function logout() {
        auth.logout();
        authed = false;
    }

    // ── Edit User Modal ───────────────────────────────────────────────────────
    let showEditUserModal = $state(false);
    let editingUser = $state<AdminUser | null>(null);
    let editUserForm = $state({ email: '', first_name: '', last_name: '', password: '' });
    let editUserError = $state('');
    let editUserSaving = $state(false);
    let allOrgsForModal = $state<AdminOrg[]>([]);
    let addOrgForm = $state({ org_id: '', role: 'beobachter' });
    let addOrgWorking = $state(false);

    async function openEditUser(user: AdminUser) {
        editingUser = user;
        editUserForm = { email: user.email, first_name: user.first_name ?? '', last_name: user.last_name ?? '', password: '' };
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
            const patch: { email?: string; password?: string; first_name?: string; last_name?: string } = {};
            if (editUserForm.email !== editingUser.email) patch.email = editUserForm.email;
            if (editUserForm.first_name.trim() !== (editingUser.first_name ?? '')) patch.first_name = editUserForm.first_name.trim();
            if (editUserForm.last_name.trim() !== (editingUser.last_name ?? '')) patch.last_name = editUserForm.last_name.trim();
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

    // ── DSGVO Betroffenenrechte (Art. 15 / 17) ─────────────────────────────────
    let dsgvoWorking = $state(false);

    async function exportUserData(user: AdminUser) {
        dsgvoWorking = true;
        editUserError = '';
        try {
            const bundle = await adminApi.exportUserData(user.id);
            const blob = new Blob([JSON.stringify(bundle, null, 2)], { type: 'application/json' });
            const url = URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = url;
            a.download = `convoyplan-export-${user.email}.json`;
            a.click();
            URL.revokeObjectURL(url);
        } catch (e: unknown) {
            editUserError = e instanceof Error ? e.message : 'Export fehlgeschlagen';
        } finally {
            dsgvoWorking = false;
        }
    }

    async function eraseUserData(user: AdminUser) {
        if (!confirm(`Wirklich ALLE Daten von ${user.email} unwiderruflich löschen?\n\nDer Audit-Trail wird aus Sicherheitsgründen pseudonymisiert beibehalten.`)) return;
        dsgvoWorking = true;
        editUserError = '';
        try {
            await adminApi.eraseUserData(user.id);
            showEditUserModal = false;
            await loadUsers();
        } catch (e: unknown) {
            editUserError = e instanceof Error ? e.message : 'Löschung fehlgeschlagen';
        } finally {
            dsgvoWorking = false;
        }
    }

    async function loadUsers() {
        try {
            loading = true;
            users = await adminApi.listUsers();
        } catch { error = 'Benutzer konnten nicht geladen werden'; }
        finally { loading = false; }
    }

    function resetCreateForm() {
        newUser = { email: '', first_name: '', last_name: '', is_superadmin: false, org_id: '', org_role: 'beobachter' };
        showCreateForm = false;
    }

    /** Build the createUser payload, omitting the optional org fields when none picked. */
    function createUserPayload(): AdminUserCreate {
        const payload: AdminUserCreate = {
            email: newUser.email,
            first_name: newUser.first_name,
            last_name: newUser.last_name,
            is_superadmin: newUser.is_superadmin,
        };
        if (newUser.org_id) {
            payload.org_id = newUser.org_id;
            payload.org_role = newUser.org_role;
        }
        return payload;
    }

    async function createUser() {
        try {
            await adminApi.createUser(createUserPayload());
            resetCreateForm();
            await loadUsers();
        } catch (e: unknown) {
            error = e instanceof Error ? e.message : 'Fehler beim Erstellen';
        }
    }

    async function createAndEmailUser() {
        createAndEmailWorking = true;
        try {
            const created = await adminApi.createUser(createUserPayload());
            await adminApi.sendUserPassword(created.id);
            resetCreateForm();
            await loadUsers();
        } catch (e: unknown) {
            error = e instanceof Error ? e.message : 'Fehler beim Erstellen oder E-Mail-Versand';
        } finally {
            createAndEmailWorking = false;
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

    let resettingMfaFor = $state<string | null>(null);

    async function resetUserMfa(user: AdminUser) {
        if (!confirm(`MFA für ${user.email} zurücksetzen?\n\nDer Benutzer kann sich danach wieder ohne MFA anmelden.`)) return;
        resettingMfaFor = user.id;
        try {
            await adminApi.resetUserMfa(user.id);
            await loadUsers();
        } catch (e: unknown) {
            error = e instanceof Error ? e.message : 'MFA konnte nicht zurückgesetzt werden';
        } finally {
            resettingMfaFor = null;
        }
    }

    // ── Organisationen ───────────────────────────────────────────────────────
    let orgs = $state<AdminOrg[]>([]);
    const sortedOrgs = $derived([...orgs.filter(o => !o.is_demo), ...orgs.filter(o => o.is_demo)]);
    const demoOrgCount = $derived(orgs.filter(o => o.is_demo).length);
    let orgsLoading = $state(false);
    let orgsError = $state('');

    async function loadOrgs() {
        orgsLoading = true;
        orgsError = '';
        try {
            [orgs, users] = await Promise.all([adminApi.listOrgs(), users.length ? Promise.resolve(users) : adminApi.listUsers()]);
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

    // Edit org owner
    let showEditOrgModal = $state(false);
    let editingOrg = $state<AdminOrg | null>(null);
    let editOrgOwnerId = $state('');
    let editOrgError = $state('');
    let editOrgSaving = $state(false);

    function openEditOrgModal(org: AdminOrg) {
        editingOrg = org;
        editOrgOwnerId = org.owner_id ?? '';
        editOrgError = '';
        showEditOrgModal = true;
    }

    async function saveOrgOwner() {
        if (!editingOrg || !editOrgOwnerId) return;
        editOrgSaving = true;
        editOrgError = '';
        try {
            await adminApi.updateOrg(editingOrg.id, { owner_id: editOrgOwnerId });
            showEditOrgModal = false;
            await loadOrgs();
        } catch { editOrgError = 'Inhaber konnte nicht gesetzt werden'; }
        finally { editOrgSaving = false; }
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

    // ── API-Keys ───────────────────────────────────────────────────────────────
    let apiKeyOrgs = $state<AdminOrg[]>([]);
    let apiKeyOrgId = $state('');
    let apiKeys = $state<ApiKey[]>([]);
    let apiKeysLoading = $state(false);
    let apiKeysError = $state('');
    let newApiKeyForm = $state({ name: '', role: 'beobachter', expires_at: '' });
    let creatingApiKey = $state(false);
    let createdApiKey = $state<ApiKeyCreated | null>(null);

    async function loadApiKeyOrgs() {
        apiKeysError = '';
        try {
            apiKeyOrgs = await adminApi.listOrgs();
            if (!apiKeyOrgId && apiKeyOrgs.length > 0) {
                apiKeyOrgId = apiKeyOrgs[0].id;
            }
            if (apiKeyOrgId) await loadApiKeys();
        } catch { apiKeysError = 'Organisationen konnten nicht geladen werden'; }
    }

    async function loadApiKeys() {
        if (!apiKeyOrgId) { apiKeys = []; return; }
        apiKeysLoading = true;
        apiKeysError = '';
        try {
            apiKeys = await adminApi.listApiKeys(apiKeyOrgId);
        } catch { apiKeysError = 'API-Keys konnten nicht geladen werden'; }
        finally { apiKeysLoading = false; }
    }

    function onApiKeyOrgChange() {
        createdApiKey = null;
        loadApiKeys();
    }

    async function createApiKey() {
        if (!apiKeyOrgId || !newApiKeyForm.name.trim()) return;
        creatingApiKey = true;
        apiKeysError = '';
        createdApiKey = null;
        try {
            const expires_at = newApiKeyForm.expires_at
                ? new Date(newApiKeyForm.expires_at).toISOString()
                : null;
            createdApiKey = await adminApi.createApiKey(apiKeyOrgId, {
                name: newApiKeyForm.name.trim(),
                role: newApiKeyForm.role,
                expires_at,
            });
            newApiKeyForm = { name: '', role: 'beobachter', expires_at: '' };
            await loadApiKeys();
        } catch (e: unknown) {
            apiKeysError = e instanceof Error ? e.message : 'API-Key konnte nicht erstellt werden';
        } finally {
            creatingApiKey = false;
        }
    }

    async function revokeApiKey(key: ApiKey) {
        if (!confirm(`API-Key "${key.name}" (cvp_${key.prefix}…) widerrufen?\n\nSysteme, die diesen Key nutzen, verlieren sofort den Zugriff.`)) return;
        try {
            await adminApi.revokeApiKey(apiKeyOrgId, key.id);
            await loadApiKeys();
        } catch { apiKeysError = 'API-Key konnte nicht widerrufen werden'; }
    }

    async function copyApiKey(value: string) {
        try { await navigator.clipboard.writeText(value); } catch { /* clipboard unavailable */ }
    }

    function fmtDate(d: string | null): string {
        if (!d) return '–';
        return new Date(d).toLocaleString('de-DE', { dateStyle: 'short', timeStyle: 'short' });
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

    // Release channel (stable / beta)
    let updateChannel = $state<import('$lib/api').UpdateChannel | null>(null);
    let channelSaving = $state(false);

    // Update mode (auto / notify)
    let updateMode = $state<import('$lib/api').UpdateMode | null>(null);
    let modeSaving = $state(false);

    // Live log terminal
    let updateLogLines = $state<string[]>([]);
    let showUpdateLog = $state(false);
    let updateLogDone = $state(false);
    let _updateLogSource: EventSource | null = null;
    let logContainer: HTMLDivElement | null = null;

    async function loadUpdateChannel() {
        try {
            updateChannel = await adminApi.getUpdateChannel();
        } catch {
            updateChannel = null;
        }
    }

    async function setChannel(channel: 'stable' | 'beta' | 'nightly') {
        if (channelSaving || updateChannel?.channel === channel) return;
        channelSaving = true;
        updateError = '';
        try {
            await adminApi.setUpdateChannel(channel);
            await loadUpdateChannel();
            // Re-evaluate update availability against the newly selected channel.
            await loadUpdateStatus();
        } catch (e: unknown) {
            updateError = e instanceof Error ? e.message : 'Kanal konnte nicht gespeichert werden';
        } finally {
            channelSaving = false;
        }
    }

    async function loadUpdateMode() {
        try {
            updateMode = await adminApi.getUpdateMode();
        } catch {
            updateMode = null;
        }
    }

    async function setMode(mode: 'auto' | 'notify') {
        if (modeSaving || updateMode?.mode === mode) return;
        modeSaving = true;
        updateError = '';
        try {
            await adminApi.setUpdateMode(mode);
            await loadUpdateMode();
        } catch (e: unknown) {
            updateError = e instanceof Error ? e.message : 'Update-Modus konnte nicht gespeichert werden';
        } finally {
            modeSaving = false;
        }
    }

    async function setNotifyOnAuto(enabled: boolean) {
        if (modeSaving || !updateMode) return;
        modeSaving = true;
        updateError = '';
        try {
            await adminApi.setUpdateMode(updateMode.mode, enabled);
            await loadUpdateMode();
        } catch (e: unknown) {
            updateError = e instanceof Error ? e.message : 'Einstellung konnte nicht gespeichert werden';
        } finally {
            modeSaving = false;
        }
    }

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

    async function startLogStream() {
        if (_updateLogSource) { _updateLogSource.close(); _updateLogSource = null; }
        updateLogLines = [];
        updateLogDone = false;
        showUpdateLog = true;

        // SSE cannot send an Authorization header — use a short-lived stream
        // ticket instead of the long-lived superadmin token in the URL.
        const ticket = await getStreamTicket();
        if (!ticket) {
            updateLogLines = ['[Authentifizierung fehlgeschlagen — bitte neu anmelden]'];
            updateLogDone = true;
            return;
        }
        const es = new EventSource(`/api/admin/update-log?token=${encodeURIComponent(ticket)}`);
        _updateLogSource = es;

        es.onmessage = (e) => {
            updateLogLines = [...updateLogLines, e.data];
            // auto-scroll to bottom
            setTimeout(() => {
                if (logContainer) logContainer.scrollTop = logContainer.scrollHeight;
            }, 0);
        };

        es.addEventListener('done', () => {
            updateLogDone = true;
            es.close();
            _updateLogSource = null;
            // Refresh status after stream ends
            setTimeout(async () => {
                await loadUpdateStatus();
                updateTriggering = false;
                if (updateStatus && !updateStatus.update_available) {
                    updateSuccess = `Aktualisiert auf ${updateStatus.deployed_sha?.slice(0, 7) ?? '?'}`;
                }
            }, 2000);
        });

        es.onerror = () => {
            // Connection dropped (e.g. backend restarted after update)
            updateLogLines = [...updateLogLines, '[Verbindung getrennt — Backend wird neu gestartet…]'];
            updateLogDone = true;
            es.close();
            _updateLogSource = null;
            setTimeout(async () => {
                await loadUpdateStatus();
                updateTriggering = false;
                if (updateStatus && !updateStatus.update_available) {
                    updateSuccess = `Aktualisiert auf ${updateStatus.deployed_sha?.slice(0, 7) ?? '?'}`;
                }
            }, 5000);
        };
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
        startLogStream();
    }

    // ── Demo-Modus ────────────────────────────────────────────────────────────
    let demoSettings = $state<DemoSettings | null>(null);
    let demoSaving = $state(false);
    let demoSettingsError = $state('');
    let demoSettingsSuccess = $state('');

    async function loadDemoSettings() {
        try {
            demoSettings = await adminApi.getDemoSettings();
            demoHoursInput = demoSettings.session_hours;
        } catch { /* Abschnitt zeigt dann "Status nicht verfügbar" */ }
        try {
            demoSessions = await adminApi.listDemoSessions();
        } catch { demoSessions = []; }
    }

    let demoSessions = $state<DemoSessionInfo[]>([]);
    let endingDemoSession = $state<string | null>(null);

    async function endDemoSession(session: DemoSessionInfo) {
        if (!confirm(`Demo-Sitzung „${session.name}" (${session.slug}) sofort beenden? Alle Daten der Sitzung werden gelöscht.`)) return;
        endingDemoSession = session.id;
        demoSettingsError = '';
        try {
            await adminApi.endDemoSession(session.id);
            demoSessions = demoSessions.filter(s => s.id !== session.id);
        } catch (e) {
            demoSettingsError = e instanceof Error ? e.message : 'Fehler beim Beenden der Demo-Sitzung';
        } finally {
            endingDemoSession = null;
        }
    }

    async function toggleDemo() {
        if (!demoSettings) return;
        demoSaving = true;
        demoSettingsError = '';
        demoSettingsSuccess = '';
        try {
            demoSettings = await adminApi.saveDemoSettings(!demoSettings.enabled);
            demoSettingsSuccess = demoSettings.enabled
                ? 'Demo-Modus aktiviert — der Demo-Button erscheint auf der Startseite.'
                : 'Demo-Modus deaktiviert.';
            setTimeout(() => { demoSettingsSuccess = ''; }, 5000);
        } catch (e) {
            demoSettingsError = e instanceof Error ? e.message : 'Fehler beim Speichern';
        } finally {
            demoSaving = false;
        }
    }

    let demoHoursInput = $state(24);
    let demoHoursSaving = $state(false);

    async function saveDemoHours() {
        if (!demoSettings) return;
        const hours = Math.round(demoHoursInput);
        if (!Number.isFinite(hours) || hours < 1 || hours > 720) {
            demoSettingsError = 'Laufzeit muss zwischen 1 und 720 Stunden liegen.';
            return;
        }
        demoHoursSaving = true;
        demoSettingsError = '';
        demoSettingsSuccess = '';
        try {
            demoSettings = await adminApi.saveDemoSettings(demoSettings.enabled, hours);
            demoHoursInput = demoSettings.session_hours;
            demoSettingsSuccess = `Laufzeit gespeichert — neue Demo-Sitzungen laufen ${hours} Stunden.`;
            setTimeout(() => { demoSettingsSuccess = ''; }, 5000);
        } catch (e) {
            demoSettingsError = e instanceof Error ? e.message : 'Fehler beim Speichern';
        } finally {
            demoHoursSaving = false;
        }
    }

    let extendingDemoSession = $state<string | null>(null);

    async function extendDemoSession(session: DemoSessionInfo) {
        extendingDemoSession = session.id;
        demoSettingsError = '';
        try {
            const updated = await adminApi.extendDemoSession(session.id, 24);
            demoSessions = demoSessions.map(s => s.id === updated.id ? updated : s);
        } catch (e) {
            demoSettingsError = e instanceof Error ? e.message : 'Fehler beim Verlängern der Demo-Sitzung';
        } finally {
            extendingDemoSession = null;
        }
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

    // ── Live-Verkehrslage (HERE / TomTom) ─────────────────────────────────────
    let trafficKeys = $state<import('$lib/api').TrafficKeysResponse | null>(null);
    let hereKeyInput = $state('');
    let tomtomKeyInput = $state('');
    let trafficProviderInput = $state('');
    let trafficSaving = $state(false);
    let trafficSuccess = $state('');
    let trafficError = $state('');

    async function loadTrafficKeys() {
        try {
            trafficKeys = await adminApi.getTrafficKeys();
            trafficProviderInput = trafficKeys.forced ?? '';
        } catch { /* ignore */ }
    }

    async function saveTrafficKeys() {
        trafficSaving = true;
        trafficError = '';
        trafficSuccess = '';
        try {
            const payload: { here_key?: string; tomtom_key?: string; provider?: string } = {
                provider: trafficProviderInput,
            };
            // Leere Eingabefelder lassen den bestehenden Key unverändert.
            if (hereKeyInput.trim()) payload.here_key = hereKeyInput.trim();
            if (tomtomKeyInput.trim()) payload.tomtom_key = tomtomKeyInput.trim();
            await adminApi.setTrafficKeys(payload);
            hereKeyInput = '';
            tomtomKeyInput = '';
            await loadTrafficKeys();
            trafficSuccess = 'Gespeichert. Verkehrslage ist beim nächsten Routen-Laden aktiv.';
            setTimeout(() => { trafficSuccess = ''; }, 5000);
        } catch (e: unknown) {
            trafficError = e instanceof Error ? e.message : 'Fehler beim Speichern';
        } finally {
            trafficSaving = false;
        }
    }

    async function clearTrafficKey(which: 'here' | 'tomtom') {
        if (!confirm(`${which === 'here' ? 'HERE' : 'TomTom'}-Key entfernen?`)) return;
        trafficSaving = true;
        try {
            await adminApi.setTrafficKeys(which === 'here' ? { here_key: '' } : { tomtom_key: '' });
            await loadTrafficKeys();
            trafficSuccess = 'Key entfernt.';
            setTimeout(() => { trafficSuccess = ''; }, 3000);
        } catch { trafficError = 'Fehler beim Entfernen'; }
        finally { trafficSaving = false; }
    }


    // ── MFA ──────────────────────────────────────────────────────────────────
    let mfaEnabled = $state(false);
    let mfaSetupSecret = $state('');
    let mfaSetupQrDataUrl = $state('');
    let mfaSetupStep = $state<'idle' | 'setup' | 'confirm'>('idle');
    let mfaCode = $state('');
    let mfaWorking = $state(false);
    let mfaError = $state('');
    let mfaSuccess = $state('');

    async function loadMfaStatus() {
        try {
            const s = await mfaApi.status();
            mfaEnabled = s.mfa_enabled;
        } catch { /* ignore */ }
    }

    async function startMfaSetup() {
        mfaWorking = true;
        mfaError = '';
        try {
            const data = await mfaApi.setup();
            mfaSetupSecret = data.secret;
            mfaSetupQrDataUrl = await QRCode.toDataURL(data.provisioning_uri, { width: 200, margin: 1 });
            mfaSetupStep = 'setup';
        } catch (e: unknown) {
            mfaError = e instanceof Error ? e.message : 'Fehler beim Setup';
        } finally {
            mfaWorking = false;
        }
    }

    async function confirmMfa() {
        if (mfaCode.length < 6) return;
        mfaWorking = true;
        mfaError = '';
        try {
            await mfaApi.confirm(mfaCode);
            mfaEnabled = true;
            mfaSetupStep = 'idle';
            mfaCode = '';
            mfaSuccess = 'MFA erfolgreich aktiviert.';
            setTimeout(() => { mfaSuccess = ''; }, 4000);
        } catch (e: unknown) {
            mfaError = e instanceof Error ? e.message : 'Ungültiger Code';
        } finally {
            mfaWorking = false;
        }
    }

    async function disableMfa() {
        if (mfaCode.length < 6) return;
        mfaWorking = true;
        mfaError = '';
        try {
            await mfaApi.disable(mfaCode);
            mfaEnabled = false;
            mfaSetupStep = 'idle';
            mfaCode = '';
            mfaSuccess = 'MFA deaktiviert.';
            setTimeout(() => { mfaSuccess = ''; }, 4000);
        } catch (e: unknown) {
            mfaError = e instanceof Error ? e.message : 'Ungültiger Code';
        } finally {
            mfaWorking = false;
        }
    }

    // ── SMTP ─────────────────────────────────────────────────────────────────
    let smtpConfig = $state<SmtpConfigResponse | null>(null);
    let smtpForm = $state<SmtpConfig>({
        host: '', port: 587, username: '', password: '',
        from_email: '', from_name: 'ConvoyPlan', use_tls: 'starttls',
    });
    let smtpSaving = $state(false);
    let smtpTesting = $state(false);
    let smtpError = $state('');
    let smtpSuccess = $state('');
    let showSmtpPassword = $state(false);

    async function loadSmtpSettings() {
        try {
            smtpConfig = await adminApi.getSmtpSettings();
            smtpForm = {
                host: smtpConfig.host,
                port: smtpConfig.port,
                username: smtpConfig.username,
                password: '',  // never pre-fill password
                from_email: smtpConfig.from_email,
                from_name: smtpConfig.from_name,
                use_tls: smtpConfig.use_tls as SmtpConfig['use_tls'],
            };
        } catch { /* ignore */ }
    }

    async function saveSmtp() {
        smtpSaving = true;
        smtpError = '';
        smtpSuccess = '';
        try {
            await adminApi.saveSmtpSettings(smtpForm);
            smtpSuccess = 'SMTP-Einstellungen gespeichert.';
            await loadSmtpSettings();
            setTimeout(() => { smtpSuccess = ''; }, 4000);
        } catch (e: unknown) {
            smtpError = e instanceof Error ? e.message : 'Fehler beim Speichern';
        } finally {
            smtpSaving = false;
        }
    }

    async function testSmtp() {
        smtpTesting = true;
        smtpError = '';
        smtpSuccess = '';
        try {
            await adminApi.testSmtp();
            smtpSuccess = 'Verbindung erfolgreich ✓';
            setTimeout(() => { smtpSuccess = ''; }, 4000);
        } catch (e: unknown) {
            smtpError = e instanceof Error ? e.message : 'Verbindungsfehler';
        } finally {
            smtpTesting = false;
        }
    }

    // ── Send-password / Reset-password per user ─────────────────────────────
    let sendingPasswordFor = $state<string | null>(null);
    let sendPasswordResult = $state<Record<string, 'ok' | 'error'>>({});
    let resettingPasswordFor = $state<string | null>(null);
    // Stores the generated plaintext password per userId for display
    let generatedPasswords = $state<Record<string, string>>({});

    async function sendUserPassword(userId: string) {
        sendingPasswordFor = userId;
        try {
            await adminApi.sendUserPassword(userId);
            sendPasswordResult = { ...sendPasswordResult, [userId]: 'ok' };
            setTimeout(() => {
                sendPasswordResult = Object.fromEntries(
                    Object.entries(sendPasswordResult).filter(([k]) => k !== userId)
                );
            }, 4000);
        } catch (e: unknown) {
            sendPasswordResult = { ...sendPasswordResult, [userId]: 'error' };
        } finally {
            sendingPasswordFor = null;
        }
    }

    async function resetUserPassword(userId: string) {
        resettingPasswordFor = userId;
        try {
            const res = await adminApi.resetUserPassword(userId);
            generatedPasswords = { ...generatedPasswords, [userId]: res.password };
        } catch (e: unknown) {
            alert('Fehler beim Zurücksetzen des Passworts.');
        } finally {
            resettingPasswordFor = null;
        }
    }

    function clearGeneratedPassword(userId: string) {
        const { [userId]: _, ...rest } = generatedPasswords;
        generatedPasswords = rest;
    }

    // ── Leitstellen: Gebiets-Picker & Übersicht ─────────────────────────────────
    let areaSel = $state<AreaSelection | null>(null);
    let areaPickerKey = $state(0);
    let editingGeo = $state<GeoJSON.Geometry | null>(null);
    let lsGeojson = $state<GeoJSON.FeatureCollection | null>(null);

    // Vorschläge (pending) zur Freigabe und bereits vergebene Kreise.
    let pendingLs = $derived(leitstellen.filter((l) => l.status === 'pending'));
    let takenCodes = $derived(
        leitstellen.filter((l) => l.id !== editingLs?.id).flatMap((l) => l.district_codes ?? [])
    );
    let takenOwnerByCode = $derived.by(() => {
        const m: Record<string, string> = {};
        for (const l of leitstellen) {
            if (l.id === editingLs?.id) continue;
            for (const c of l.district_codes ?? []) m[c] = l.name;
        }
        return m;
    });

    async function loadLeitstellen() {
        try {
            leitstellen = await leistellenApi.list();
            lsGeojson = await leistellenApi.geojson();
        } catch { lsError = 'Leitstellen konnten nicht geladen werden'; }
    }

    function openCreateLs() {
        editingLs = null;
        lsForm = { name: '', anrufgruppe: '', zusatz_kanaele: [] };
        areaSel = null;
        editingGeo = null;
        areaPickerKey++;
        showLsModal = true;
    }

    async function openEditLs(ls: Leitstelle) {
        try {
            editingLs = await leistellenApi.get(ls.id);
            lsForm = {
                name: editingLs.name,
                anrufgruppe: editingLs.anrufgruppe,
                zusatz_kanaele: [...editingLs.zusatz_kanaele],
            };
            areaSel = null;
            editingGeo = (editingLs.geometry_geojson as GeoJSON.Geometry) ?? null;
            areaPickerKey++;
            showLsModal = true;
        } catch { lsError = 'Leitstelle konnte nicht geladen werden'; }
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
            const payload = { ...lsForm, district_codes: areaSel ? areaSel.districtCodes : undefined };
            const saved = editingLs
                ? await leistellenApi.update(editingLs.id, payload)
                : await leistellenApi.create(payload);
            if (areaSel?.boundaryFile) {
                await leistellenApi.importBoundary(saved.id, areaSel.boundaryFile);
            }
            showLsModal = false;
            await loadLeitstellen();
        } catch (e: unknown) {
            lsError = e instanceof Error ? e.message : 'Fehler beim Speichern';
        }
    }

    async function approveLs(ls: Leitstelle) {
        try {
            await leistellenApi.approve(ls.id);
            await loadLeitstellen();
        } catch (e: unknown) {
            lsError = e instanceof Error ? e.message : 'Fehler bei der Freigabe';
        }
    }

    async function rejectLs(ls: Leitstelle) {
        const note = prompt(`Vorschlag „${ls.name}" ablehnen. Optionaler Grund (für die Organisation sichtbar):`);
        if (note === null) return;
        try {
            await leistellenApi.reject(ls.id, note || undefined);
            await loadLeitstellen();
        } catch (e: unknown) {
            lsError = e instanceof Error ? e.message : 'Fehler beim Ablehnen';
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

    // ── E-Mail Template ──────────────────────────────────────────────────────
    let emailTemplate = $state<EmailTemplate | null>(null);
    let emailTemplateForm = $state({ subject: '', html: '' });
    let emailTemplateSaving = $state(false);
    let emailTemplateResetting = $state(false);
    let emailTemplateError = $state('');
    let emailTemplateSuccess = $state('');
    let emailTemplateVarsOpen = $state(false);

    async function loadEmailTemplate() {
        try {
            emailTemplate = await emailTemplateApi.get();
            emailTemplateForm = { subject: emailTemplate.subject, html: emailTemplate.html };
        } catch { /* ignore, may not be superadmin yet */ }
    }

    async function saveEmailTemplate() {
        emailTemplateSaving = true;
        emailTemplateError = '';
        emailTemplateSuccess = '';
        try {
            emailTemplate = await emailTemplateApi.update(emailTemplateForm);
            emailTemplateForm = { subject: emailTemplate.subject, html: emailTemplate.html };
            emailTemplateSuccess = 'Template gespeichert.';
            setTimeout(() => { emailTemplateSuccess = ''; }, 4000);
        } catch (e: unknown) {
            emailTemplateError = e instanceof Error ? e.message : 'Fehler beim Speichern';
        } finally {
            emailTemplateSaving = false;
        }
    }

    async function resetEmailTemplate() {
        if (!confirm('E-Mail-Template wirklich auf Standard zurücksetzen? Alle Anpassungen gehen verloren.')) return;
        emailTemplateResetting = true;
        emailTemplateError = '';
        emailTemplateSuccess = '';
        try {
            emailTemplate = await emailTemplateApi.reset();
            emailTemplateForm = { subject: emailTemplate.subject, html: emailTemplate.html };
            emailTemplateSuccess = 'Template auf Standard zurückgesetzt.';
            setTimeout(() => { emailTemplateSuccess = ''; }, 4000);
        } catch (e: unknown) {
            emailTemplateError = e instanceof Error ? e.message : 'Fehler beim Zurücksetzen';
        } finally {
            emailTemplateResetting = false;
        }
    }

    async function previewEmailTemplate() {
        const token = $auth.token ?? '';
        try {
            const resp = await fetch('/api/admin/email-template/preview', {
                headers: { 'Authorization': `Bearer ${token}` },
            });
            if (!resp.ok) throw new Error(resp.statusText);
            const blob = await resp.blob();
            const url = URL.createObjectURL(blob);
            window.open(url, '_blank', 'noopener');
            // Release the object URL once the new tab has had time to load it.
            setTimeout(() => URL.revokeObjectURL(url), 60_000);
        } catch (e: unknown) {
            emailTemplateError = e instanceof Error ? e.message : 'Vorschau fehlgeschlagen';
        }
    }
</script>

{#if authed}
<div class="admin-page">
    <div class="admin-header">
        <h1>Admin</h1>
        <div class="header-actions">
            <a href="/plan" class="back-link">← Plan</a>
            <button class="logout-btn" onclick={logout}>Abmelden</button>
        </div>
    </div>

    <div class="tab-bar">
        <button class="tab" class:active={activeTab === 'benutzer'} onclick={() => (activeTab = 'benutzer')}>Benutzer</button>
        <button class="tab" class:active={activeTab === 'organisationen'} onclick={() => { activeTab = 'organisationen'; loadOrgs(); }}>Organisationen</button>
        <button class="tab" class:active={activeTab === 'api-keys'} onclick={() => { activeTab = 'api-keys'; loadApiKeyOrgs(); }}>API-Keys</button>
        <button class="tab" class:active={activeTab === 'leitstellen'} onclick={() => (activeTab = 'leitstellen')}>Leitstellen</button>
        <button class="tab" class:active={activeTab === 'branding'} onclick={() => activeTab = 'branding'}>Branding</button>
        <button class="tab" class:active={activeTab === 'system'} onclick={() => { activeTab = 'system'; loadUpdateStatus(); loadUpdateChannel(); loadUpdateMode(); loadLicenseStatus(); loadGithubTokenStatus(); loadDemoSettings(); }}>System</button>
    </div>

    <!-- ── Benutzer ── -->
    {#if activeTab === 'benutzer'}
        {#if error}
            <div class="error-bar">{error} <button onclick={() => (error = '')}>✕</button></div>
        {/if}

        <div class="section">
            <div class="section-header">
                <strong>Benutzer ({users.length - demoUserCount}{demoUserCount > 0 ? ` + ${demoUserCount} Demo` : ''})</strong>
                <button class="btn-small" onclick={toggleCreateForm}>+ Neu</button>
            </div>

            {#if showCreateForm}
                <form class="create-form" onsubmit={(e) => { e.preventDefault(); createUser(); }}>
                    <div class="name-input-row">
                        <input placeholder="Vorname" type="text" bind:value={newUser.first_name} autocomplete="off" />
                        <input placeholder="Nachname" type="text" bind:value={newUser.last_name} autocomplete="off" />
                    </div>
                    <input placeholder="E-Mail *" type="email" bind:value={newUser.email} required />
                    <div class="org-input-row">
                        <select bind:value={newUser.org_id} class="org-select">
                            <option value="">Organisation (optional)…</option>
                            {#each createOrgs.filter(o => !o.is_demo) as o}
                                <option value={o.id}>{o.name} ({o.slug})</option>
                            {/each}
                        </select>
                        {#if newUser.org_id}
                            <select bind:value={newUser.org_role} class="role-select">
                                <option value="beobachter">Beobachter</option>
                                <option value="fahrer">Fahrer</option>
                                <option value="planer">Planer</option>
                                <option value="admin">Admin</option>
                            </select>
                        {/if}
                    </div>
                    <label class="checkbox-label">
                        <input type="checkbox" bind:checked={newUser.is_superadmin} />
                        Superadmin
                    </label>
                    <p class="hint create-pw-hint">
                        🔑 Das Passwort wird automatisch generiert. Mit „Anlegen &amp; Einladen" erhält
                        der Benutzer seine Zugangsdaten (inkl. Login-Link) per E-Mail.
                    </p>
                    <div class="create-actions">
                        <button type="submit">Anlegen</button>
                        <button
                            type="button"
                            class="btn-invite"
                            onclick={createAndEmailUser}
                            disabled={createAndEmailWorking || !smtpConfig?.configured}
                            title={smtpConfig?.configured ? 'Anlegen & Zugangsdaten per E-Mail senden' : 'SMTP zuerst unter System → E-Mail konfigurieren'}
                        >
                            {createAndEmailWorking ? '…' : 'Anlegen & ✉ Einladen'}
                        </button>
                    </div>
                </form>
            {/if}

            {#if loading}
                <p class="hint">Lade…</p>
            {:else}
                <table class="user-table">
                    <thead>
                        <tr>
                            <th>Name</th>
                            <th>E-Mail</th>
                            <th>Organisationen</th>
                            <th>Aktiv</th>
                            <th>Superadmin</th>
                            <th>MFA</th>
                            <th></th>
                        </tr>
                    </thead>
                    <tbody>
                        {#each sortedUsers as user, i}
                            {#if user.is_demo && (i === 0 || !sortedUsers[i - 1].is_demo)}
                                <tr class="group-divider-row">
                                    <td colspan="7">▶ Demo-Sitzungen ({demoUserCount}) — temporär, werden automatisch gelöscht</td>
                                </tr>
                            {/if}
                            <tr class:inactive={!user.is_active} class:demo-row={user.is_demo}>
                                <td>
                                    {#if user.first_name || user.last_name}
                                        {[user.first_name, user.last_name].filter(Boolean).join(' ')}
                                    {:else}
                                        <span class="hint">—</span>
                                    {/if}
                                </td>
                                <td class="email-cell">{user.email}</td>
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
                                <td>
                                    {#if user.mfa_enabled}
                                        <span class="mfa-on" title="MFA aktiv">Aktiv</span>
                                    {:else}
                                        <span class="hint">—</span>
                                    {/if}
                                </td>
                                <td class="actions-cell">
                                    <div>
                                        <button class="btn-small" onclick={() => openEditUser(user)} title="Bearbeiten">✎</button>
                                        {#if user.mfa_enabled}
                                            <button
                                                class="btn-small"
                                                onclick={() => resetUserMfa(user)}
                                                disabled={resettingMfaFor === user.id}
                                                title="MFA zurücksetzen — Benutzer kann sich danach wieder ohne MFA anmelden"
                                            >
                                                {resettingMfaFor === user.id ? '…' : '🔓'}
                                            </button>
                                        {/if}
                                        <button
                                            class="btn-small"
                                            onclick={() => resetUserPassword(user.id)}
                                            disabled={resettingPasswordFor === user.id}
                                            title="Neues Passwort generieren und anzeigen"
                                        >
                                            {resettingPasswordFor === user.id ? '…' : '🔑'}
                                        </button>
                                        <button
                                            class="btn-small"
                                            class:success-btn={sendPasswordResult[user.id] === 'ok'}
                                            class:danger={sendPasswordResult[user.id] === 'error'}
                                            onclick={() => sendUserPassword(user.id)}
                                            disabled={sendingPasswordFor === user.id || !smtpConfig?.configured}
                                            title={smtpConfig?.configured ? 'Neues Passwort generieren & per E-Mail senden' : 'SMTP zuerst unter Einstellungen konfigurieren'}
                                        >
                                            {sendingPasswordFor === user.id ? '…' : sendPasswordResult[user.id] === 'ok' ? '✓' : sendPasswordResult[user.id] === 'error' ? '✕' : '✉'}
                                        </button>
                                        <button class="btn-small danger" onclick={() => deleteUser(user)} title="Löschen">🗑</button>
                                    </div>
                                    {#if generatedPasswords[user.id]}
                                        <div class="generated-pw-box">
                                            <span class="generated-pw-label">Neues Passwort:</span>
                                            <code class="generated-pw">{generatedPasswords[user.id]}</code>
                                            <button
                                                class="btn-tiny"
                                                onclick={() => navigator.clipboard.writeText(generatedPasswords[user.id])}
                                                title="Kopieren"
                                            >📋</button>
                                            <button
                                                class="btn-tiny"
                                                onclick={() => clearGeneratedPassword(user.id)}
                                                title="Schließen"
                                            >✕</button>
                                        </div>
                                    {/if}
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
                <strong>Organisationen ({orgs.length - demoOrgCount}{demoOrgCount > 0 ? ` + ${demoOrgCount} Demo` : ''})</strong>
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
                        {#each sortedOrgs as org, i}
                            {#if org.is_demo && (i === 0 || !sortedOrgs[i - 1].is_demo)}
                                <tr class="group-divider-row">
                                    <td colspan="5">▶ Demo-Sitzungen ({demoOrgCount}) — temporär, werden automatisch gelöscht</td>
                                </tr>
                            {/if}
                            <tr class:demo-row={org.is_demo}>
                                <td>{org.name}</td>
                                <td><code>{org.slug}</code></td>
                                <td class="hint email-cell">{org.owner_email ?? '–'}</td>
                                <td>{org.member_count}</td>
                                <td class="actions-cell">
                                    <div>
                                        <button class="btn-small" onclick={() => openEditOrgModal(org)} title="Inhaber ändern">✎</button>
                                        <button class="btn-small danger" onclick={() => deleteOrg(org)} title="Löschen">🗑</button>
                                    </div>
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

    <!-- ── API-Keys ── -->
    {#if activeTab === 'api-keys'}
        {#if apiKeysError}
            <div class="error-bar">{apiKeysError} <button onclick={() => (apiKeysError = '')}>✕</button></div>
        {/if}

        <div class="section">
            <div class="section-header">
                <strong>API-Keys</strong>
                <button class="btn-small" onclick={loadApiKeys} disabled={!apiKeyOrgId}>↺</button>
            </div>
            <p class="hint" style="margin:.2rem 0 .8rem">
                API-Keys erlauben Fremdsystemen den programmatischen Zugriff auf die Daten <em>einer</em>
                Organisation. Der Key wird per Header <code>X-API-Key</code> gesendet und besitzt die hier
                gewählte Rolle. Der Klartext wird nur einmal bei der Erstellung angezeigt.
            </p>

            <div class="form-row" style="margin-bottom:1rem">
                <label>Organisation
                    <select bind:value={apiKeyOrgId} onchange={onApiKeyOrgChange}>
                        {#each apiKeyOrgs as org}
                            <option value={org.id}>{org.name} ({org.slug})</option>
                        {/each}
                    </select>
                </label>
            </div>

            {#if createdApiKey}
                <div class="key-reveal">
                    <strong>Neuer API-Key — jetzt kopieren, er wird nur einmal angezeigt:</strong>
                    <div class="key-reveal-row">
                        <code>{createdApiKey.key}</code>
                        <button class="btn-small" onclick={() => copyApiKey(createdApiKey!.key)}>Kopieren</button>
                        <button class="btn-small" onclick={() => (createdApiKey = null)}>Schließen</button>
                    </div>
                </div>
            {/if}

            {#if apiKeyOrgId}
                <div class="form-row" style="align-items:flex-end;flex-wrap:wrap;gap:.6rem">
                    <label style="flex:1;min-width:180px">Name / Verwendungszweck
                        <input type="text" bind:value={newApiKeyForm.name} placeholder="z. B. Leitstellen-Anbindung" />
                    </label>
                    <label>Rolle
                        <select bind:value={newApiKeyForm.role}>
                            <option value="beobachter">Beobachter (nur lesen)</option>
                            <option value="fahrer">Fahrer</option>
                            <option value="planer">Planer (schreiben)</option>
                            <option value="admin">Admin (voll)</option>
                        </select>
                    </label>
                    <label>Ablauf (optional)
                        <input type="date" bind:value={newApiKeyForm.expires_at} />
                    </label>
                    <button class="btn-primary" onclick={createApiKey} disabled={creatingApiKey || !newApiKeyForm.name.trim()}>
                        {creatingApiKey ? 'Erstelle…' : '+ Key erstellen'}
                    </button>
                </div>

                {#if apiKeysLoading}
                    <p class="hint">Lade…</p>
                {:else}
                    <table class="user-table">
                        <thead>
                            <tr>
                                <th>Name</th>
                                <th>Key</th>
                                <th>Rolle</th>
                                <th>Erstellt</th>
                                <th>Zuletzt genutzt</th>
                                <th>Ablauf</th>
                                <th>Status</th>
                                <th></th>
                            </tr>
                        </thead>
                        <tbody>
                            {#each apiKeys as key}
                                <tr style:opacity={key.revoked ? 0.5 : 1}>
                                    <td>{key.name}</td>
                                    <td><code>cvp_{key.prefix}…</code></td>
                                    <td>{key.role}</td>
                                    <td class="hint">{fmtDate(key.created_at)}</td>
                                    <td class="hint">{fmtDate(key.last_used_at)}</td>
                                    <td class="hint">{fmtDate(key.expires_at)}</td>
                                    <td>{key.revoked ? '⛔ widerrufen' : '✓ aktiv'}</td>
                                    <td class="actions-cell">
                                        {#if !key.revoked}
                                            <div><button class="btn-small danger" onclick={() => revokeApiKey(key)} title="Widerrufen">🗑</button></div>
                                        {/if}
                                    </td>
                                </tr>
                            {/each}
                            {#if apiKeys.length === 0}
                                <tr><td colspan="8" class="hint" style="text-align:center">Noch keine API-Keys für diese Organisation.</td></tr>
                            {/if}
                        </tbody>
                    </table>
                {/if}
            {:else}
                <p class="hint">Keine Organisationen vorhanden — zuerst eine Organisation anlegen.</p>
            {/if}
        </div>
    {/if}

    <!-- ── Leitstellen ── -->
    {#if activeTab === 'leitstellen'}
        {#if lsError}
            <div class="error-bar">{lsError} <button onclick={() => (lsError = '')}>✕</button></div>
        {/if}

        {#if lsGeojson && lsGeojson.features.length > 0}
            <div class="section">
                <div class="section-header"><strong>Übersicht</strong></div>
                <LeitstellenOverviewMap geojson={lsGeojson} />
                <p class="hint" style="margin:.4rem 0 0">Blau = global · Rot = org-eigen/Vorschlag</p>
            </div>
        {/if}

        {#if pendingLs.length > 0}
            <div class="section">
                <div class="section-header"><strong>Vorschläge zur Freigabe ({pendingLs.length})</strong></div>
                <table class="user-table">
                    <thead>
                        <tr><th>Name</th><th>Anrufgruppe</th><th>Vorgeschlagen von</th><th>Grenzen</th><th></th></tr>
                    </thead>
                    <tbody>
                        {#each pendingLs as ls}
                            <tr>
                                <td>{ls.name}</td>
                                <td><code>{ls.anrufgruppe}</code></td>
                                <td>{ls.proposed_by_org_name ?? ls.org_name ?? '–'}</td>
                                <td>{ls.has_geometry ? '✓' : '✗'}</td>
                                <td class="actions-cell">
                                    <div>
                                        <button class="btn-small primary" onclick={() => approveLs(ls)}>✓ Freigeben</button>
                                        <button class="btn-small danger" onclick={() => rejectLs(ls)}>✕ Ablehnen</button>
                                        <button class="btn-small" onclick={() => openEditLs(ls)}>✎ Bearbeiten</button>
                                    </div>
                                </td>
                            </tr>
                        {/each}
                    </tbody>
                </table>
            </div>
        {/if}

        <div class="section">
            <div class="section-header">
                <strong>Leitstellen ({leitstellen.length})</strong>
                {#if $auth.is_superadmin}
                    <button class="btn-small" onclick={openCreateLs}>+ Neu</button>
                {/if}
            </div>

            <LeitstellenTable items={leitstellen} showOrg>
                {#snippet actions(ls)}
                    {#if $auth.is_superadmin}
                        <div>
                            <button class="btn-small" onclick={() => openEditLs(ls)}>✎</button>
                            <button class="btn-small danger" onclick={() => deleteLs(ls)}>✕</button>
                        </div>
                    {/if}
                {/snippet}
            </LeitstellenTable>
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

        <!-- ── E-Mail-Template ── -->
        <div class="et-section">
            <div class="et-header">
                <h2>E-Mail-Template</h2>
                {#if emailTemplate}
                    {#if emailTemplate.is_custom}
                        <span class="badge et-badge-custom">Angepasst</span>
                    {:else}
                        <span class="badge et-badge-default">Standard</span>
                    {/if}
                {/if}
            </div>

            {#if emailTemplateError}
                <div class="error-bar">{emailTemplateError} <button onclick={() => emailTemplateError = ''}>✕</button></div>
            {/if}
            {#if emailTemplateSuccess}
                <div class="success-bar">{emailTemplateSuccess}</div>
            {/if}

            <div class="bf-section">
                <label class="bf-label">Betreff
                    <input type="text" bind:value={emailTemplateForm.subject} placeholder="Deine Zugangsdaten für &#123;app_name&#125;" />
                </label>
            </div>

            <div class="bf-section">
                <label class="bf-label">HTML-Template
                    <textarea
                        bind:value={emailTemplateForm.html}
                        class="et-textarea"
                        spellcheck="false"
                        placeholder="<!DOCTYPE html>..."
                    ></textarea>
                </label>
            </div>

            <!-- Variablen-Referenz -->
            <div class="et-vars-panel">
                <button class="et-vars-toggle" onclick={() => emailTemplateVarsOpen = !emailTemplateVarsOpen}>
                    {emailTemplateVarsOpen ? '▾' : '▸'} Verfügbare Variablen
                </button>
                {#if emailTemplateVarsOpen}
                    <table class="et-vars-table">
                        <thead>
                            <tr><th>Variable</th><th>Bedeutung</th></tr>
                        </thead>
                        <tbody>
                            <tr><td><code>{'{recipient_name}'}</code></td><td>Name des Empfängers</td></tr>
                            <tr><td><code>{'{email}'}</code></td><td>E-Mail-Adresse</td></tr>
                            <tr><td><code>{'{password}'}</code></td><td>Generiertes Passwort</td></tr>
                            <tr><td><code>{'{login_url}'}</code></td><td>Login-URL</td></tr>
                            <tr><td><code>{'{app_name}'}</code></td><td>App-Name (aus Branding)</td></tr>
                            <tr><td><code>{'{logo_block}'}</code></td><td>Logo-Block (automatisch aus Branding)</td></tr>
                            <tr><td><code>{'{color_primary}'}</code></td><td>Primärfarbe (aus Branding)</td></tr>
                            <tr><td><code>{'{color_primary_hover}'}</code></td><td>Primärfarbe hover</td></tr>
                        </tbody>
                    </table>
                {/if}
            </div>

            <div class="bf-actions" style="margin-top:1rem">
                <button class="btn-secondary" onclick={previewEmailTemplate}>Vorschau</button>
                <button
                    class="btn-secondary"
                    onclick={resetEmailTemplate}
                    disabled={emailTemplateResetting || !emailTemplate?.is_custom}
                >
                    {emailTemplateResetting ? '…' : 'Auf Standard zurücksetzen'}
                </button>
                <button class="btn-primary" onclick={saveEmailTemplate} disabled={emailTemplateSaving}>
                    {emailTemplateSaving ? 'Wird gespeichert…' : 'Speichern'}
                </button>
            </div>
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

            {#if updateChannel}
                <div class="update-row" style="margin-bottom:.75rem; flex-wrap:wrap;">
                    <span class="update-label">Update-Kanal</span>
                    <div class="channel-toggle">
                        <button
                            class="channel-btn"
                            class:active={updateChannel.channel === 'stable'}
                            disabled={channelSaving}
                            onclick={() => setChannel('stable')}
                        >Stable</button>
                        <button
                            class="channel-btn"
                            class:active={updateChannel.channel === 'beta'}
                            disabled={channelSaving}
                            onclick={() => setChannel('beta')}
                        >Beta</button>
                        <button
                            class="channel-btn"
                            class:active={updateChannel.channel === 'nightly'}
                            disabled={channelSaving}
                            onclick={() => setChannel('nightly')}
                        >Nightly</button>
                    </div>
                </div>
                <p class="hint" style="margin:-.25rem 0 1rem;">
                    {#if updateChannel.channel === 'stable'}
                        <strong>Stable:</strong> Updates nur bei veröffentlichten GitHub-Releases — einzelne Commits auf <code>main</code> lösen kein Update aus.
                    {:else if updateChannel.channel === 'beta'}
                        <strong>Beta:</strong> Nummerierte Vorabversionen (Release-Kandidaten, z. B. <code>v2026.2.1-beta.1</code>) zum gezielten Testen des nächsten Releases.
                    {:else}
                        <strong>Nightly:</strong> Jeder Commit auf <code>main</code> wird installiert, sobald seine Nightly-Images gebaut sind (ca. 10–15 Min. nach dem Merge; für Entwickler/Tester).
                    {/if}
                </p>
            {/if}

            {#if updateMode}
                <div class="update-row" style="margin-bottom:.75rem; flex-wrap:wrap;">
                    <span class="update-label">Update-Modus</span>
                    <div class="channel-toggle">
                        <button
                            class="channel-btn"
                            class:active={updateMode.mode === 'auto'}
                            disabled={modeSaving}
                            onclick={() => setMode('auto')}
                        >Automatisch</button>
                        <button
                            class="channel-btn"
                            class:active={updateMode.mode === 'notify'}
                            disabled={modeSaving}
                            onclick={() => setMode('notify')}
                        >Benachrichtigen</button>
                    </div>
                </div>
                <p class="hint" style="margin:-.25rem 0 1rem;">
                    {#if updateMode.mode === 'auto'}
                        <strong>Automatisch:</strong> Verfügbare Updates im gewählten Kanal werden ohne weiteres Zutun installiert.
                    {:else}
                        <strong>Benachrichtigen:</strong> Es wird nichts automatisch installiert. Alle Superadmins erhalten eine E-Mail, sobald im gewählten Kanal ein Update verfügbar ist (SMTP muss konfiguriert sein) — installiert wird über „Jetzt updaten".
                    {/if}
                </p>
                {#if updateMode.mode === 'auto'}
                    <label class="hint" style="margin:-.5rem 0 1rem; display:flex; align-items:center; gap:.5rem; cursor:pointer;">
                        <input
                            type="checkbox"
                            checked={updateMode.notify_on_auto}
                            disabled={modeSaving}
                            onchange={(e) => setNotifyOnAuto(e.currentTarget.checked)}
                        />
                        Nach automatischen Updates alle Superadmins per E-Mail informieren (SMTP muss konfiguriert sein)
                    </label>
                {/if}
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
                        {#if updateStatus.channel === 'nightly'}
                            <span class="update-label">Letzter Nightly-Build</span>
                        {:else if updateStatus.channel === 'beta'}
                            <span class="update-label">Neuestes Beta-Release</span>
                        {:else}
                            <span class="update-label">Neuestes Release</span>
                        {/if}
                        {#if !updateStatus.github_reachable}
                            <span class="hint">nicht erreichbar</span>
                        {:else if updateStatus.no_release}
                            <span class="hint">{updateStatus.channel === 'beta' ? 'noch kein Prerelease veröffentlicht' : 'noch kein Release veröffentlicht'}</span>
                        {:else}
                            {#if updateStatus.latest_release}
                                <code>{updateStatus.latest_release}</code>
                            {/if}
                            <code>{updateStatus.remote_sha?.slice(0, 7) ?? '—'}</code>
                        {/if}
                    </div>
                    <div class="update-row">
                        <span class="update-label">Status</span>
                        {#if !updateStatus.github_reachable}
                            <span class="badge badge-warn">GitHub nicht erreichbar</span>
                        {:else if updateStatus.no_release}
                            <span class="badge badge-ok">Kein Release — aktuell ✓</span>
                        {:else if updateStatus.ahead_of_release}
                            <span class="badge badge-ok">Neuer als letztes Release (Beta-Stand) ✓</span>
                            <span class="hint">Kein automatisches Downgrade — Stable greift wieder, sobald ein neueres Release erscheint. „Jetzt updaten" setzt bewusst auf das Release zurück.</span>
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
                            <span class="spinner"></span> Update läuft…
                        </button>
                    {:else if updateStatus.github_reachable}
                        <button
                            class="btn-primary"
                            disabled={!updateStatus.update_available}
                            onclick={triggerUpdate}
                        >
                            Jetzt updaten
                        </button>
                    {:else}
                        <button class="btn-primary" onclick={triggerUpdate}>
                            Manuell aktualisieren
                        </button>
                        <span class="hint" style="font-size:var(--text-xs)">GitHub nicht erreichbar — zieht trotzdem neueste Images</span>
                    {/if}
                    {#if showUpdateLog && !updateTriggering}
                        <button class="btn-small" onclick={() => showUpdateLog = false}>Log ausblenden</button>
                    {/if}
                </div>

                {#if showUpdateLog}
                    <div class="update-terminal" bind:this={logContainer}>
                        {#each updateLogLines as line}
                            <div class="log-line">{line}</div>
                        {/each}
                        {#if !updateLogDone}
                            <div class="log-cursor">▌</div>
                        {:else}
                            <div class="log-line log-done">─── Fertig ───</div>
                        {/if}
                    </div>
                {/if}
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

        <!-- ── Live-Verkehrslage (HERE / TomTom) ── -->
        <div class="section">
            <div class="section-header">
                <strong>Live-Verkehrslage (Stau)</strong>
            </div>

            {#if trafficError}
                <div class="error-bar">{trafficError} <button onclick={() => trafficError = ''}>✕</button></div>
            {/if}
            {#if trafficSuccess}
                <div class="success-bar">{trafficSuccess}</div>
            {/if}

            <p class="hint" style="margin-bottom:.6rem">
                Optional. Ohne Key ist die Verkehrslage aus; sobald ein Key hinterlegt ist,
                lässt sich die Echtzeit-Verkehrslage (grün→rot) entlang der Route einblenden –
                bundesweit. Kostenlose Kontingente:
                <a href="https://platform.here.com/" target="_blank" rel="noopener" style="color:var(--color-primary)">HERE</a>
                (250k Anfragen/Monat) oder
                <a href="https://developer.tomtom.com/" target="_blank" rel="noopener" style="color:var(--color-primary)">TomTom</a>.
                Hinweis: Die Anzeige dieser Daten auf der OSM-Karte kann lizenzpflichtig sein –
                bitte die Nutzungsbedingungen des Anbieters prüfen.
            </p>

            {#if trafficKeys}
                <div class="update-grid" style="margin-bottom:.75rem">
                    <div class="update-row">
                        <span class="update-label">HERE-Key</span>
                        {#if trafficKeys.here.set}
                            <span class="badge badge-ok">Gesetzt ({trafficKeys.here.source === 'env' ? 'Umgebungsvariable' : 'Datenbank'}) ✓</span>
                            {#if trafficKeys.here.source === 'db'}
                                <button class="btn-small danger" onclick={() => clearTrafficKey('here')} disabled={trafficSaving}>Entfernen</button>
                            {/if}
                        {:else}
                            <span class="badge badge-warn">Nicht konfiguriert</span>
                        {/if}
                    </div>
                    <div class="update-row">
                        <span class="update-label">TomTom-Key</span>
                        {#if trafficKeys.tomtom.set}
                            <span class="badge badge-ok">Gesetzt ({trafficKeys.tomtom.source === 'env' ? 'Umgebungsvariable' : 'Datenbank'}) ✓</span>
                            {#if trafficKeys.tomtom.source === 'db'}
                                <button class="btn-small danger" onclick={() => clearTrafficKey('tomtom')} disabled={trafficSaving}>Entfernen</button>
                            {/if}
                        {:else}
                            <span class="badge badge-warn">Nicht konfiguriert</span>
                        {/if}
                    </div>
                    <div class="update-row">
                        <span class="update-label">Aktiver Anbieter</span>
                        {#if trafficKeys.provider}
                            <span class="badge badge-ok">{trafficKeys.provider.toUpperCase()}</span>
                        {:else}
                            <span class="badge badge-warn">Keiner (kein Key)</span>
                        {/if}
                    </div>
                </div>
            {/if}

            <label class="hint" style="display:block;margin-bottom:.25rem">HERE-API-Key</label>
            <div class="license-input-row" style="margin-bottom:.5rem">
                <input
                    type="password"
                    class="license-input"
                    placeholder={trafficKeys?.here.set ? '••• Key ersetzen •••' : 'HERE apiKey'}
                    bind:value={hereKeyInput}
                    autocomplete="off"
                />
            </div>

            <label class="hint" style="display:block;margin-bottom:.25rem">TomTom-API-Key</label>
            <div class="license-input-row" style="margin-bottom:.5rem">
                <input
                    type="password"
                    class="license-input"
                    placeholder={trafficKeys?.tomtom.set ? '••• Key ersetzen •••' : 'TomTom key'}
                    bind:value={tomtomKeyInput}
                    autocomplete="off"
                />
            </div>

            <label class="hint" style="display:block;margin-bottom:.25rem">Bevorzugter Anbieter (bei zwei Keys)</label>
            <div class="license-input-row">
                <select class="license-input" bind:value={trafficProviderInput}>
                    <option value="">Automatisch (HERE bevorzugt)</option>
                    <option value="here">HERE</option>
                    <option value="tomtom">TomTom</option>
                </select>
                <button class="btn-primary" onclick={saveTrafficKeys} disabled={trafficSaving}>
                    {trafficSaving ? '…' : 'Speichern'}
                </button>
            </div>
        </div>

        <!-- ── Demo-Modus ── -->
        <div class="section">
            <div class="section-header">
                <strong>Demo-Modus</strong>
            </div>

            {#if demoSettingsError}
                <div class="error-bar">{demoSettingsError} <button onclick={() => demoSettingsError = ''}>✕</button></div>
            {/if}
            {#if demoSettingsSuccess}
                <div class="success-bar">{demoSettingsSuccess}</div>
            {/if}

            {#if demoSettings}
                <div class="update-grid" style="margin-bottom:.75rem">
                    <div class="update-row">
                        <span class="update-label">Status</span>
                        {#if demoSettings.enabled}
                            <span class="badge badge-ok">Aktiv ({demoSettings.source === 'env' ? 'Umgebungsvariable' : 'Datenbank'}) ✓</span>
                        {:else}
                            <span class="badge badge-warn">Deaktiviert</span>
                        {/if}
                    </div>
                </div>

                <p class="hint" style="margin-bottom:.6rem">
                    Bei aktivem Demo-Modus erscheint auf der Startseite ein „Demo ausprobieren"-Button.
                    Besucher erhalten ohne Registrierung eine eigene temporäre Organisation, die nach
                    {demoSettings.session_hours} Stunden automatisch gelöscht wird (max. 10 Demo-Starts pro Stunde pro IP).
                </p>

                <div style="display:flex; align-items:center; gap:.75rem; flex-wrap:wrap; margin-bottom:.75rem">
                    <button
                        class={demoSettings.enabled ? 'btn-small danger' : 'btn-primary'}
                        onclick={toggleDemo}
                        disabled={demoSaving}
                    >
                        {demoSaving ? '…' : demoSettings.enabled ? 'Demo-Modus deaktivieren' : 'Demo-Modus aktivieren'}
                    </button>
                    <span class="update-label" style="margin-left:.5rem">Laufzeit</span>
                    <input
                        type="number"
                        min="1"
                        max="720"
                        bind:value={demoHoursInput}
                        style="width:5rem; padding:.35rem .5rem; border:1px solid var(--border); border-radius:6px; background:var(--surface-2); color:var(--text-1)"
                    />
                    <span class="hint">Stunden</span>
                    <button
                        class="btn-small"
                        onclick={saveDemoHours}
                        disabled={demoHoursSaving || demoHoursInput === demoSettings.session_hours}
                    >
                        {demoHoursSaving ? '…' : 'Speichern'}
                    </button>
                </div>
                <p class="hint" style="margin-bottom:.6rem; font-size:var(--text-xs)">
                    Gilt für neue Demo-Sitzungen. Bestehende Sitzungen behalten ihr Ablaufdatum — einzeln verlängerbar über „+24 h".
                </p>

                <div class="section-header" style="margin-top:1.25rem">
                    <strong>Offene Demo-Sitzungen ({demoSessions.length})</strong>
                    <button class="btn-small" onclick={loadDemoSettings} title="Aktualisieren">⟳</button>
                </div>
                {#if demoSessions.length === 0}
                    <p class="hint">Keine offenen Demo-Sitzungen.</p>
                {:else}
                    <table class="user-table">
                        <thead>
                            <tr>
                                <th>Name</th>
                                <th>Code (Slug)</th>
                                <th>Gestartet</th>
                                <th>Läuft ab</th>
                                <th>Herkunft</th>
                                <th>Marschverbände</th>
                                <th></th>
                            </tr>
                        </thead>
                        <tbody>
                            {#each demoSessions as session}
                                <tr>
                                    <td>{session.name}</td>
                                    <td><code>{session.slug}</code></td>
                                    <td class="hint">{new Date(session.created_at).toLocaleString('de-DE', { day:'2-digit', month:'2-digit', hour:'2-digit', minute:'2-digit' })}</td>
                                    <td class="hint">{new Date(session.expires_at).toLocaleString('de-DE', { day:'2-digit', month:'2-digit', hour:'2-digit', minute:'2-digit' })}</td>
                                    <td>
                                        {#if session.created_location || session.created_ip}
                                            {#if session.created_location}
                                                {session.created_location}<br>
                                            {/if}
                                            {#if session.created_ip}
                                                <code class="hint" title="IP-Adresse bei Sitzungsstart">{session.created_ip}</code>
                                            {/if}
                                        {:else}
                                            <span class="hint">–</span>
                                        {/if}
                                    </td>
                                    <td>{session.convoy_count}</td>
                                    <td class="actions-cell">
                                        <div>
                                            <button
                                                class="btn-small"
                                                onclick={() => extendDemoSession(session)}
                                                disabled={extendingDemoSession === session.id}
                                                title="Ablauf um 24 Stunden verlängern"
                                            >
                                                {extendingDemoSession === session.id ? '…' : '+24 h'}
                                            </button>
                                            <button
                                                class="btn-small danger"
                                                onclick={() => endDemoSession(session)}
                                                disabled={endingDemoSession === session.id}
                                                title="Sitzung beenden und Daten löschen"
                                            >
                                                {endingDemoSession === session.id ? '…' : '✕ Beenden'}
                                            </button>
                                        </div>
                                    </td>
                                </tr>
                            {/each}
                        </tbody>
                    </table>
                {/if}
            {:else}
                <p class="hint">Status nicht verfügbar</p>
            {/if}
        </div>

        <!-- ── Zwei-Faktor-Authentifizierung ── -->
        <div class="section">
            <div class="section-header">
                <strong>Zwei-Faktor-Authentifizierung (MFA)</strong>
            </div>

            {#if mfaError}
                <div class="error-bar">{mfaError} <button onclick={() => mfaError = ''}>✕</button></div>
            {/if}
            {#if mfaSuccess}
                <div class="success-bar">{mfaSuccess}</div>
            {/if}

            {#if mfaSetupStep === 'idle'}
                <div class="update-row" style="margin-bottom:.75rem">
                    <span class="update-label">Status</span>
                    {#if mfaEnabled}
                        <span class="badge badge-ok">Aktiv ✓</span>
                    {:else}
                        <span class="badge badge-warn">Nicht aktiv</span>
                    {/if}
                </div>

                {#if mfaEnabled}
                    <p class="hint" style="margin-bottom:.75rem">MFA ist aktiv. Zum Deaktivieren bitte Code eingeben:</p>
                    <div class="mfa-code-row">
                        <input
                            type="text"
                            inputmode="numeric"
                            maxlength="6"
                            placeholder="000000"
                            bind:value={mfaCode}
                            class="mfa-input"
                            autocomplete="one-time-code"
                        />
                        <button class="btn-small danger" onclick={disableMfa} disabled={mfaWorking || mfaCode.length < 6}>
                            {mfaWorking ? '…' : 'Deaktivieren'}
                        </button>
                    </div>
                {:else}
                    <button class="btn-primary" onclick={startMfaSetup} disabled={mfaWorking}>
                        {mfaWorking ? '…' : 'MFA einrichten'}
                    </button>
                {/if}

            {:else if mfaSetupStep === 'setup'}
                <p class="hint" style="margin-bottom:1rem">Scanne den QR-Code mit einer Authenticator-App (z.B. Authy, Google Authenticator) oder gib den Secret manuell ein.</p>
                <div class="mfa-setup-qr">
                    {#if mfaSetupQrDataUrl}
                        <img src={mfaSetupQrDataUrl} alt="MFA QR Code" class="qr-img" />
                    {/if}
                    <div class="mfa-secret-box">
                        <span class="update-label">Secret (manuell)</span>
                        <code class="mfa-secret">{mfaSetupSecret}</code>
                    </div>
                </div>
                <p class="hint" style="margin:.75rem 0 .5rem">Danach Code eingeben um MFA zu aktivieren:</p>
                <div class="mfa-code-row">
                    <input
                        type="text"
                        inputmode="numeric"
                        maxlength="6"
                        placeholder="000000"
                        bind:value={mfaCode}
                        class="mfa-input"
                        autocomplete="one-time-code"
                    />
                    <button class="btn-primary" onclick={confirmMfa} disabled={mfaWorking || mfaCode.length < 6}>
                        {mfaWorking ? '…' : 'Bestätigen'}
                    </button>
                    <button class="btn-small" onclick={() => { mfaSetupStep = 'idle'; mfaCode = ''; }}>Abbrechen</button>
                </div>
            {/if}
        </div>

        <!-- ── E-Mail / SMTP ── -->
        <div class="section">
            <div class="section-header">
                <strong>E-Mail (SMTP)</strong>
            </div>

            {#if smtpError}
                <div class="error-bar">{smtpError} <button onclick={() => smtpError = ''}>✕</button></div>
            {/if}
            {#if smtpSuccess}
                <div class="success-bar">{smtpSuccess}</div>
            {/if}

            <div class="smtp-grid">
                <label class="smtp-label">Host
                    <input type="text" bind:value={smtpForm.host} placeholder="smtp.example.com" autocomplete="off" />
                </label>
                <label class="smtp-label smtp-port">Port
                    <input type="number" bind:value={smtpForm.port} min="1" max="65535" />
                </label>
                <label class="smtp-label">Sicherheit
                    <select bind:value={smtpForm.use_tls}>
                        <option value="starttls">STARTTLS (Port 587)</option>
                        <option value="ssl">SSL/TLS (Port 465)</option>
                        <option value="false">Kein TLS (unsicher)</option>
                    </select>
                </label>
                <label class="smtp-label">Benutzername
                    <input type="text" bind:value={smtpForm.username} placeholder="user@example.com" autocomplete="off" />
                </label>
                <label class="smtp-label">
                    Passwort {#if smtpConfig?.password_set}<span class="hint">(gesetzt — leer lassen = nicht ändern)</span>{/if}
                    <div class="smtp-pw-row">
                        <input
                            type={showSmtpPassword ? 'text' : 'password'}
                            bind:value={smtpForm.password}
                            placeholder={smtpConfig?.password_set ? '••••••••' : 'Passwort'}
                            autocomplete="new-password"
                        />
                        <button type="button" class="btn-small" onclick={() => showSmtpPassword = !showSmtpPassword}>
                            {showSmtpPassword ? '🙈' : '👁'}
                        </button>
                    </div>
                </label>
                <label class="smtp-label">Absender-E-Mail
                    <input type="email" bind:value={smtpForm.from_email} placeholder="noreply@example.com" />
                </label>
                <label class="smtp-label">Absender-Name
                    <input type="text" bind:value={smtpForm.from_name} placeholder="ConvoyPlan" />
                </label>
            </div>

            <div style="margin-top:1rem; display:flex; gap:.5rem; flex-wrap:wrap;">
                <button class="btn-primary" onclick={saveSmtp} disabled={smtpSaving}>
                    {smtpSaving ? '…' : 'Speichern'}
                </button>
                <button class="btn-secondary" onclick={testSmtp} disabled={smtpTesting || !smtpConfig?.configured}>
                    {smtpTesting ? 'Teste…' : 'Verbindung testen'}
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
                        <div class="name-input-row">
                            <label style="flex:1">Vorname
                                <input type="text" bind:value={editUserForm.first_name} placeholder="Vorname" />
                            </label>
                            <label style="flex:1">Nachname
                                <input type="text" bind:value={editUserForm.last_name} placeholder="Nachname" />
                            </label>
                        </div>
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

                <!-- Datenschutz (DSGVO) -->
                <div class="edit-section">
                    <p class="edit-section-title">Datenschutz (DSGVO)</p>
                    <div class="dsgvo-actions">
                        <button class="btn-small" onclick={() => exportUserData(editingUser!)} disabled={dsgvoWorking}>
                            ⬇ Daten exportieren
                        </button>
                        <button class="btn-small danger" onclick={() => eraseUserData(editingUser!)} disabled={dsgvoWorking}>
                            🗑 Daten löschen (Art. 17)
                        </button>
                    </div>
                    <p class="hint" style="margin-top:.4rem">
                        Export = alle gespeicherten Daten als JSON (Art. 15). Löschen entfernt den
                        Benutzer samt abhängiger Daten; der Audit-Trail wird pseudonymisiert beibehalten.
                    </p>
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

<!-- ── Edit Org Owner Modal ── -->
{#if showEditOrgModal && editingOrg}
    <div class="modal-backdrop" onclick={() => (showEditOrgModal = false)}>
        <div class="modal" style="max-width:440px" onclick={(e) => e.stopPropagation()}>
            <div class="modal-header">
                <h2>Inhaber ändern</h2>
                <button onclick={() => (showEditOrgModal = false)}>✕</button>
            </div>
            <div class="modal-body">
                <p class="hint" style="margin-bottom:.75rem">Organisation: <strong>{editingOrg.name}</strong></p>
                {#if editOrgError}
                    <div class="error-bar" style="margin-bottom:.75rem">{editOrgError} <button onclick={() => (editOrgError = '')}>✕</button></div>
                {/if}
                <div class="ls-form">
                    <label>Neuer Inhaber *
                        <select bind:value={editOrgOwnerId}>
                            <option value="">– Benutzer wählen –</option>
                            {#each users as u}
                                <option value={u.id}>{u.email}</option>
                            {/each}
                        </select>
                    </label>
                </div>
            </div>
            <div class="modal-footer">
                <button onclick={() => (showEditOrgModal = false)}>Abbrechen</button>
                <button class="btn-primary" onclick={saveOrgOwner}
                    disabled={editOrgSaving || !editOrgOwnerId}>
                    {editOrgSaving ? 'Speichern…' : 'Speichern'}
                </button>
            </div>
        </div>
    </div>
{/if}

<!-- ── Leitstelle Modal ── -->
{#if showLsModal}
    <div class="modal-backdrop" onclick={() => { showLsModal = false; }}>
        <div class="modal" onclick={(e) => e.stopPropagation()}>
            <div class="modal-header">
                <h2>{editingLs ? 'Leitstelle bearbeiten' : 'Neue Leitstelle'}</h2>
                <button onclick={() => { showLsModal = false; }}>✕</button>
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
                        {#key areaPickerKey}
                            <LeitstelleAreaPicker
                                initialGeo={editingGeo}
                                takenCodes={takenCodes}
                                takenOwnerByCode={takenOwnerByCode}
                                onchange={(s) => (areaSel = s)}
                            />
                        {/key}
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
                                            editingGeo = (editingLs.geometry_geojson as GeoJSON.Geometry) ?? null;
                                            areaSel = null;
                                            areaPickerKey++;
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
                <button onclick={() => { showLsModal = false; }}>Abbrechen</button>
                <button class="btn-primary" onclick={saveLs} disabled={!lsForm.name || !lsForm.anrufgruppe}>Speichern</button>
            </div>
        </div>
    </div>
{/if}
{:else}
    <SuperadminLogin onsuccess={handleAuthenticated} />
{/if}

<style>
    :global(body) { margin: 0; font-family: system-ui, sans-serif; background: var(--bg); color: var(--text-1); }
    .admin-page { max-width: 900px; margin: 0 auto; padding: 2rem 1rem; }
    .admin-header { display: flex; align-items: center; justify-content: space-between; margin-bottom: 1rem; }
    h1 { margin: 0; font-size: var(--text-lg); }
    .back-link { color: var(--text-2); font-size: var(--text-sm); text-decoration: none; }
    .back-link:hover { color: var(--text-1); }
    .header-actions { display: flex; align-items: center; gap: 1rem; }
    .logout-btn {
        padding: .4rem .8rem;
        background: var(--surface-2);
        color: var(--text-1);
        border: 1px solid var(--border);
        border-radius: 6px;
        font-size: var(--text-sm);
        cursor: pointer;
    }
    .logout-btn:hover { background: var(--surface-1); border-color: var(--color-primary); color: var(--color-primary); }

    .tab-bar { display: flex; gap: .25rem; border-bottom: 1px solid var(--border); margin-bottom: 1.5rem; padding: .25rem .25rem 0; }
    .tab { padding: .5rem 1rem; background: none; border: none; cursor: pointer; font-size: var(--text-sm); color: var(--text-2); border-radius: 4px 4px 0 0; margin-bottom: -1px; }
    .tab.active { color: var(--color-primary); background: var(--surface-2); font-weight: 600; border-bottom: 2px solid var(--color-primary); }

    .error-bar { background: var(--color-primary-hover); color: white; padding: .4rem .75rem; border-radius: 4px; margin-bottom: 1rem; display: flex; justify-content: space-between; }
    .error-bar button { background: none; border: none; color: white; cursor: pointer; }
    /* overflow-x: Breite Tabellen scrollen innerhalb der Karte statt rechts
       über den Kartenrand hinauszulaufen. */
    .section { background: var(--surface-1); border: 1px solid var(--border); border-radius: 8px; padding: 1rem; margin-bottom: 1rem; box-shadow: var(--shadow); overflow-x: auto; -webkit-overflow-scrolling: touch; }
    .section-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: .75rem; font-size: var(--text-sm); font-weight: 500; color: var(--text-1); }

    .create-form { display: flex; flex-direction: column; gap: .5rem; margin-bottom: 1rem; padding: .75rem; background: var(--surface-2); border-radius: 6px; border: 1px solid var(--border); }
    .create-form input { padding: .5rem .75rem; border-radius: 6px; border: 1px solid var(--border); background: var(--surface-1); color: var(--text-1); font-size: var(--text-sm); }
    .create-form input:focus { outline: none; border-color: var(--color-primary); }
    .create-form button[type="submit"] { align-self: flex-start; padding: .5rem 1rem; background: #6B7F4D; color: white; border: none; border-radius: 6px; cursor: pointer; font-weight: 600; font-size: var(--text-sm); }
    .pw-input-row { display: flex; align-items: center; gap: .3rem; }
    .pw-input-row .pw-field { flex: 1; }
    .org-input-row { display: flex; gap: .5rem; align-items: center; }
    .create-pw-hint { margin: 0; font-size: var(--text-sm); color: var(--text-2); line-height: 1.4; }
    .name-input-row { display: flex; gap: .5rem; }
    .name-input-row input { flex: 1; min-width: 0; }
    .create-actions { display: flex; gap: .5rem; flex-wrap: wrap; align-items: center; }
    .btn-invite { padding: .5rem 1rem; background: #3d6080; color: white; border: none; border-radius: 6px; cursor: pointer; font-weight: 600; font-size: var(--text-sm); }
    .btn-invite:hover:not(:disabled) { background: #4d77a0; }
    .btn-invite:disabled { opacity: .45; cursor: not-allowed; }
    .checkbox-label { display: flex; align-items: center; gap: .4rem; font-size: var(--text-sm); color: var(--text-2); cursor: pointer; }
    .user-table { width: 100%; border-collapse: collapse; font-size: var(--text-sm); }
    .user-table th { text-align: left; padding: .5rem; color: var(--text-muted); font-size: var(--text-xs); text-transform: uppercase; letter-spacing: .04em; border-bottom: 1px solid var(--border); }
    .user-table td { padding: .5rem; border-bottom: 1px solid var(--border); vertical-align: middle; color: var(--text-2); }
    /* Lange E-Mails (z. B. Demo-Adressen) dürfen umbrechen, damit die
       Tabelle nicht breiter als die Karte wird. */
    .user-table td.email-cell { overflow-wrap: anywhere; }
    .user-table tr.inactive td { opacity: .45; }
    .user-table tr.group-divider-row td {
        padding: .6rem .5rem .35rem;
        color: #d97706;
        font-size: var(--text-xs);
        text-transform: uppercase;
        letter-spacing: .04em;
        font-weight: 600;
        border-bottom: 1px solid color-mix(in srgb, #d97706 35%, transparent);
        background: color-mix(in srgb, #d97706 6%, transparent);
    }
    .user-table tr.demo-row td { background: color-mix(in srgb, #d97706 4%, transparent); }
    .user-table tr.demo-row td:first-child { border-left: 2px solid color-mix(in srgb, #d97706 50%, transparent); }
    .orgs-cell { display: flex; flex-wrap: wrap; gap: .25rem; align-items: center; min-height: 1.4rem; }
    .tag { display: inline-block; padding: .1rem .35rem; background: var(--surface-2); border: 1px solid var(--border); border-radius: 3px; font-size: var(--text-xs); color: var(--text-2); }
    .mfa-on { display: inline-block; padding: .1rem .4rem; background: rgba(39,174,96,.18); color: #2c9c4e; border: 1px solid rgba(39,174,96,.35); border-radius: 3px; font-size: var(--text-xs); font-weight: 600; }
    .toggle-btn { padding: .2rem .5rem; border-radius: 3px; border: 1px solid var(--border); background: var(--surface-2); color: var(--text-2); font-size: var(--text-xs); cursor: pointer; }
    .toggle-btn.on { background: rgba(107,127,77,.3); border-color: #6B7F4D; color: #a8c070; }
    .actions-cell { white-space: nowrap; }
    .actions-cell > div { display: flex; gap: .3rem; }
    .generated-pw-box { display: flex; align-items: center; gap: .3rem; margin-top: .3rem; padding: .3rem .4rem; background: var(--surface-2); border: 1px solid var(--border); border-radius: 4px; flex-wrap: nowrap; }
    .generated-pw-label { font-size: var(--text-xs); color: var(--text-muted); white-space: nowrap; }
    .generated-pw { font-size: var(--text-xs); color: var(--text-1); user-select: all; letter-spacing: .03em; }
    .btn-tiny { padding: .1rem .25rem; font-size: .65rem; border-radius: 3px; border: 1px solid var(--border); background: transparent; color: var(--text-2); cursor: pointer; line-height: 1; }
    .btn-tiny:hover { background: var(--surface-1); }
    .hint { color: var(--text-muted); font-size: var(--text-sm); }
    .dsgvo-actions { display: flex; gap: .5rem; flex-wrap: wrap; }
    code { background: var(--surface-2); padding: .1rem .3rem; border-radius: 3px; font-size: var(--text-xs); font-family: monospace; color: var(--text-1); }

    .btn-small { padding: .2rem .5rem; font-size: var(--text-xs); border-radius: 3px; border: 1px solid var(--border); background: var(--surface-2); color: var(--text-2); cursor: pointer; }
    .btn-small:hover { background: var(--surface-1); }
    .btn-small.danger { border-color: var(--color-primary); color: var(--color-primary); }
    .btn-small.active { background: #e74c3c; color: white; border-color: #e74c3c; }
    .btn-small.primary { background: #2563eb; color: #fff; border-color: #2563eb; }
    .btn-primary { padding: .5rem 1rem; background: var(--color-primary); color: white; border: none; border-radius: 6px; font-weight: 600; cursor: pointer; font-size: var(--text-sm); }
    .btn-primary:disabled { opacity: .5; cursor: not-allowed; }
    .btn-primary:hover:not(:disabled) { background: var(--color-primary-hover); }
    .btn-danger-small { padding: .2rem .6rem; font-size: var(--text-xs); border-radius: 3px; border: 1px solid #e74c3c; background: transparent; color: #e74c3c; cursor: pointer; }
    .btn-danger-small:hover:not(:disabled) { background: #e74c3c; color: white; }
    .btn-danger-small:disabled { opacity: .5; cursor: not-allowed; }

    /* API-Keys */
    .form-row { display: flex; gap: 1rem; align-items: center; }
    .form-row label { display: flex; flex-direction: column; gap: .25rem; font-size: var(--text-xs); color: var(--text-muted); }
    .form-row input, .form-row select { padding: .4rem .5rem; border: 1px solid var(--border); border-radius: 4px; background: var(--surface-2); color: var(--text-1); font-size: var(--text-sm); }
    .key-reveal { background: var(--surface-2); border: 1px solid var(--color-primary); border-radius: 6px; padding: .75rem; margin-bottom: 1rem; font-size: var(--text-sm); }
    .key-reveal-row { display: flex; align-items: center; gap: .5rem; margin-top: .5rem; flex-wrap: wrap; }
    .key-reveal-row code { word-break: break-all; flex: 1; min-width: 200px; }

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
    .channel-toggle { display: inline-flex; border: 1px solid var(--border); border-radius: 5px; overflow: hidden; }
    .channel-btn { padding: .3rem .9rem; font-size: var(--text-sm); background: var(--surface-2); color: var(--text-2); border: none; cursor: pointer; }
    .channel-btn + .channel-btn { border-left: 1px solid var(--border); }
    .channel-btn.active { background: var(--color-primary); color: #fff; }
    .channel-btn:disabled { opacity: .6; cursor: default; }
    .badge { display: inline-block; padding: .15rem .5rem; border-radius: 3px; font-size: var(--text-xs); font-weight: 600; }
    .badge-ok { background: rgba(107,127,77,.2); color: #a8c070; border: 1px solid rgba(107,127,77,.4); }
    .badge-update { background: rgba(210,120,30,.2); color: #e8a050; border: 1px solid rgba(210,120,30,.4); }
    .badge-warn { background: rgba(180,60,40,.15); color: var(--color-primary); border: 1px solid rgba(180,60,40,.3); }
    .spinner { display: inline-block; width: 12px; height: 12px; border: 2px solid rgba(255,255,255,.3); border-top-color: white; border-radius: 50%; animation: spin .7s linear infinite; vertical-align: middle; margin-right: .3rem; }
    .update-terminal {
        margin-top: .75rem;
        background: #0d1117;
        border: 1px solid #30363d;
        border-radius: 6px;
        padding: .75rem 1rem;
        font-family: 'Menlo', 'Consolas', 'Monaco', monospace;
        font-size: 12px;
        line-height: 1.6;
        color: #c9d1d9;
        max-height: 260px;
        overflow-y: auto;
        scroll-behavior: smooth;
    }
    .log-line { white-space: pre-wrap; word-break: break-all; }
    .log-done { color: #58a6ff; margin-top: .25rem; }
    .log-cursor { display: inline-block; color: #58a6ff; animation: blink 1s step-start infinite; }
    @keyframes blink { 0%, 100% { opacity: 1; } 50% { opacity: 0; } }
    .mfa-code-row { display: flex; align-items: center; gap: .5rem; flex-wrap: wrap; }
    .mfa-input { width: 120px; padding: .4rem .6rem; border: 1px solid var(--border); border-radius: 6px; background: var(--surface-2); color: var(--text-1); font-size: var(--text-base); text-align: center; letter-spacing: .15em; font-family: monospace; }
    .mfa-setup-qr { display: flex; align-items: flex-start; gap: 1.5rem; flex-wrap: wrap; margin-bottom: .5rem; }
    .qr-img { border-radius: 6px; border: 4px solid white; }
    .mfa-secret-box { display: flex; flex-direction: column; gap: .5rem; }
    .mfa-secret { display: block; font-size: 13px; letter-spacing: .08em; word-break: break-all; background: var(--surface-2); border: 1px solid var(--border); border-radius: 4px; padding: .4rem .6rem; }
    .smtp-grid { display: grid; grid-template-columns: 1fr 1fr; gap: .75rem; }
    @media (max-width: 600px) { .smtp-grid { grid-template-columns: 1fr; } }
    .smtp-port { grid-column: span 1; }
    .smtp-label { display: flex; flex-direction: column; gap: .3rem; font-size: var(--text-sm); font-weight: 500; color: var(--text-2); }
    .smtp-label input, .smtp-label select { padding: .4rem .6rem; border: 1px solid var(--border); border-radius: 6px; background: var(--surface-2); color: var(--text-1); font-size: var(--text-sm); }
    .smtp-pw-row { display: flex; gap: .3rem; }
    .smtp-pw-row input { flex: 1; }
    .success-btn { background: rgba(107,127,77,.2) !important; color: #a8c070 !important; border-color: rgba(107,127,77,.4) !important; }
    @keyframes spin { to { transform: rotate(360deg); } }

    /* E-Mail Template */
    .et-section { margin-top: 2rem; padding-top: 1.5rem; border-top: 1px solid var(--border); }
    .et-header { display: flex; align-items: center; gap: .75rem; margin-bottom: 1rem; }
    .et-header h2 { margin: 0; font-size: var(--text-base); font-weight: 600; color: var(--text-1); }
    .et-badge-custom { background: rgba(210,120,30,.2); color: #e8a050; border: 1px solid rgba(210,120,30,.4); }
    .et-badge-default { background: var(--surface-2); color: var(--text-muted); border: 1px solid var(--border); }
    .et-textarea {
        width: 100%;
        height: 400px;
        resize: vertical;
        font-family: 'Menlo', 'Consolas', 'Monaco', monospace;
        font-size: 12px;
        line-height: 1.5;
        padding: .5rem .75rem;
        border: 1px solid var(--border);
        border-radius: 6px;
        background: var(--surface-2);
        color: var(--text-1);
        box-sizing: border-box;
    }
    .et-textarea:focus { outline: none; border-color: var(--color-primary); }
    .et-vars-panel { margin-bottom: .75rem; }
    .et-vars-toggle { background: none; border: none; cursor: pointer; font-size: var(--text-sm); color: var(--color-primary); padding: 0; font-weight: 500; }
    .et-vars-table { width: 100%; border-collapse: collapse; font-size: var(--text-xs); margin-top: .5rem; }
    .et-vars-table th { text-align: left; padding: .3rem .5rem; color: var(--text-muted); text-transform: uppercase; letter-spacing: .04em; border-bottom: 1px solid var(--border); }
    .et-vars-table td { padding: .3rem .5rem; border-bottom: 1px solid var(--border); color: var(--text-2); vertical-align: middle; }
    .et-vars-table tr:last-child td { border-bottom: none; }

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

    /* ── Mobile (≤ 768px) ───────────────────────────────────────── */
    @media (max-width: 768px) {
        .admin-page {
            padding: 1rem .75rem calc(1rem + env(safe-area-inset-bottom));
            padding-left: max(.75rem, env(safe-area-inset-left));
            padding-right: max(.75rem, env(safe-area-inset-right));
        }
        .admin-header { margin-bottom: .75rem; }

        /* Tabs scroll horizontally instead of squashing — touch-friendly. */
        .tab-bar {
            overflow-x: auto;
            flex-wrap: nowrap;
            scrollbar-width: none;
            -webkit-overflow-scrolling: touch;
            margin: 0 -.75rem 1rem;
            padding: .25rem .75rem 0;
        }
        .tab-bar::-webkit-scrollbar { display: none; }
        .tab { flex-shrink: 0; padding: .55rem .85rem; font-size: var(--text-sm); }

        .section { padding: .75rem; }
        .section :global(table) { white-space: nowrap; }

        .branding-panel {
            padding: 1rem .75rem;
            max-width: 100%;
        }
        .colors-grid { grid-template-columns: 1fr; }
        .logo-row { gap: 1rem; }
        .bf-actions {
            flex-direction: column-reverse;
            align-items: stretch;
            gap: .5rem;
        }
        .bf-actions > * { width: 100%; }

        .create-actions { flex-direction: column; align-items: stretch; }
        .create-actions > * { width: 100%; }

        .update-row { flex-wrap: wrap; gap: .35rem .75rem; }
        .update-label { width: auto; }
        .license-input-row { flex-wrap: wrap; }
        .license-input { min-width: 0; }

        /* Modal: edge-to-edge, footer wraps. */
        .modal {
            width: 100%;
            max-width: calc(100vw - 1rem);
            max-height: calc(100dvh - 1rem);
        }
        .modal-body { padding: .75rem; }
        .modal-footer {
            flex-wrap: wrap;
            padding-bottom: calc(.75rem + env(safe-area-inset-bottom));
        }
        .modal-footer > * { flex: 1 1 auto; min-width: 0; }

        .et-textarea { height: 240px; font-size: 13px; }
        .update-terminal { font-size: 11px; max-height: 200px; }
    }
</style>
