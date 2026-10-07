<script lang="ts">
    /**
     * Anmeldung der Begleit-App über den Browser (RFC 8252).
     *
     * Die App öffnet `/authorize` in ASWebAuthenticationSession bzw. einem
     * Custom Tab, der Server leitet hierher. Diese Seite entscheidet nichts:
     * sie fragt `POST /api/oauth/app/anfrage` und folgt der Antwort.
     *
     * - 200 → zurück zur App, mit Code oder mit `access_denied`.
     * - 401 → Anmeldung der Organisation (Passwort, MFA oder Passkey) und
     *   danach hierher zurück.
     * - 409 → eine bestehende Sitzung; einmal bestätigen. Ohne diesen Klick
     *   könnte eine fremde Seite den Browser hierher schicken und den Code an
     *   die App leiten, die sich das Schema genommen hat.
     */
    import { goto } from '$app/navigation';
    import { page } from '$app/stores';
    import { onMount } from 'svelte';
    import { appOAuthApi, type AppAnfrage } from '$lib/api';
    import { ApiError } from '$lib/api/client';
    import AppLogo from '$lib/components/AppLogo.svelte';
    import LegalFooter from '$lib/components/LegalFooter.svelte';

    const ticket = $derived($page.url.searchParams.get('request') ?? '');

    let info = $state<AppAnfrage | null>(null);
    let bestaetigen = $state<{ email: string; org_name: string } | null>(null);
    let zurueck = $state('');
    let fehler = $state('');
    let arbeitet = $state(true);

    function zurAnmeldung(slug: string) {
        const hier = $page.url.pathname + $page.url.search;
        goto(`/o/${encodeURIComponent(slug)}/login?redirect=${encodeURIComponent(hier)}`);
    }

    async function entscheiden(weiter: { bestaetigt?: boolean; abbrechen?: boolean } = {}) {
        arbeitet = true;
        fehler = '';
        try {
            const { redirect_url } = await appOAuthApi.entscheiden(ticket, weiter);
            bestaetigen = null;
            zurueck = redirect_url;
            // Das eigene Schema der App — ASWebAuthenticationSession bzw. der
            // Custom Tab fängt die Navigation ab und gibt sie der App.
            window.location.href = redirect_url;
        } catch (e) {
            if (e instanceof ApiError && e.status === 401 && info) {
                zurAnmeldung(info.org_slug);
                return;
            }
            if (e instanceof ApiError && e.status === 409 && e.data?.bestaetigen) {
                bestaetigen = {
                    email: String(e.data.email ?? ''),
                    org_name: String(e.data.org_name ?? info?.org_name ?? ''),
                };
                arbeitet = false;
                return;
            }
            fehler = e instanceof Error ? e.message : 'Die Anmeldung ist fehlgeschlagen.';
        }
        arbeitet = false;
    }

    onMount(async () => {
        if (!ticket) {
            fehler = 'Diese Seite wurde ohne Anmeldeanfrage aufgerufen. Bitte die Anmeldung in der App starten.';
            arbeitet = false;
            return;
        }
        try {
            info = await appOAuthApi.anfrage(ticket);
        } catch (e) {
            fehler = e instanceof Error ? e.message : 'Die Anmeldeanfrage ist ungültig.';
            arbeitet = false;
            return;
        }
        await entscheiden();
    });
</script>

<svelte:head>
    <title>Anmeldung in der App</title>
</svelte:head>

<div class="container">
    <div class="karte">
        <div class="logo"><AppLogo variant="main" height={110} /></div>
        <h1>ConvoyPlan-App</h1>

        {#if fehler}
            <p class="fehler" role="alert">{fehler}</p>
        {:else if bestaetigen}
            <p class="text" data-testid="bestaetigen">
                In der ConvoyPlan-App als <strong>{bestaetigen.email}</strong> bei
                <strong>{bestaetigen.org_name}</strong> anmelden?
            </p>
            <p class="hinweis">
                Nur bestätigen, wenn du die Anmeldung gerade selbst in der App gestartet hast.
            </p>
            <button class="knopf" onclick={() => entscheiden({ bestaetigt: true })} disabled={arbeitet}>
                Anmelden
            </button>
            <button class="knopf zweit" onclick={() => entscheiden({ abbrechen: true })} disabled={arbeitet}>
                Abbrechen
            </button>
        {:else if zurueck}
            <p class="text">Zurück zur App …</p>
            <p class="hinweis">Falls nichts passiert: <a href={zurueck}>App öffnen</a></p>
        {:else}
            <p class="text">
                {info ? `Anmeldung bei ${info.org_name} …` : 'Einen Moment …'}
            </p>
        {/if}

        <LegalFooter />
    </div>
</div>

<style>
    .container {
        display: flex;
        align-items: center;
        justify-content: center;
        min-height: 100vh;
        min-height: 100dvh;
        padding: env(safe-area-inset-top) 1rem env(safe-area-inset-bottom);
        background: var(--bg);
    }
    .karte {
        background: var(--surface-1);
        border: 1px solid var(--border);
        border-radius: 8px;
        padding: 2rem;
        width: 100%;
        max-width: 380px;
        box-shadow: var(--shadow);
        text-align: center;
    }
    .logo { display: flex; justify-content: center; margin-bottom: .75rem; }
    h1 { margin: 0 0 1rem; font-size: 1.2rem; color: var(--text-1); }
    .text { color: var(--text-1); line-height: 1.5; margin: 0 0 .75rem; }
    .hinweis { color: var(--text-2); font-size: var(--text-sm); line-height: 1.4; margin: 0 0 1rem; }
    .hinweis a { color: var(--text-1); }
    .fehler { color: var(--color-primary); font-size: var(--text-sm); line-height: 1.4; }
    .knopf {
        width: 100%;
        padding: .6rem;
        margin-top: .5rem;
        border: none;
        border-radius: 6px;
        background: var(--color-primary);
        color: #fff;
        font-size: var(--text-base);
        font-weight: 600;
        cursor: pointer;
    }
    .knopf:hover:not(:disabled) { background: var(--color-primary-hover); }
    .knopf:disabled { opacity: .6; cursor: not-allowed; }
    .knopf.zweit { background: transparent; color: var(--text-2); border: 1px solid var(--border); font-weight: 400; }
    .knopf.zweit:hover:not(:disabled) { background: var(--surface-2); }
</style>
