<script lang="ts">
    import { onMount } from 'svelte';
    import { goto } from '$app/navigation';
    import { authApi } from '$lib/api';
    import { orgStore } from '$lib/stores/org';
    import AppLogo from '$lib/components/AppLogo.svelte';

    let error = $state('');

    onMount(async () => {
        try {
            const status = await authApi.demoStatus();
            if (!status.enabled) {
                error = 'Die Demo ist derzeit nicht verfügbar.';
                return;
            }
            const result = await authApi.createDemoSession();
            orgStore.setToken(result.org_slug, result.access_token);
            goto(`/o/${result.org_slug}/plan`, { replaceState: true });
        } catch {
            error = 'Demo konnte nicht gestartet werden. Bitte später nochmal versuchen.';
        }
    });
</script>

<svelte:head>
    <title>Demo starten – ConvoyPlan</title>
    <meta name="robots" content="noindex" />
</svelte:head>

<div class="demo-container">
    <div class="demo-card">
        <div class="demo-logo">
            <AppLogo variant="main" height={120} />
        </div>
        {#if error}
            <p class="error">{error}</p>
            <a href="/" class="back-link">Zur Startseite →</a>
        {:else}
            <div class="spinner"></div>
            <p class="status">Deine Demo-Umgebung wird vorbereitet…</p>
            <p class="hint">Eigene temporäre Umgebung · Keine Registrierung</p>
        {/if}
    </div>
</div>

<style>
    .demo-container {
        display: flex;
        align-items: center;
        justify-content: center;
        min-height: 100vh;
        background: var(--bg);
    }
    .demo-card {
        background: var(--surface-1);
        border: 1px solid var(--border);
        border-radius: 8px;
        padding: 2.5rem;
        width: 100%;
        max-width: 380px;
        box-shadow: var(--shadow);
        text-align: center;
    }
    .demo-logo { display: flex; justify-content: center; margin-bottom: 1.5rem; }
    .spinner {
        width: 28px;
        height: 28px;
        margin: 0 auto 1rem;
        border: 3px solid var(--border);
        border-top-color: var(--color-primary);
        border-radius: 50%;
        animation: spin .8s linear infinite;
    }
    @keyframes spin { to { transform: rotate(360deg); } }
    .status {
        color: var(--text-1);
        font-size: var(--text-base);
        font-weight: 600;
        margin: 0 0 .25rem;
    }
    .hint {
        color: var(--text-2);
        font-size: var(--text-sm);
        margin: 0;
    }
    .error {
        color: var(--color-primary);
        font-size: var(--text-base);
        margin: 0 0 1rem;
    }
    .back-link {
        color: var(--color-primary);
        font-weight: 600;
        text-decoration: none;
    }
    .back-link:hover { text-decoration: underline; }
</style>
