<script lang="ts">
    import { onMount } from 'svelte';
    import { goto } from '$app/navigation';
    import { orgAuthApi, authApi } from '$lib/api';
    import { demoFailure, formatRetryAt } from '$lib/demo-error';
    import { orgStore } from '$lib/stores/org';
    import AppLogo from '$lib/components/AppLogo.svelte';
    import LegalFooter from '$lib/components/LegalFooter.svelte';

    let slugInput = $state('');
    let error = $state('');
    let loading = $state(false);
    let demoLoading = $state(false);
    let demoError = $state('');
    // Zeitpunkt der Wiederfreigabe nach der IP-Karenzzeit — als Datum, damit er
    // in der Zeitzone des Besuchers angezeigt wird.
    let demoRetryAt = $state<Date | null>(null);
    let demoAvailable = $state(false);
    let demoHours = $state(24);

    onMount(async () => {
        try {
            const status = await authApi.demoStatus();
            demoAvailable = status.enabled;
            demoHours = status.session_hours;
        } catch {
            // Backend nicht erreichbar — Demo-Bereich bleibt ausgeblendet
        }
    });

    async function handleSubmit() {
        const slug = slugInput.trim().toLowerCase();
        if (!slug) return;
        loading = true;
        error = '';
        try {
            await orgAuthApi.lookup(slug);
            goto(`/o/${slug}/login`);
        } catch {
            error = 'Organisation nicht gefunden. Bitte Code prüfen.';
        } finally {
            loading = false;
        }
    }

    async function startDemo() {
        demoLoading = true;
        demoError = '';
        demoRetryAt = null;
        try {
            const result = await authApi.createDemoSession();
            orgStore.setToken(result.org_slug, result.access_token);
            // Läuft die eigene Sitzung noch, kommt sie zurück statt einer neuen —
            // der Hinweis erklärt die Daten, die dort schon stehen.
            goto(`/o/${result.org_slug}/plan${result.resumed ? '?resumed=1' : ''}`);
        } catch (err) {
            const failure = demoFailure(err);
            demoError = failure.message;
            demoRetryAt = failure.retryAt;
        } finally {
            demoLoading = false;
        }
    }
</script>

<div class="login-container">
    <div class="login-card">
        <div class="login-logo">
            <AppLogo variant="main" height={170} />
        </div>

        <form onsubmit={(e) => { e.preventDefault(); handleSubmit(); }}>
            <div class="field">
                <label for="slug">Organisations-Code</label>
                <input
                    id="slug"
                    type="text"
                    bind:value={slugInput}
                    placeholder="z.B. rdmu"
                    autocomplete="organization"
                    spellcheck="false"
                />
            </div>
            {#if error}
                <p class="error">{error}</p>
            {/if}
            <button type="submit" disabled={loading}>
                {loading ? 'Suche…' : 'Weiter →'}
            </button>
        </form>

        {#if demoAvailable}
            <div class="demo-divider">
                <span>oder</span>
            </div>

            <button class="demo-btn" onclick={startDemo} disabled={demoLoading}>
                {demoLoading ? 'Starte Demo…' : '▶ Demo ausprobieren'}
            </button>
            {#if demoError}
                <p class="error" style="margin-top:.5rem">{demoError}</p>
                {#if demoRetryAt}
                    <p class="demo-retry">Wieder möglich ab {formatRetryAt(demoRetryAt)}</p>
                {/if}
            {/if}
            <p class="demo-hint">Eigene temporäre Umgebung · Keine Registrierung · {demoHours} Stunden</p>
        {/if}

        <LegalFooter />
    </div>
</div>

<style>
    .login-container {
        display: flex;
        align-items: center;
        justify-content: center;
        /* 100dvh statt 100vh: auf iOS entspricht 100vh der Höhe bei eingeklappter
           Toolbar — die Karte würde sonst außermittig sitzen. Safe-Area-Insets als
           Padding, damit der Hintergrund bis unter Statusleiste/Toolbar reicht. */
        min-height: 100vh;
        min-height: 100dvh;
        padding: env(safe-area-inset-top) env(safe-area-inset-right) env(safe-area-inset-bottom) env(safe-area-inset-left);
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
    .login-logo { display: flex; justify-content: center; margin-bottom: 1.5rem; }
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
    .error {
        color: var(--color-primary);
        font-size: var(--text-sm);
        margin-bottom: .5rem;
    }
    .demo-divider {
        display: flex;
        align-items: center;
        gap: .75rem;
        margin: 1.25rem 0 1rem;
        color: var(--text-2);
        font-size: var(--text-sm);
    }
    .demo-divider::before, .demo-divider::after {
        content: '';
        flex: 1;
        border-top: 1px solid var(--border);
    }
    .demo-btn {
        width: 100%;
        padding: .6rem;
        background: transparent;
        color: var(--color-primary);
        border: 1.5px solid var(--color-primary);
        border-radius: 6px;
        font-size: var(--text-base);
        font-weight: 600;
        cursor: pointer;
    }
    .demo-btn:hover:not(:disabled) {
        background: color-mix(in srgb, var(--color-primary) 10%, transparent);
    }
    .demo-btn:disabled { opacity: 0.6; cursor: not-allowed; }
    .demo-hint {
        text-align: center;
        font-size: var(--text-sm);
        color: var(--text-2);
        margin: .5rem 0 0;
    }
    /* Der genaue Zeitpunkt gehört zur Absage darüber, steht aber ruhiger da als
       die rote Begründung — er ist die Antwort, nicht die Fehlermeldung. */
    .demo-retry {
        text-align: center;
        font-size: var(--text-sm);
        font-weight: 600;
        color: var(--text-1);
        margin: .25rem 0 0;
    }
</style>
