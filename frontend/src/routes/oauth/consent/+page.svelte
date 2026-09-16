<script lang="ts">
    import { goto } from '$app/navigation';
    import { page } from '$app/stores';
    import { onMount } from 'svelte';
    import { mcpApi, type McpConsentRequest } from '$lib/api';
    import { getToken } from '$lib/api/client';
    import AppLogo from '$lib/components/AppLogo.svelte';
    import LegalFooter from '$lib/components/LegalFooter.svelte';

    // Das signierte Ticket aus der Weiterleitung des Authorization Servers.
    const ticket = $derived($page.url.searchParams.get('request') ?? '');

    let info = $state<McpConsentRequest | null>(null);
    let selectedOrgId = $state('');
    let error = $state('');
    let loading = $state(true);
    let working = $state(false);

    const selectedOrg = $derived(
        info?.organizations.find((o) => o.id === selectedOrgId) ?? null
    );
    // Was diese Organisation von den angefragten Rechten tatsächlich hergibt.
    // Eine Org, in der man nur beobachtet, kann kein Schreibrecht erteilen —
    // das soll vor dem Klick sichtbar sein, nicht danach.
    const grantable = $derived(
        info && selectedOrg
            ? info.requested_scopes.filter((s) => selectedOrg.grantable_scopes.includes(s.scope))
            : []
    );
    const withheld = $derived(
        info && selectedOrg
            ? info.requested_scopes.filter((s) => !selectedOrg.grantable_scopes.includes(s.scope))
            : []
    );

    onMount(async () => {
        if (!ticket) {
            error = 'Diese Seite wurde ohne Autorisierungsanfrage aufgerufen.';
            loading = false;
            return;
        }
        if (!getToken()) {
            // Nicht angemeldet: zur Anmeldung und danach hierher zurück.
            goto(`/?redirect=${encodeURIComponent($page.url.pathname + $page.url.search)}`);
            return;
        }
        try {
            info = await mcpApi.readConsentRequest(ticket);
            const erste = info.organizations.find((o) => o.grantable_scopes.length > 0);
            selectedOrgId = erste?.id ?? info.organizations[0]?.id ?? '';
        } catch (e) {
            error = e instanceof Error ? e.message : 'Die Anfrage konnte nicht geladen werden.';
        } finally {
            loading = false;
        }
    });

    /**
     * Prüft, ob eine Zieladresse angesteuert werden darf.
     *
     * Die Adresse kommt vom eigenen Backend, das sie aus einem signierten
     * Ticket gebaut hat, dessen redirect_uri wiederum gegen die registrierten
     * URIs des Clients geprüft wurde. Trotzdem wird hier noch einmal geprüft:
     * eine ungeprüfte Weiterleitung auf genau dem Bildschirm, auf dem jemand
     * gerade Zugriff erteilt, ist die klassische Open-Redirect-Lücke
     * (CWE-601) — und eine Sicherheitszusage, die an drei Stellen weiter oben
     * hängt, ist beim nächsten Umbau weg.
     *
     * Zugelassen ist dasselbe wie bei der Registrierung: HTTPS, und HTTP nur
     * auf Loopback für lokal laufende Programme (RFC 8252).
     */
    function isAllowedRedirect(raw: string): boolean {
        let url: URL;
        try {
            url = new URL(raw);
        } catch {
            return false;
        }
        if (url.protocol === 'https:') return true;
        if (url.protocol === 'http:') {
            return ['127.0.0.1', 'localhost', '[::1]', '::1'].includes(url.hostname);
        }
        return false;
    }

    async function decide(approve: boolean) {
        if (working) return;
        working = true;
        error = '';
        try {
            const result = await mcpApi.decide(ticket, approve, approve ? selectedOrgId : null);
            if (!isAllowedRedirect(result.redirect_url)) {
                error =
                    'Die Zieladresse des Programms ist nicht zulässig. Es wurde nichts erteilt.';
                working = false;
                return;
            }
            // Zurück zum Client — der übernimmt ab hier den Token-Tausch.
            window.location.assign(result.redirect_url);
        } catch (e) {
            error = e instanceof Error ? e.message : 'Die Entscheidung konnte nicht übermittelt werden.';
            working = false;
        }
    }
</script>

<svelte:head><title>Zugriff erlauben — ConvoyPlan</title></svelte:head>

<div class="wrap">
    <div class="card">
        <AppLogo />

        {#if loading}
            <p class="muted">Anfrage wird geladen …</p>
        {:else if error && !info}
            <h1>Zugriff nicht möglich</h1>
            <p class="error">{error}</p>
            <p class="muted">Bitte die Verbindung im Programm erneut starten.</p>
        {:else if info}
            <h1>Zugriff erlauben?</h1>

            <p class="lead">
                Ein Programm möchte über die KI-Schnittstelle auf ConvoyPlan zugreifen.
            </p>

            <dl class="client">
                <dt>Angegebener Name</dt>
                <dd>
                    {info.client_name}
                    <!--
                        Der Name stammt aus der Registrierung des Programms und ist
                        frei wählbar. Ihn ungekennzeichnet zu zeigen wäre die
                        Einladung zum Confused-Deputy-Angriff: ein fremdes Programm
                        nennt sich "ConvoyPlan Desktop" und der Benutzer klickt zu.
                    -->
                    <span class="badge-warn" title="Diesen Namen hat sich das Programm selbst gegeben">
                        ungeprüft
                    </span>
                </dd>
                <dt>Antwort geht an</dt>
                <dd>
                    <code>{info.redirect_host}</code>
                    <span class="badge-ok" title="Diese Adresse wurde bei der Registrierung hinterlegt und wird geprüft">
                        geprüft
                    </span>
                </dd>
            </dl>

            <p class="hint">
                Verlässlich ist nur die Zieladresse. Erlaube den Zugriff nur, wenn du
                dieses Programm gerade selbst verbunden hast und die Adresse dazu passt.
            </p>

            {#if info.organizations.length === 0}
                <p class="error">
                    Dein Konto gehört keiner Organisation an — es gibt nichts, worauf du
                    Zugriff erteilen könntest.
                </p>
            {:else}
                <label class="field">
                    <span>Organisation</span>
                    <select bind:value={selectedOrgId} disabled={working}>
                        {#each info.organizations as org (org.id)}
                            <option value={org.id} disabled={org.grantable_scopes.length === 0}>
                                {org.name} — Rolle: {org.role}
                                {org.grantable_scopes.length === 0 ? ' (keine passenden Rechte)' : ''}
                            </option>
                        {/each}
                    </select>
                </label>

                <p class="lead">Das Programm erhält damit das Recht:</p>
                <ul class="scopes">
                    {#each grantable as s (s.scope)}
                        <li>{s.label}</li>
                    {:else}
                        <li class="muted">— nichts, siehe unten</li>
                    {/each}
                </ul>

                {#if withheld.length > 0}
                    <p class="hint">
                        Angefragt, aber durch deine Rolle „{selectedOrg?.role}“ nicht gedeckt
                        und deshalb <strong>nicht</strong> erteilt:
                    </p>
                    <ul class="scopes withheld">
                        {#each withheld as s (s.scope)}
                            <li>{s.label}</li>
                        {/each}
                    </ul>
                {/if}

                <p class="hint">
                    Die Verbindung gilt nur für diese eine Organisation und lässt sich im
                    Adminbereich jederzeit trennen. Gelöscht werden kann über diese
                    Schnittstelle nichts.
                </p>
            {/if}

            {#if error}<p class="error">{error}</p>{/if}

            <div class="actions">
                <button class="secondary" onclick={() => decide(false)} disabled={working}>
                    Ablehnen
                </button>
                <button
                    class="primary"
                    onclick={() => decide(true)}
                    disabled={working || grantable.length === 0}
                >
                    {working ? 'Einen Moment …' : 'Zugriff erlauben'}
                </button>
            </div>
        {/if}
    </div>
    <LegalFooter />
</div>

<style>
    .wrap {
        min-height: 100vh;
        display: flex;
        flex-direction: column;
        align-items: center;
        justify-content: center;
        gap: 1rem;
        padding: 1.5rem;
    }
    .card {
        width: 100%;
        max-width: 34rem;
        background: var(--surface, #fff);
        border: 1px solid var(--border, #d8dde3);
        border-radius: 0.75rem;
        padding: 1.75rem;
        box-shadow: 0 1px 3px rgb(0 0 0 / 0.08);
    }
    h1 { font-size: 1.35rem; margin: 1rem 0 0.5rem; }
    .lead { margin: 0.75rem 0 0.25rem; }
    .muted { color: var(--text-muted, #667); }
    .hint { color: var(--text-muted, #667); font-size: 0.875rem; margin: 0.75rem 0; }
    .error { color: var(--danger, #b42318); margin: 0.75rem 0; }
    .client { margin: 1rem 0; display: grid; grid-template-columns: max-content 1fr; gap: 0.35rem 1rem; }
    .client dt { color: var(--text-muted, #667); font-size: 0.875rem; }
    .client dd { margin: 0; }
    .badge-warn, .badge-ok {
        font-size: 0.7rem;
        text-transform: uppercase;
        letter-spacing: 0.03em;
        padding: 0.1rem 0.4rem;
        border-radius: 0.25rem;
        margin-left: 0.4rem;
        white-space: nowrap;
    }
    .badge-warn { background: #fef0c7; color: #93370d; }
    .badge-ok { background: #d1fadf; color: #05603a; }
    .field { display: block; margin: 1rem 0; }
    .field > span { display: block; font-size: 0.875rem; margin-bottom: 0.25rem; }
    .field select { width: 100%; padding: 0.5rem; border: 1px solid var(--border, #d8dde3); border-radius: 0.375rem; }
    .scopes { margin: 0.25rem 0 0; padding-left: 1.25rem; }
    .scopes.withheld { color: var(--text-muted, #667); text-decoration: line-through; }
    .actions { display: flex; gap: 0.75rem; justify-content: flex-end; margin-top: 1.5rem; }
    .actions button { padding: 0.55rem 1.1rem; border-radius: 0.375rem; border: 1px solid transparent; cursor: pointer; }
    .actions button:disabled { opacity: 0.55; cursor: not-allowed; }
    .secondary { background: transparent; border-color: var(--border, #d8dde3); }
    .primary { background: var(--primary, #1f4e79); color: #fff; }
</style>
