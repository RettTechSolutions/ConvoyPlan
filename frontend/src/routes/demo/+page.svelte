<script lang="ts">
    import { onMount } from 'svelte';
    import { goto } from '$app/navigation';
    import { authApi } from '$lib/api';
    import { demoFailure, formatRetryAt } from '$lib/demo-error';
    import { orgStore } from '$lib/stores/org';
    import AppLogo from '$lib/components/AppLogo.svelte';

    // 'checking' → Demo-Verfügbarkeit wird geprüft, 'form' → Kontaktangabe,
    // 'starting' → Umgebung wird angelegt, 'error' → Absage mit Begründung.
    let phase = $state<'checking' | 'form' | 'starting' | 'error'>('checking');
    let error = $state('');
    let retryAt = $state<Date | null>(null);
    let sessionHours = $state(24);

    let email = $state('');
    let firstName = $state('');
    let lastName = $state('');

    onMount(async () => {
        try {
            const status = await authApi.demoStatus();
            if (!status.enabled) {
                error = 'Die Demo ist derzeit nicht verfügbar.';
                phase = 'error';
                return;
            }
            sessionHours = status.session_hours;
            phase = 'form';
        } catch {
            error = 'Die Demo ist derzeit nicht erreichbar.';
            phase = 'error';
        }
    });

    async function start(event: SubmitEvent) {
        event.preventDefault();
        phase = 'starting';
        try {
            const result = await authApi.createDemoSession({
                email: email.trim(),
                first_name: firstName.trim() || undefined,
                last_name: lastName.trim() || undefined,
            });
            orgStore.setToken(result.org_slug, result.access_token);
            goto(`/o/${result.org_slug}/plan${result.resumed ? '?resumed=1' : ''}`, { replaceState: true });
        } catch (err) {
            const failure = demoFailure(err);
            error = failure.message;
            retryAt = failure.retryAt;
            phase = 'error';
        }
    }
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

        {#if phase === 'error'}
            <p class="error">{error}</p>
            {#if retryAt}
                <p class="retry">Wieder möglich ab {formatRetryAt(retryAt)}</p>
            {/if}
            <a href="/" class="back-link">Zur Startseite →</a>
        {:else if phase === 'starting'}
            <div class="spinner"></div>
            <p class="status">Deine Demo-Umgebung wird vorbereitet…</p>
            <p class="hint">Eigene temporäre Umgebung · {sessionHours} Stunden</p>
        {:else if phase === 'form'}
            <p class="status">Demo starten</p>
            <p class="hint">
                Eigene temporäre Umgebung für {sessionHours} Stunden — danach wird sie
                samt aller Testdaten gelöscht.
            </p>

            <form onsubmit={start}>
                <label for="demo-email">E-Mail-Adresse *</label>
                <input
                    id="demo-email"
                    type="email"
                    bind:value={email}
                    required
                    autocomplete="email"
                    placeholder="name@organisation.de"
                />

                <div class="name-row">
                    <div>
                        <label for="demo-first">Vorname</label>
                        <input id="demo-first" type="text" bind:value={firstName}
                               autocomplete="given-name" maxlength="100" />
                    </div>
                    <div>
                        <label for="demo-last">Nachname</label>
                        <input id="demo-last" type="text" bind:value={lastName}
                               autocomplete="family-name" maxlength="100" />
                    </div>
                </div>

                <button type="submit" class="submit-btn">▶ Demo starten</button>
            </form>

            <p class="privacy">
                Kein Konto, keine Registrierung — die Adresse dient dazu, deine Sitzung
                zuzuordnen. Nach Ablauf der Demo bekommst du einmalig eine E-Mail mit der
                Nachfrage, ob alles gepasst hat; abbestellen geht dort mit einem Klick.
                <a href="https://convoyplan.de/datenschutz" target="_blank" rel="noopener">Datenschutz</a>
            </p>
        {:else}
            <div class="spinner"></div>
            <p class="status">Einen Moment…</p>
        {/if}
    </div>
</div>

<style>
    .demo-container {
        display: flex;
        align-items: center;
        justify-content: center;
        /* 100dvh + Safe-Area-Padding: mittig im sichtbaren Viewport, Hintergrund
           reicht bis unter Statusleiste/Toolbar (siehe app.html). */
        min-height: 100vh;
        min-height: 100dvh;
        padding: env(safe-area-inset-top) env(safe-area-inset-right) env(safe-area-inset-bottom) env(safe-area-inset-left);
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
    form { margin-top: 1.5rem; text-align: left; }
    label {
        display: block;
        font-size: var(--text-sm);
        font-weight: 600;
        color: var(--text-2);
        margin-bottom: .25rem;
    }
    input {
        width: 100%;
        box-sizing: border-box;
        padding: .6rem .75rem;
        margin-bottom: .85rem;
        border: 1px solid var(--border);
        border-radius: 6px;
        background: var(--surface-2, var(--surface-1));
        color: var(--text-1);
        font-size: var(--text-base);
    }
    input:focus {
        outline: none;
        border-color: var(--color-primary);
    }
    .name-row {
        display: flex;
        gap: .75rem;
    }
    .name-row > div { flex: 1; min-width: 0; }
    .submit-btn {
        width: 100%;
        padding: .75rem;
        margin-top: .25rem;
        border: none;
        border-radius: 6px;
        background: var(--color-primary);
        color: #fff;
        font-size: var(--text-base);
        font-weight: 600;
        cursor: pointer;
    }
    .submit-btn:hover { background: var(--color-primary-hover, var(--color-primary)); }
    .privacy {
        margin: 1rem 0 0;
        font-size: var(--text-xs, .75rem);
        line-height: 1.5;
        color: var(--text-2);
        text-align: left;
    }
    .privacy a { color: var(--color-primary); }
    .error {
        color: var(--color-primary);
        font-size: var(--text-base);
        margin: 0 0 1rem;
    }
    .retry {
        color: var(--text-1);
        font-size: var(--text-sm);
        font-weight: 600;
        margin: -.5rem 0 1rem;
    }
    .back-link {
        color: var(--color-primary);
        font-weight: 600;
        text-decoration: none;
    }
    .back-link:hover { text-decoration: underline; }
</style>
