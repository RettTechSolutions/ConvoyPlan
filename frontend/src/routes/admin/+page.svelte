<script lang="ts">
    import { onMount } from 'svelte';
    import { goto } from '$app/navigation';
    import { auth } from '$lib/stores/auth';
    import { adminApi, type AdminUser } from '$lib/api';

    let users = $state<AdminUser[]>([]);
    let loading = $state(true);
    let error = $state('');
    let showCreateForm = $state(false);
    let newUser = $state({ email: '', password: '', is_superadmin: false });

    onMount(async () => {
        if (!$auth.is_superadmin) { goto('/plan'); return; }
        await loadUsers();
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
</script>

<div class="admin-page">
    <div class="admin-header">
        <h1>Admin</h1>
        <a href="/plan" class="back-link">← Plan</a>
    </div>

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
</div>

<style>
    :global(body) { margin: 0; font-family: system-ui, sans-serif; background: #0F1B24; color: white; }
    .admin-page { max-width: 900px; margin: 0 auto; padding: 2rem 1rem; }
    .admin-header { display: flex; align-items: center; justify-content: space-between; margin-bottom: 1.5rem; }
    h1 { margin: 0; font-size: 1.4rem; }
    .back-link { color: rgba(255,255,255,.6); font-size: .9rem; text-decoration: none; }
    .back-link:hover { color: white; }
    .error-bar { background: #C23020; color: white; padding: .4rem .75rem; border-radius: 4px; margin-bottom: 1rem; display: flex; justify-content: space-between; }
    .error-bar button { background: none; border: none; color: white; cursor: pointer; }
    .section { background: rgba(255,255,255,.05); border-radius: 8px; padding: 1rem; margin-bottom: 1rem; }
    .section-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: .75rem; }
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
    .btn-small { padding: .2rem .5rem; font-size: .78rem; border-radius: 3px; border: 1px solid rgba(255,255,255,.2); background: rgba(255,255,255,.08); color: white; cursor: pointer; }
    .btn-small.danger { border-color: #E23D28; color: #E23D28; }
    .hint { color: rgba(255,255,255,.4); font-size: .85rem; }
</style>
