<script lang="ts">
    import { onMount } from 'svelte';
    import { page } from '$app/stores';
    import { authApi } from '$lib/api';
    import { ApiError } from '$lib/api/client';
    import AppLogo from '$lib/components/AppLogo.svelte';

    let state_ = $state<'working' | 'done' | 'failed'>('working');
    let message = $state('');

    onMount(async () => {
        const token = $page.url.searchParams.get('token') ?? '';
        if (!token) {
            state_ = 'failed';
            message = 'Dieser Abmeldelink ist unvollständig.';
            return;
        }
        try {
            await authApi.unsubscribeDemoFollowup(token);
            state_ = 'done';
        } catch (err) {
            state_ = 'failed';
            message = err instanceof ApiError && err.detail
                ? err.detail
                : 'Die Abmeldung hat nicht geklappt. Bitte antworte kurz auf die E-Mail, dann erledigen wir das von Hand.';
        }
    });
</script>

<svelte:head>
    <title>Abmelden – ConvoyPlan</title>
    <meta name="robots" content="noindex" />
</svelte:head>

<div class="container">
    <div class="card">
        <div class="logo"><AppLogo variant="main" height={100} /></div>

        {#if state_ === 'working'}
            <div class="spinner"></div>
            <p class="status">Einen Moment…</p>
        {:else if state_ === 'done'}
            <p class="status">Abgemeldet</p>
            <p class="hint">
                Zu dieser E-Mail-Adresse verschicken wir keine Nachfragen zu Demo-Zugängen mehr.
                Das gilt auch für spätere Demo-Sitzungen.
            </p>
        {:else}
            <p class="error">{message}</p>
        {/if}

        <a href="/" class="back-link">Zur Startseite →</a>
    </div>
</div>

<style>
    .container {
        display: flex;
        align-items: center;
        justify-content: center;
        min-height: 100vh;
        min-height: 100dvh;
        padding: env(safe-area-inset-top) env(safe-area-inset-right) env(safe-area-inset-bottom) env(safe-area-inset-left);
        background: var(--bg);
    }
    .card {
        background: var(--surface-1);
        border: 1px solid var(--border);
        border-radius: 8px;
        padding: 2.5rem;
        width: 100%;
        max-width: 380px;
        box-shadow: var(--shadow);
        text-align: center;
    }
    .logo { display: flex; justify-content: center; margin-bottom: 1.5rem; }
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
        margin: 0 0 .5rem;
    }
    .hint {
        color: var(--text-2);
        font-size: var(--text-sm);
        line-height: 1.5;
        margin: 0 0 1.25rem;
    }
    .error {
        color: var(--color-primary);
        font-size: var(--text-base);
        margin: 0 0 1.25rem;
    }
    .back-link {
        color: var(--color-primary);
        font-weight: 600;
        text-decoration: none;
    }
    .back-link:hover { text-decoration: underline; }
</style>
