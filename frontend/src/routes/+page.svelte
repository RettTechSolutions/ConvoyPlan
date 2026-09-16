<script lang="ts">
    import { onMount } from 'svelte';
    import { goto } from '$app/navigation';
    import { page } from '$app/stores';
    import { sicheresZiel } from '$lib/redirect';
    import { orgAuthApi, authApi } from '$lib/api';
    import AppLogo from '$lib/components/AppLogo.svelte';
    import LegalFooter from '$lib/components/LegalFooter.svelte';
    import { PRODUCT } from '$lib/agent/facts';
    import { buildJsonLd } from '$lib/agent/jsonld';
    import { registerWebMcpTools } from '$lib/agent/webmcp';
    import type { PageData } from './$types';

    let { data }: { data: PageData } = $props();

    // $derived, nicht const: `data` ist reaktiv, und eine Navigation auf
    // dieselbe Route soll Canonical und JSON-LD mitziehen.
    const canonical = $derived(`${data.base}/`);
    const jsonLd = $derived(data.agentDiscovery ? buildJsonLd(data.base) : '');

    let slugInput = $state('');
    let error = $state('');
    let loading = $state(false);
    let demoAvailable = $state(false);
    let demoHours = $state(24);

    onMount(async () => {
        // Werkzeuge für Browser-Agenten anmelden (WebMCP). Tut nichts, wenn der
        // Browser das Modell nicht kennt — heute also fast überall.
        if (data.agentDiscovery) registerWebMcpTools();

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
            // Ein Ziel, das uns hierher geschickt hat, überlebt den Umweg
            // über die Organisationsanmeldung.
            const ziel = sicheresZiel($page.url.searchParams.get('redirect'));
            goto(
                ziel
                    ? `/o/${slug}/login?redirect=${encodeURIComponent(ziel)}`
                    : `/o/${slug}/login`
            );
        } catch {
            error = 'Organisation nicht gefunden. Bitte Code prüfen.';
        } finally {
            loading = false;
        }
    }
</script>

<svelte:head>
    <title>ConvoyPlan — Marschplanung für Einsatzorganisationen</title>
    <meta name="description" content="ConvoyPlan plant Marschverbände und Konvois von Einsatzorganisationen: kartenbasierte Routenplanung, Zeitplan mit technischen Halten, Live-Tracking und Marschbefehl-Export. Self-hosted." />
    <link rel="canonical" href={canonical} />
    {#if data.agentDiscovery}
        <link rel="alternate" type="text/markdown" href="{data.base}/index.md" title="Markdown-Fassung dieser Seite" />
        <link rel="alternate" type="text/plain" href="{data.base}/llms.txt" title="llms.txt" />
        <meta property="og:type" content="website" />
        <meta property="og:title" content="ConvoyPlan — Marschplanung für Einsatzorganisationen" />
        <meta property="og:description" content={PRODUCT.tagline} />
        <meta property="og:url" content={canonical} />
        <meta property="og:site_name" content="ConvoyPlan" />
        <meta property="og:locale" content="de_DE" />
        <meta property="og:image" content="{data.base}/logo/light/LogoHorinzontal.png" />
        <meta property="og:image:alt" content="ConvoyPlan Logo" />
        <meta name="twitter:card" content="summary_large_image" />
        <!--
            JSON-LD als ein @graph: Organisation, Website, Software, Service,
            API, FAQ und Breadcrumb verweisen über @id aufeinander, damit ein
            Parser eine Entität sieht statt sieben gleichnamiger.
            eslint-disable-next-line svelte/no-at-html-tags
        -->
        {@html `<script type="application/ld+json">${jsonLd}<\/script>`}
    {/if}
</svelte:head>

<div class="login-container" class:standalone={!data.agentDiscovery}>
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

            <!-- Der Start hängt seit der Kontakterfassung an einem kurzen
                 Formular; die Absagegründe (Karenzzeit, Demo abgeschaltet)
                 zeigt damit /demo an, nicht mehr diese Seite. -->
            <button class="demo-btn" onclick={() => goto('/demo')}>
                ▶ Demo ausprobieren
            </button>
            <p class="demo-hint">Eigene temporäre Umgebung · Ohne Konto · {demoHours} Stunden</p>
        {/if}

        <LegalFooter />
    </div>
</div>

{#if data.agentDiscovery}
    <!--
        Der beschreibende Teil der Startseite. Er steht bewusst im
        serverseitig gerenderten HTML: davor bestand diese Seite aus einem
        Logo und einem Eingabefeld, und wer sie ohne JavaScript oder als
        Crawler abrief, sah praktisch nichts. Das H1 ist zugleich die
        Überschrift, die der Seite bis dahin fehlte.
    -->
    <section class="intro" aria-labelledby="intro-title">
        <h1 id="intro-title">ConvoyPlan — Marschplanung für Einsatzorganisationen</h1>
        <p class="lead">{PRODUCT.tagline}</p>
        <p>
            ConvoyPlan ist eine selbst gehostete Web-Anwendung für die strukturierte Planung und
            Durchführung von Marschverbänden und Konvoifahrten. Die Routen berechnet ein
            mitgelieferter GraphHopper-Dienst auf Basis von OpenStreetMap; Wegpunkte,
            Kontrollpunkte und technische Halte bekommen dabei automatisch einen Zeitplan, an dem
            sich alle Besatzungen ausrichten können. Während der Fahrt zeigt das Live-Tracking per
            WebSocket, wo die Fahrzeuge stehen und welchen Marschstatus sie gemeldet haben. Am
            Ende steht der fertige Marschbefehl als PDF, GPX oder JSON.
        </p>
        <p>
            Die Anwendung läuft vollständig on-premise über Docker Compose und setzt keinen
            Cloud-Dienst voraus. Mehrere Organisationen teilen sich eine Instanz, ohne die Daten
            der jeweils anderen zu sehen: Zugang gibt es über den Organisations-Code oben.
            {#if data.demoHint}
                Wer ConvoyPlan zuerst ansehen will, startet über „Demo ausprobieren" eine eigene
                temporäre Umgebung mit Beispieldaten — ohne Konto und ohne Berührung mit
                Produktivdaten.
            {/if}
        </p>
        <nav class="intro-nav" aria-label="Weitere Informationen">
            <a href="/about">Über ConvoyPlan</a>
            <a href="/pricing">Preise und Lizenzen</a>
            <a href="/developers">Entwickler und API</a>
            <a href="/docs">Dokumentation</a>
            <a href="/contact">Kontakt</a>
            <a href="/privacy">Datenschutz</a>
            <a href="/status">Systemstatus</a>
        </nav>
        <p class="agent-hint">
            Für KI-Agenten und Programme: <a href="/llms.txt">llms.txt</a> ·
            <a href="/agents.md">agents.md</a> · <a href="/auth.md">auth.md</a> ·
            <a href="/openapi.json">openapi.json</a>
        </p>
    </section>
{/if}

<style>
    .login-container {
        display: flex;
        align-items: center;
        justify-content: center;
        /* 100dvh statt 100vh: auf iOS entspricht 100vh der Höhe bei eingeklappter
           Toolbar — die Karte würde sonst außermittig sitzen. Safe-Area-Insets als
           Padding, damit der Hintergrund bis unter Statusleiste/Toolbar reicht. */
        /* Ohne den Beschreibungsteil darunter füllt die Karte weiterhin den
           Schirm; mit ihm wäre sie sonst die einzige sichtbare Seite und der
           Text stünde unter der Falz. */
        min-height: 70vh;
        min-height: 70dvh;
        padding: env(safe-area-inset-top) env(safe-area-inset-right) env(safe-area-inset-bottom) env(safe-area-inset-left);
        background: var(--bg);
    }
    .login-container.standalone {
        min-height: 100vh;
        min-height: 100dvh;
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
    .intro {
        max-width: 48rem;
        margin: 0 auto;
        padding: 0 1rem 4rem;
        color: var(--text-1);
        line-height: 1.6;
        font-size: var(--text-base);
    }
    .intro h1 {
        font-size: 1.5rem;
        margin: 0 0 .5rem;
    }
    .intro .lead {
        font-size: var(--text-lg);
        color: var(--text-2);
        margin: 0 0 1rem;
    }
    .intro p { margin: 0 0 1rem; }
    .intro-nav {
        display: flex;
        flex-wrap: wrap;
        gap: .4rem 1rem;
        margin-bottom: 1rem;
        font-size: var(--text-sm);
    }
    .intro-nav a, .agent-hint a { color: var(--color-primary); text-decoration: none; }
    .intro-nav a:hover, .agent-hint a:hover { text-decoration: underline; }
    .agent-hint {
        font-size: var(--text-sm);
        color: var(--text-muted);
    }
</style>
