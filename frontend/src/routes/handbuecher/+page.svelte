<script lang="ts">
    /**
     * Die Handbücher dieser Instanz (/handbuecher).
     *
     * Öffentlich wie /status: Wer ein Handbuch sucht, hat oft noch keinen
     * Zugang — der Betreiber vor der Installation, die Besatzung vor dem
     * ersten Scan. Die PDFs liegen in `static/handbuecher/` und kommen von
     * dieser Instanz, nicht von GitHub: Eine Instanz ohne Internet hat ihr
     * Handbuch trotzdem.
     */
    import AppLogo from '$lib/components/AppLogo.svelte';
    import LegalFooter from '$lib/components/LegalFooter.svelte';
    import { themeStore } from '$lib/stores/theme';
    import { HANDBUECHER, groesse, handbuchUrl, stand } from '$lib/handbuecher';

    const SYMBOL: Record<string, string> = {
        'ConvoyPlan-Anwenderhandbuch.pdf': '🗺',
        'ConvoyPlan-Betriebshandbuch.pdf': '🛠',
        'ConvoyPlan-Begleit-App.pdf': '📱',
    };
</script>

<svelte:head>
    <title>Handbücher · ConvoyPlan</title>
    <meta name="description" content="Handbücher zu ConvoyPlan als PDF: Anwendung, Betrieb und Begleit-App." />
</svelte:head>

<div class="page">
    <header class="top">
        <a class="brand" href="/" aria-label="Zur Anmeldung">
            <AppLogo variant="horizontal" height={34} />
        </a>
        <button
            class="theme-btn"
            onclick={() => themeStore.toggle()}
            title={$themeStore === 'dark' ? 'Helle Ansicht' : 'Dunkle Ansicht'}
            aria-label="Ansicht umschalten"
        >{$themeStore === 'dark' ? '☀' : '☾'}</button>
    </header>

    <main class="wrap">
        <p class="eyebrow">Hilfe</p>
        <h1>Handbücher</h1>
        <p class="sub">
            Zum Lesen am Bildschirm, zum Ausdrucken und zum Mitnehmen ins Fahrzeug.
            Die Kapitel entsprechen dem
            <a href="https://github.com/RettTechSolutions/ConvoyPlan/wiki" target="_blank" rel="noopener">Wiki</a>,
            die Bildschirmfotos stammen aus einer Demo-Organisation.
        </p>

        <ul class="liste">
            {#each HANDBUECHER as h (h.datei)}
                <li class="karte">
                    <span class="symbol" aria-hidden="true">{SYMBOL[h.datei] ?? '📖'}</span>
                    <div class="text">
                        <h2>{h.titel}</h2>
                        <p class="fuer">Für {h.fuer}</p>
                        <p class="beschreibung">{h.beschreibung}</p>
                        <p class="meta">PDF · {h.seiten} Seiten · {groesse(h.bytes)} · Stand {stand(h)}</p>
                    </div>
                    <a class="oeffnen" href={handbuchUrl(h)} target="_blank" rel="noopener">PDF öffnen</a>
                </li>
            {/each}
        </ul>

        <LegalFooter />
    </main>
</div>

<style>
    .page {
        min-height: 100vh;
        min-height: 100dvh;
        background: var(--bg);
        color: var(--text-1);
        padding: env(safe-area-inset-top) env(safe-area-inset-right) env(safe-area-inset-bottom) env(safe-area-inset-left);
    }
    .top {
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: 1rem;
        max-width: 860px;
        margin: 0 auto;
        padding: 1.25rem 1.25rem 0;
    }
    .brand { display: block; }
    .theme-btn {
        background: var(--surface-1);
        border: 1px solid var(--border);
        color: var(--text-2);
        border-radius: 999px;
        width: 2.1rem;
        height: 2.1rem;
        font-size: .95rem;
        cursor: pointer;
    }
    .theme-btn:hover { color: var(--text-1); border-color: var(--text-muted); }
    .wrap {
        max-width: 860px;
        margin: 0 auto;
        padding: 2rem 1.25rem 3rem;
    }
    .eyebrow {
        margin: 0;
        font-size: var(--text-xs);
        letter-spacing: .08em;
        text-transform: uppercase;
        color: var(--color-primary);
        font-weight: 700;
    }
    h1 { margin: .25rem 0 .5rem; font-size: 1.9rem; }
    .sub { margin: 0 0 1.75rem; color: var(--text-2); max-width: 60ch; line-height: 1.5; }
    .sub a { color: inherit; }
    .liste { list-style: none; margin: 0; padding: 0; display: grid; gap: .9rem; }
    .karte {
        display: grid;
        grid-template-columns: auto 1fr auto;
        align-items: center;
        gap: 1rem;
        background: var(--surface-1);
        border: 1px solid var(--border);
        border-radius: 12px;
        padding: 1rem 1.15rem;
    }
    /* Feste Breite: Emojis sind unterschiedlich breit, und der Text daneben soll
       in allen Karten an derselben Kante beginnen. */
    .symbol { font-size: 1.8rem; line-height: 1; width: 2.4rem; text-align: center; }
    .text { min-width: 0; }
    h2 { margin: 0; font-size: var(--text-base, 1rem); }
    .fuer { margin: .15rem 0 0; font-size: var(--text-sm); color: var(--color-primary); font-weight: 600; }
    .beschreibung { margin: .35rem 0 0; font-size: var(--text-sm); color: var(--text-2); line-height: 1.45; }
    .meta { margin: .35rem 0 0; font-size: var(--text-xs); color: var(--text-muted); }
    .oeffnen {
        background: var(--color-primary);
        color: #fff;
        border-radius: 8px;
        padding: .5rem .9rem;
        font-size: var(--text-sm);
        font-weight: 600;
        text-decoration: none;
        white-space: nowrap;
    }
    .oeffnen:hover { filter: brightness(1.08); }
    /* Am Telefon steht der Knopf unter dem Text über die volle Breite — neben
       ihm bliebe für die Beschreibung eine Spalte von drei Wörtern. */
    @media (max-width: 560px) {
        .karte { grid-template-columns: auto 1fr; }
        .oeffnen { grid-column: 1 / -1; text-align: center; }
    }
</style>
