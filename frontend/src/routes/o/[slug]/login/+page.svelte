<script lang="ts">
    import { goto } from '$app/navigation';
    import { page } from '$app/stores';
    import { onMount } from 'svelte';
    import { orgStore } from '$lib/stores/org';
    import { orgAuthApi } from '$lib/api';
    import { setActiveSlug } from '$lib/api/client';

    const slug = $derived(($page.params as Record<string, string>).slug);
    let orgName = $state('');
    let email = $state('');
    let password = $state('');
    let error = $state('');
    let loading = $state(false);

    onMount(async () => {
        setActiveSlug(slug);

        // Bereits eingeloggt? Weiterleiten
        const existing = orgStore.getToken(slug);
        if (existing) {
            try {
                const payload = JSON.parse(atob(existing.split('.')[1]));
                if (payload.exp * 1000 > Date.now() && payload.org_slug === slug) {
                    goto(`/o/${slug}/plan`);
                    return;
                }
            } catch { /* abgelaufen oder ungültig */ }
        }

        // Org-Name für Anzeige laden
        try {
            const info = await orgAuthApi.lookup(slug);
            orgName = info.name;
        } catch {
            // Org existiert nicht → zurück zur Root
            goto('/');
        }
    });

    async function handleLogin() {
        if (!email || !password) return;
        loading = true;
        error = '';
        try {
            setActiveSlug(slug);
            const data = await orgAuthApi.loginOrg(email, password, slug);
            orgStore.setToken(slug, data.access_token);
            orgStore.setFromToken(slug, orgName, data.access_token);
            goto(`/o/${slug}/plan`);
        } catch (e: unknown) {
            error = e instanceof Error ? e.message : 'Login fehlgeschlagen';
        } finally {
            loading = false;
        }
    }
</script>

<div class="login-page">
    <div class="card">
        {#if orgName}
            <p class="org-label">Anmelden bei</p>
            <h1>{orgName}</h1>
        {:else}
            <h1>Anmelden</h1>
        {/if}

        <form onsubmit={(e) => { e.preventDefault(); handleLogin(); }}>
            <input type="email" bind:value={email} placeholder="E-Mail" autocomplete="email" />
            <input type="password" bind:value={password} placeholder="Passwort" autocomplete="current-password" />
            {#if error}
                <p class="error">{error}</p>
            {/if}
            <button type="submit" disabled={loading}>
                {loading ? 'Anmelden…' : 'Anmelden'}
            </button>
        </form>

        <a href="/" class="back-link">← Andere Organisation</a>
    </div>
</div>

<style>
    .login-page {
        display: flex;
        align-items: center;
        justify-content: center;
        min-height: 100vh;
        background: var(--color-bg, #f5f5f5);
    }
    .card {
        background: var(--color-surface, #fff);
        border-radius: 12px;
        padding: 2.5rem;
        width: 100%;
        max-width: 380px;
        box-shadow: 0 4px 24px rgba(0,0,0,0.08);
        display: flex;
        flex-direction: column;
        gap: 1rem;
    }
    .org-label { color: var(--color-text-muted, #666); margin: 0; font-size: 0.9rem; }
    h1 { margin: 0; font-size: 1.5rem; }
    input {
        width: 100%;
        padding: 0.75rem 1rem;
        border: 1px solid var(--color-border, #ddd);
        border-radius: 8px;
        font-size: 1rem;
        box-sizing: border-box;
    }
    button {
        width: 100%;
        padding: 0.75rem;
        background: var(--color-primary, #2563eb);
        color: #fff;
        border: none;
        border-radius: 8px;
        font-size: 1rem;
        cursor: pointer;
    }
    button:disabled { opacity: 0.6; }
    .error { color: #dc2626; font-size: 0.9rem; margin: 0; }
    .back-link { color: var(--color-text-muted, #666); font-size: 0.9rem; text-align: center; }
</style>
