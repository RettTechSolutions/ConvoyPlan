<script lang="ts">
    import { goto } from '$app/navigation';
    import { page } from '$app/stores';
    import { onMount } from 'svelte';
    import { orgStore } from '$lib/stores/org';
    import { orgAuthApi } from '$lib/api';
    import { setActiveSlug } from '$lib/api/client';
    import AppLogo from '$lib/components/AppLogo.svelte';

    const slug = $derived(($page.params as Record<string, string>).slug);
    let orgName = $state('');
    let email = $state('');
    let password = $state('');
    let error = $state('');
    let loading = $state(false);

    // MFA step
    let mfaRequired = $state(false);
    let mfaToken = $state('');
    let mfaCode = $state('');

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
            if (data.mfa_required && data.mfa_token) {
                mfaRequired = true;
                mfaToken = data.mfa_token;
                return;
            }
            if (data.access_token) {
                orgStore.setToken(slug, data.access_token);
                orgStore.setFromToken(slug, orgName, data.access_token);
                goto(`/o/${slug}/plan`);
            }
        } catch (e: unknown) {
            error = e instanceof Error ? e.message : 'Login fehlgeschlagen';
        } finally {
            loading = false;
        }
    }

    async function handleMfa() {
        if (mfaCode.length < 6) return;
        loading = true;
        error = '';
        try {
            const data = await orgAuthApi.mfaVerify(mfaToken, mfaCode);
            if (data.access_token) {
                orgStore.setToken(slug, data.access_token);
                orgStore.setFromToken(slug, orgName, data.access_token);
                goto(`/o/${slug}/plan`);
            }
        } catch (e: unknown) {
            error = e instanceof Error ? e.message : 'Ungültiger Code';
        } finally {
            loading = false;
        }
    }
</script>

<div class="login-container">
    <div class="login-card">
        <div class="login-logo">
            <AppLogo variant="main" height={140} />
        </div>

        {#if orgName}
            <div class="org-header">
                <p class="org-label">Anmelden bei</p>
                <h1>{orgName}</h1>
            </div>
        {/if}

        {#if !mfaRequired}
            <form onsubmit={(e) => { e.preventDefault(); handleLogin(); }}>
                <div class="field">
                    <label for="email">E-Mail</label>
                    <input id="email" type="email" bind:value={email} placeholder="E-Mail" autocomplete="email" required />
                </div>
                <div class="field">
                    <label for="password">Passwort</label>
                    <input id="password" type="password" bind:value={password} placeholder="Passwort" autocomplete="current-password" required />
                </div>
                {#if error}
                    <p class="error">{error}</p>
                {/if}
                <button type="submit" disabled={loading}>
                    {loading ? 'Anmelden…' : 'Anmelden'}
                </button>
            </form>
        {:else}
            <form onsubmit={(e) => { e.preventDefault(); handleMfa(); }}>
                <p class="mfa-hint">Gib den 6-stelligen Code aus deiner Authenticator-App ein.</p>
                <div class="field">
                    <label for="mfa-code">Authentifizierungscode</label>
                    <input
                        id="mfa-code"
                        type="text"
                        inputmode="numeric"
                        pattern="[0-9]*"
                        maxlength="6"
                        bind:value={mfaCode}
                        required
                        autocomplete="one-time-code"
                        placeholder="000000"
                    />
                </div>
                {#if error}
                    <p class="error">{error}</p>
                {/if}
                <button type="submit" disabled={loading || mfaCode.length < 6}>
                    {loading ? 'Prüfe…' : 'Bestätigen'}
                </button>
                <button type="button" class="btn-back" onclick={() => { mfaRequired = false; mfaCode = ''; error = ''; }}>
                    ← Zurück
                </button>
            </form>
        {/if}

        <a href="/" class="back-link">← Andere Organisation</a>
    </div>
</div>

<style>
    .login-container {
        display: flex;
        align-items: center;
        justify-content: center;
        min-height: 100vh;
        background: var(--bg);
    }
    .login-card {
        background: var(--surface-1);
        border: 1px solid var(--border);
        border-radius: 8px;
        padding: 2.5rem;
        width: 100%;
        max-width: 380px;
        box-shadow: var(--shadow);
    }
    .login-logo {
        display: flex;
        justify-content: center;
        margin-bottom: 1rem;
    }
    .org-header {
        text-align: center;
        margin-bottom: 1.5rem;
    }
    .org-label {
        color: var(--text-muted);
        margin: 0 0 .25rem;
        font-size: var(--text-sm);
        letter-spacing: .04em;
    }
    h1 {
        margin: 0;
        font-size: 1.35rem;
        color: var(--text-1);
    }
    .field { margin-bottom: 1rem; }
    label {
        display: block;
        font-size: var(--text-sm);
        font-weight: 500;
        margin-bottom: .25rem;
        color: var(--text-2);
    }
    input {
        width: 100%;
        padding: .5rem .75rem;
        border: 1px solid var(--border);
        border-radius: 6px;
        font-size: var(--text-base);
        box-sizing: border-box;
        background: var(--surface-2);
        color: var(--text-1);
    }
    input:focus {
        outline: none;
        border-color: var(--color-primary);
        box-shadow: 0 0 0 3px rgba(226, 61, 40, .15);
    }
    button {
        width: 100%;
        padding: .6rem;
        background: var(--color-primary);
        color: white;
        border: none;
        border-radius: 6px;
        font-size: var(--text-base);
        font-weight: 600;
        cursor: pointer;
        margin-top: .5rem;
    }
    button:hover:not(:disabled) { background: var(--color-primary-hover); }
    button:disabled { opacity: 0.6; cursor: not-allowed; }
    .btn-back {
        background: transparent;
        color: var(--text-2);
        font-weight: 400;
        font-size: var(--text-sm);
        margin-top: .25rem;
    }
    .btn-back:hover:not(:disabled) { background: var(--surface-2); }
    .error {
        color: var(--color-primary);
        font-size: var(--text-sm);
        margin-bottom: .5rem;
    }
    .mfa-hint {
        font-size: var(--text-sm);
        color: var(--text-2);
        margin-bottom: 1rem;
        line-height: 1.4;
    }
    .back-link {
        display: block;
        text-align: center;
        margin-top: 1.25rem;
        color: var(--text-muted);
        font-size: var(--text-sm);
        text-decoration: none;
    }
    .back-link:hover { color: var(--text-2); }
</style>
