<script lang="ts">
    import { onMount } from 'svelte';
    import { goto } from '$app/navigation';
    import { page } from '$app/stores';
    import { sicheresZiel } from '$lib/redirect';
    import { orgAuthApi, authApi } from '$lib/api';
    import AppLogo from '$lib/components/AppLogo.svelte';
    import LegalFooter from '$lib/components/LegalFooter.svelte';
    import { PRODUCT, FEATURES } from '$lib/agent/facts';
    import { PAGES, pageFor } from '$lib/agent/pages';
    import { buildJsonLd } from '$lib/agent/jsonld';
    import { registerWebMcpTools } from '$lib/agent/webmcp';
    import type { PageData } from './$types';

    let { data }: { data: PageData } = $props();

    // Titel, Überschrift und og:title sind dasselbe — der Eintrag aus dem
    // Seitenkatalog, aus dem auch Sitemap und `/index.md` ihren Titel ziehen.
    const pageTitle = pageFor('/')?.title ?? PRODUCT.name;

    // Datenschutz und Systemstatus stehen schon im LegalFooter unter der
    // Anmeldekarte und würden hier ein zweites Mal auftauchen — seit #492
    // sogar mit demselben Ziel.
    const IM_LEGALFOOTER = ['/privacy', '/status'];
    const navPages = PAGES.filter((p) => p.path !== '/' && !IM_LEGALFOOTER.includes(p.path));

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
    <title>{pageTitle}</title>
    <meta name="description" content={PRODUCT.tagline} />
    <link rel="canonical" href={canonical} />
    {#if data.agentDiscovery}
        <link rel="alternate" type="text/markdown" href="{data.base}/index.md" title="Markdown-Fassung dieser Seite" />
        <link rel="alternate" type="text/plain" href="{data.base}/llms.txt" title="llms.txt" />
        <meta property="og:type" content="website" />
        <meta property="og:title" content={pageTitle} />
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

<!--
    Die Anmeldekarte gibt es in beiden Fassungen der Seite — als rechte Spalte
    der Startseite und, mit abgeschalteter Agenten-Auskunft, als einziges
    Element auf leerem Schirm. Ein Snippet statt zweier Kopien.
-->
{#snippet loginCard()}
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
{/snippet}

{#if data.agentDiscovery}
    <!--
        Die Startseite trägt zwei Aufgaben gleichzeitig: Einstieg für die
        eigenen Leute und einzige Seite, die eine Instanz unaufgefordert über
        sich selbst ausliefert. Der beschreibende Teil steht deshalb im
        serverseitig gerenderten HTML — ohne ihn besteht die Seite aus einem
        Logo und einem Eingabefeld, und ein Crawler sieht nichts.

        Er ist als Seite gebaut und nicht als Textblock unter der Karte:
        Anmeldung und Beschreibung stehen nebeneinander, der Rest sind
        Kacheln. Was drinsteht, kommt aus `lib/agent/facts.ts` — derselben
        Quelle, aus der `/index.md` und das JSON-LD entstehen.
    -->
    <main class="landing">
        <section class="hero">
            <div class="hero-login">
                {@render loginCard()}
            </div>

            <div class="hero-copy">
                <p class="eyebrow">Self-hosted · Docker Compose · {PRODUCT.license}</p>
                <h1>{pageTitle}</h1>
                <p class="lead">{PRODUCT.tagline}</p>
                <p>{PRODUCT.description}</p>
                {#if data.demoHint}
                    <p class="hero-demo">
                        Ohne Konto ansehen: „Demo ausprobieren" legt eine eigene temporäre Umgebung
                        mit Beispieldaten an, ohne Berührung mit Produktivdaten.
                    </p>
                {/if}
            </div>
        </section>

        <section class="features" aria-labelledby="features-title">
            <h2 id="features-title">Was ConvoyPlan kann</h2>
            <ul class="feature-grid">
                {#each FEATURES as feature (feature.id)}
                    <li class="feature">
                        <h3>{feature.title}</h3>
                        <p>{feature.summary}</p>
                    </li>
                {/each}
            </ul>
        </section>

        <footer class="landing-foot">
            <nav class="foot-nav" aria-label="Weitere Informationen">
                {#each navPages as entry (entry.path)}
                    <a href={entry.path}>{entry.title}</a>
                {/each}
            </nav>
            <p class="agent-hint">
                Für KI-Agenten und Programme: <a href="/llms.txt">llms.txt</a> ·
                <a href="/agents.md">agents.md</a> · <a href="/auth.md">auth.md</a> ·
                <a href="/openapi.json">openapi.json</a>
            </p>
        </footer>
    </main>
{:else}
    <div class="login-container">
        {@render loginCard()}
    </div>
{/if}

<style>
    /* ── Anmeldekarte ──────────────────────────────────────────────────── */
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

    /* ── Startseite ────────────────────────────────────────────────────── */
    .landing {
        --landing-width: 68rem;
        min-height: 100vh;
        min-height: 100dvh;
        background: var(--bg);
        color: var(--text-1);
        padding: env(safe-area-inset-top) env(safe-area-inset-right) env(safe-area-inset-bottom) env(safe-area-inset-left);
    }
    .hero, .features, .landing-foot {
        max-width: var(--landing-width);
        margin: 0 auto;
        padding-left: 1rem;
        padding-right: 1rem;
    }
    .hero {
        display: grid;
        gap: clamp(2rem, 5vw, 3.5rem);
        align-items: center;
        padding-top: clamp(1.5rem, 5vh, 3.5rem);
        padding-bottom: clamp(2.5rem, 7vh, 4.5rem);
    }
    /* Auf schmalem Schirm zuerst die Karte: wer hier landet, will sich in aller
       Regel anmelden, nicht lesen. Auf breitem Schirm steht beides
       nebeneinander, die Karte rechts. */
    .hero-login { display: flex; justify-content: center; }
    .hero-copy { max-width: 42rem; }
    .eyebrow {
        margin: 0 0 .6rem;
        font-size: var(--text-xs);
        font-weight: 600;
        letter-spacing: .08em;
        text-transform: uppercase;
        color: var(--text-muted);
    }
    .hero-copy h1 {
        margin: 0 0 .6rem;
        font-size: clamp(1.6rem, 1.1rem + 2vw, 2.4rem);
        line-height: 1.15;
        letter-spacing: -.01em;
    }
    .hero-copy .lead {
        margin: 0 0 1rem;
        font-size: clamp(1.02rem, .95rem + .5vw, 1.2rem);
        line-height: 1.45;
        color: var(--text-1);
    }
    .hero-copy p {
        margin: 0 0 1rem;
        line-height: 1.65;
        font-size: var(--text-base);
        color: var(--text-2);
    }
    .hero-demo {
        border-left: 2px solid var(--color-primary);
        padding-left: .75rem;
    }

    .features {
        border-top: 1px solid var(--border);
        padding-top: clamp(2rem, 5vh, 3rem);
        padding-bottom: clamp(2rem, 5vh, 3rem);
    }
    .features h2 {
        margin: 0 0 1.25rem;
        font-size: var(--text-lg);
        letter-spacing: -.01em;
    }
    .feature-grid {
        list-style: none;
        margin: 0;
        padding: 0;
        display: grid;
        gap: 1rem;
        grid-template-columns: repeat(auto-fit, minmax(15rem, 1fr));
    }
    .feature {
        background: var(--surface-1);
        border: 1px solid var(--border);
        border-radius: 10px;
        padding: 1.1rem 1.15rem;
        box-shadow: var(--shadow);
    }
    /* Der Strich ersetzt das Icon, das es für diese Kacheln nicht gibt — er
       gibt dem Raster eine Kante, ohne eine Bilddatei zu erfinden. */
    .feature::before {
        content: '';
        display: block;
        width: 1.75rem;
        height: 2px;
        border-radius: 2px;
        background: var(--color-primary);
        margin-bottom: .75rem;
    }
    .feature h3 {
        margin: 0 0 .35rem;
        font-size: var(--text-base);
        font-weight: 600;
        line-height: 1.3;
    }
    .feature p {
        margin: 0;
        font-size: var(--text-sm);
        line-height: 1.55;
        color: var(--text-2);
    }

    .landing-foot {
        border-top: 1px solid var(--border);
        padding-top: 1.5rem;
        padding-bottom: 3rem;
    }
    .foot-nav {
        display: flex;
        flex-wrap: wrap;
        gap: .4rem 1.25rem;
        margin-bottom: .75rem;
        font-size: var(--text-sm);
    }
    .foot-nav a, .agent-hint a { color: var(--color-primary); text-decoration: none; }
    .foot-nav a:hover, .agent-hint a:hover { text-decoration: underline; }
    .agent-hint {
        margin: 0;
        font-size: var(--text-sm);
        color: var(--text-muted);
    }

    @media (min-width: 900px) {
        .hero {
            grid-template-columns: minmax(0, 1fr) 24rem;
            min-height: min(80vh, 44rem);
        }
        .hero-copy { grid-column: 1; grid-row: 1; }
        .hero-login { grid-column: 2; grid-row: 1; justify-content: flex-end; }
    }
</style>
