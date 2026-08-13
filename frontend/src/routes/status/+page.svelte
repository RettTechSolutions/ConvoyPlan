<script lang="ts">
    /**
     * Öffentliche Statusseite (/status).
     *
     * Bewusst ohne Anmeldung und ohne Betriebsinterna: die Seite beantwortet
     * nur, welche Funktion gerade nutzbar ist. Latenzen, Anbieternamen,
     * Container- und Versionsangaben bleiben der Admin-Systemübersicht
     * vorbehalten — hier steht, was ein Anwender wissen muss, bevor er einen
     * Konvoi plant.
     */
    import { onDestroy, onMount } from 'svelte';
    import { statusApi, type PublicComponentState, type PublicStatusResponse } from '$lib/api';
    import AppLogo from '$lib/components/AppLogo.svelte';
    import LegalFooter from '$lib/components/LegalFooter.svelte';
    import { themeStore } from '$lib/stores/theme';

    const REFRESH_MS = 30_000;

    let status = $state<PublicStatusResponse | null>(null);
    let unreachable = $state(false);
    let loading = $state(true);
    // Zählt jede abgeschlossene Abfrage — startet die Fortschrittsleiste neu.
    let cycle = $state(0);
    // Tickt sekündlich, damit „vor x Sekunden" mitläuft, ohne neu abzufragen.
    let now = $state(Date.now());

    let refreshTimer: ReturnType<typeof setInterval>;
    let clockTimer: ReturnType<typeof setInterval>;

    async function load() {
        try {
            status = await statusApi.getPublic();
            unreachable = false;
        } catch {
            // Antwortet das Backend nicht, ist das selbst die Aussage: nicht
            // erreichbar. Die zuletzt bekannten Funktionen bleiben stehen,
            // werden aber als veraltet gekennzeichnet.
            unreachable = true;
        } finally {
            loading = false;
            cycle += 1;
            now = Date.now();
        }
    }

    onMount(() => {
        load();
        refreshTimer = setInterval(load, REFRESH_MS);
        clockTimer = setInterval(() => (now = Date.now()), 1_000);
    });

    onDestroy(() => {
        clearInterval(refreshTimer);
        clearInterval(clockTimer);
    });

    const overall = $derived<PublicComponentState>(
        unreachable ? 'down' : (status?.overall ?? 'unknown')
    );

    const OVERALL_TEXT: Record<PublicComponentState, { title: string; sub: string }> = {
        operational: {
            title: 'Alle Systeme betriebsbereit',
            sub: 'Planung, Tracking und die angebundenen Kartendienste arbeiten normal.',
        },
        degraded: {
            title: 'Eingeschränkter Betrieb',
            sub: 'Einzelne Funktionen sind derzeit beeinträchtigt. Der Rest läuft weiter.',
        },
        down: {
            title: 'Störung',
            sub: 'Wesentliche Funktionen stehen momentan nicht zur Verfügung.',
        },
        unknown: {
            title: 'Status wird geprüft',
            sub: 'Die Dienste werden gerade abgefragt.',
        },
    };

    const headline = $derived.by(() => {
        if (!unreachable) return OVERALL_TEXT[overall];
        return {
            title: 'Portal nicht erreichbar',
            // Ohne zwischengespeicherte Antwort gibt es unten nichts zu sehen —
            // dann darf der Text auch nicht darauf verweisen.
            sub: (status?.components.length ?? 0) > 0
                ? 'Der Server antwortet derzeit nicht. Unten steht der zuletzt bekannte Stand.'
                : 'Der Server antwortet derzeit nicht. Die Seite versucht es automatisch erneut.',
        };
    });

    const STATE_LABEL: Record<PublicComponentState, string> = {
        operational: 'Betriebsbereit',
        degraded: 'Eingeschränkt',
        down: 'Nicht verfügbar',
        unknown: 'Wird geprüft',
    };

    /** Kurzer Klartext je Funktion — was die Einschränkung praktisch bedeutet. */
    const STATE_HINT: Record<PublicComponentState, string> = {
        operational: 'Uneingeschränkt nutzbar.',
        degraded: 'Nutzbar, aber langsamer oder unvollständig.',
        down: 'Diese Funktion ist gerade nicht nutzbar.',
        unknown: 'Wird gerade geprüft.',
    };

    // Ein Symbol je Funktion — Pfaddaten für ein 24×24-Raster.
    const ICONS: Record<string, string> = {
        portal: 'M12 3 3 8v8l9 5 9-5V8l-9-5Zm0 2.3 6.6 3.7L12 12.7 5.4 9 12 5.3ZM5 10.7l6 3.4v5.2l-6-3.3v-5.3Zm8 8.6v-5.2l6-3.4v5.3l-6 3.3Z',
        data: 'M12 3c-4 0-7 1.3-7 3v12c0 1.7 3 3 7 3s7-1.3 7-3V6c0-1.7-3-3-7-3Zm0 2c3.4 0 5 1 5 1s-1.6 1-5 1-5-1-5-1 1.6-1 5-1Zm5 13s-1.6 1-5 1-5-1-5-1v-2.3c1.3.7 3.1 1.1 5 1.1s3.7-.4 5-1.1V18Zm0-5s-1.6 1-5 1-5-1-5-1v-2.3c1.3.7 3.1 1.1 5 1.1s3.7-.4 5-1.1V13Z',
        planning: 'M9 3 3 5.4v15.1l6-2.4 6 2.4 6-2.4V2.9l-6 2.4L9 3Zm0 2.2 4 1.6v11.3l-4-1.6V5.2ZM5 6.8l2-.8v11.3l-2 .8V6.8Zm14 10.4-2 .8V6.7l2-.8v11.3Z',
        tracking: 'M12 2a7 7 0 0 0-7 7c0 5 7 13 7 13s7-8 7-13a7 7 0 0 0-7-7Zm0 9.5A2.5 2.5 0 1 1 12 6.5a2.5 2.5 0 0 1 0 5Z',
        traffic: 'M12 2 1.5 20.5h21L12 2Zm0 4.6 6.6 11.6H5.4L12 6.6ZM11 10v4.2h2V10h-2Zm0 5.5v2h2v-2h-2Z',
        weather: 'M17.5 19H7a5 5 0 0 1-.6-9.96A6 6 0 0 1 17.9 10.1 4.5 4.5 0 0 1 17.5 19Zm-10.5-2h10.5a2.5 2.5 0 0 0 0-5h-.9l-.2-.9A4 4 0 0 0 8.3 11l-.2 1-1 .05A3 3 0 0 0 7 17Z',
    };
    const FALLBACK_ICON = 'M12 2a10 10 0 1 0 0 20 10 10 0 0 0 0-20Zm0 2a8 8 0 1 1 0 16 8 8 0 0 1 0-16Zm-1 4v6h2V8h-2Zm0 8v2h2v-2h-2Z';

    function relTime(iso: string | null | undefined): string {
        if (!iso) return '';
        const diff = Math.max(0, Math.round((now - new Date(iso).getTime()) / 1000));
        if (diff < 10) return 'gerade eben';
        if (diff < 60) return `vor ${diff} Sekunden`;
        const min = Math.round(diff / 60);
        if (min < 60) return `vor ${min} Minute${min === 1 ? '' : 'n'}`;
        const h = Math.round(min / 60);
        return `vor ${h} Stunde${h === 1 ? '' : 'n'}`;
    }

    /* Zustandsfarben sind bewusst fest verdrahtet und nicht an das Branding
       gekoppelt: eine Organisation, die --color-primary auf Grün stellt, hätte
       sonst grün eingefärbte Störungsmeldungen. */
    const TINT: Record<PublicComponentState, string> = {
        operational: '#27ae60',
        degraded: '#f39c12',
        down: '#e74c3c',
        unknown: '#6b7177',
    };

    const components = $derived(status?.components ?? []);
    const affected = $derived(components.filter((c) => c.state === 'degraded' || c.state === 'down').length);
</script>

<svelte:head>
    <title>Systemstatus · ConvoyPlan</title>
    <meta name="description" content="Aktueller Betriebsstatus der ConvoyPlan-Dienste." />
</svelte:head>

<div class="page">
    <!-- Zwei langsam wandernde Farbschleier — dieselbe ruhige Anmutung wie die
         Kartenansicht im Portal, ohne von der Aussage abzulenken. -->
    <div class="aurora" aria-hidden="true">
        <span class="blob blob-a" style="--tint: {TINT[overall]}"></span>
        <span class="blob blob-b"></span>
    </div>

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
        <section class="hero {overall}" class:stale={unreachable}>
            <div class="ring-slot">
                <span class="ring" aria-hidden="true"></span>
                <span class="halo" aria-hidden="true"></span>
                <span class="core" aria-hidden="true"></span>
            </div>
            <div class="hero-text" role="status" aria-live="polite">
                <p class="eyebrow">Systemstatus</p>
                <h1>{loading ? 'Status wird geladen…' : headline.title}</h1>
                <p class="sub">{loading ? 'Einen Moment bitte.' : headline.sub}</p>
                {#if !loading && !unreachable && affected > 0}
                    <p class="affected">{affected} von {components.length} Funktionen betroffen</p>
                {/if}
            </div>
        </section>

        <div class="meta">
            <span class="meta-live" class:paused={unreachable}>
                <span class="live-dot" aria-hidden="true"></span>
                {#if status?.checked_at}
                    Zuletzt geprüft {relTime(status.checked_at)}
                {:else}
                    Prüfung läuft
                {/if}
            </span>
            <span class="meta-bar" aria-hidden="true">
                {#key cycle}
                    <span class="meta-bar-fill" style="--cycle: {REFRESH_MS}ms"></span>
                {/key}
            </span>
        </div>

        {#if loading}
            <div class="grid">
                {#each Array(6) as _, i}
                    <div class="card skeleton" style="--i: {i}"></div>
                {/each}
            </div>
        {:else if components.length === 0}
            <p class="empty">Derzeit liegen keine Statusdaten vor. Die Seite versucht es automatisch erneut.</p>
        {:else}
            <div class="grid">
                {#each components as c, i (c.key)}
                    <article class="card {c.state}" style="--i: {i}">
                        <div class="card-head">
                            <span class="ico" aria-hidden="true">
                                <svg viewBox="0 0 24 24"><path d={ICONS[c.key] ?? FALLBACK_ICON} /></svg>
                            </span>
                            <h2>{c.name}</h2>
                            <span class="dot" aria-hidden="true"></span>
                        </div>
                        <p class="desc">{c.description}</p>
                        <div class="card-foot">
                            <span class="badge">{STATE_LABEL[c.state]}</span>
                            <span class="hint">{STATE_HINT[c.state]}</span>
                        </div>
                    </article>
                {/each}
            </div>
        {/if}

        <p class="note">
            Diese Seite zeigt ausschließlich, ob die einzelnen Funktionen nutzbar sind —
            keine Einsatz-, Personen- oder Systemdaten.
        </p>

        <div class="actions">
            <a class="btn-primary" href="/">Zur Anmeldung →</a>
            <a class="btn-ghost" href="https://convoyplan.de" target="_blank" rel="noopener">convoyplan.de</a>
        </div>

        <LegalFooter showStatus={false} />
    </main>
</div>

<style>
    .page {
        position: relative;
        min-height: 100vh;
        min-height: 100dvh;
        background: var(--bg);
        color: var(--text-1);
        overflow: hidden;
        padding: env(safe-area-inset-top) env(safe-area-inset-right) env(safe-area-inset-bottom) env(safe-area-inset-left);
    }

    /* ── Hintergrund ─────────────────────────────────────────────────── */
    .aurora {
        position: absolute;
        inset: 0;
        overflow: hidden;
        pointer-events: none;
        z-index: 0;
    }
    .blob {
        position: absolute;
        width: 46rem;
        height: 46rem;
        border-radius: 50%;
        filter: blur(90px);
        opacity: .16;
    }
    .blob-a {
        top: -18rem;
        left: -12rem;
        background: radial-gradient(circle, var(--tint) 0%, transparent 68%);
        animation: drift-a 26s ease-in-out infinite;
    }
    .blob-b {
        bottom: -22rem;
        right: -14rem;
        background: radial-gradient(circle, var(--color-accent) 0%, transparent 68%);
        animation: drift-b 32s ease-in-out infinite;
    }
    @keyframes drift-a {
        0%, 100% { transform: translate3d(0, 0, 0) scale(1); }
        50%      { transform: translate3d(6rem, 4rem, 0) scale(1.12); }
    }
    @keyframes drift-b {
        0%, 100% { transform: translate3d(0, 0, 0) scale(1.08); }
        50%      { transform: translate3d(-5rem, -3rem, 0) scale(1); }
    }

    /* ── Kopfzeile ───────────────────────────────────────────────────── */
    .top {
        position: relative;
        z-index: 1;
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: 1rem;
        max-width: 1000px;
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
        line-height: 1;
        transition: color .15s, border-color .15s;
    }
    .theme-btn:hover { color: var(--text-1); border-color: var(--text-muted); }

    .wrap {
        position: relative;
        z-index: 1;
        max-width: 1000px;
        margin: 0 auto;
        padding: 2rem 1.25rem 3rem;
    }

    /* ── Gesamtaussage ───────────────────────────────────────────────── */
    .hero {
        --state: #6b7177;
        display: flex;
        align-items: center;
        gap: 1.75rem;
        background: var(--surface-1);
        border: 1px solid var(--border);
        border-radius: 16px;
        padding: 1.9rem 2rem;
        box-shadow: var(--shadow);
        animation: rise .5s cubic-bezier(.22, 1, .36, 1) both;
    }
    .hero.operational { --state: #27ae60; }
    .hero.degraded    { --state: #f39c12; }
    .hero.down        { --state: #e74c3c; }
    .hero.stale       { opacity: .92; }

    .ring-slot {
        position: relative;
        flex: 0 0 auto;
        width: 76px;
        height: 76px;
        display: grid;
        place-items: center;
    }
    /* Rotierender Bogen: signalisiert die laufende Überwachung, nicht den Zustand. */
    .ring {
        position: absolute;
        inset: 0;
        border-radius: 50%;
        background: conic-gradient(from 0deg, transparent 0 62%, var(--state) 88%, transparent 100%);
        -webkit-mask: radial-gradient(circle, transparent 0 58%, #000 59%);
        mask: radial-gradient(circle, transparent 0 58%, #000 59%);
        opacity: .85;
        animation: spin 4.5s linear infinite;
    }
    .halo {
        position: absolute;
        width: 46px;
        height: 46px;
        border-radius: 50%;
        background: var(--state);
        opacity: .28;
        animation: breathe 2.6s ease-in-out infinite;
    }
    .core {
        position: relative;
        width: 20px;
        height: 20px;
        border-radius: 50%;
        background: var(--state);
        box-shadow: 0 0 14px color-mix(in srgb, var(--state) 60%, transparent);
    }
    @keyframes spin { to { transform: rotate(360deg); } }
    @keyframes breathe {
        0%, 100% { transform: scale(.82); opacity: .3; }
        50%      { transform: scale(1.14); opacity: .12; }
    }

    .hero-text { min-width: 0; }
    .eyebrow {
        margin: 0 0 .3rem;
        font-size: var(--text-xs);
        text-transform: uppercase;
        letter-spacing: .1em;
        color: var(--text-muted);
    }
    .hero h1 {
        margin: 0;
        font-size: clamp(1.35rem, 3.4vw, 1.85rem);
        line-height: 1.2;
        color: var(--text-1);
    }
    .sub {
        margin: .45rem 0 0;
        font-size: var(--text-base);
        color: var(--text-2);
        max-width: 46ch;
    }
    .affected {
        margin: .6rem 0 0;
        display: inline-block;
        font-size: var(--text-xs);
        font-weight: 600;
        color: var(--state);
        background: color-mix(in srgb, var(--state) 14%, transparent);
        border-radius: 999px;
        padding: .18rem .6rem;
    }

    /* ── Prüfzeile ───────────────────────────────────────────────────── */
    .meta {
        display: flex;
        align-items: center;
        gap: .9rem;
        margin: .9rem .25rem 1.4rem;
        font-size: var(--text-xs);
        color: var(--text-muted);
    }
    .meta-live { display: inline-flex; align-items: center; gap: .45rem; white-space: nowrap; }
    .live-dot {
        width: 7px;
        height: 7px;
        border-radius: 50%;
        background: #27ae60;
        animation: blink 2s ease-in-out infinite;
    }
    .meta-live.paused .live-dot { background: #e74c3c; }
    @keyframes blink { 0%, 100% { opacity: 1; } 50% { opacity: .25; } }

    .meta-bar {
        flex: 1;
        height: 2px;
        border-radius: 2px;
        background: var(--border);
        overflow: hidden;
    }
    .meta-bar-fill {
        display: block;
        height: 100%;
        width: 100%;
        background: linear-gradient(90deg, transparent, var(--color-accent));
        transform-origin: left;
        animation: fill var(--cycle) linear forwards;
    }
    @keyframes fill { from { transform: scaleX(0); } to { transform: scaleX(1); } }

    /* ── Funktionskarten ─────────────────────────────────────────────── */
    .grid {
        display: grid;
        grid-template-columns: repeat(auto-fit, minmax(270px, 1fr));
        gap: .9rem;
    }
    .card {
        --state: #6b7177;
        position: relative;
        background: var(--surface-1);
        border: 1px solid var(--border);
        border-radius: 12px;
        padding: 1.05rem 1.15rem;
        box-shadow: var(--shadow);
        overflow: hidden;
        animation: rise .5s cubic-bezier(.22, 1, .36, 1) both;
        animation-delay: calc(var(--i) * 55ms + 80ms);
        transition: transform .18s ease, border-color .18s ease;
    }
    .card:hover { transform: translateY(-2px); border-color: color-mix(in srgb, var(--state) 45%, var(--border)); }
    /* Farbkante links: der Zustand ist auch beim Überfliegen ablesbar. */
    .card::before {
        content: '';
        position: absolute;
        inset: 0 auto 0 0;
        width: 3px;
        background: var(--state);
        opacity: .85;
    }
    .card.operational { --state: #27ae60; }
    .card.degraded    { --state: #f39c12; }
    .card.down        { --state: #e74c3c; }

    .card-head { display: flex; align-items: center; gap: .6rem; }
    .ico {
        display: grid;
        place-items: center;
        width: 30px;
        height: 30px;
        flex: 0 0 auto;
        border-radius: 8px;
        background: color-mix(in srgb, var(--state) 14%, transparent);
        color: var(--state);
    }
    .ico svg { width: 17px; height: 17px; fill: currentColor; }
    .card h2 {
        flex: 1;
        margin: 0;
        font-size: var(--text-base);
        font-weight: 600;
        color: var(--text-1);
    }
    .dot {
        width: 9px;
        height: 9px;
        flex: 0 0 auto;
        border-radius: 50%;
        background: var(--state);
    }
    /* Nur auffällige Zustände pulsieren — sonst flackert die ganze Seite. */
    .card.degraded .dot,
    .card.down .dot { animation: pulse-ring 1.8s ease-out infinite; }
    @keyframes pulse-ring {
        0%   { box-shadow: 0 0 0 0 color-mix(in srgb, var(--state) 60%, transparent); }
        70%  { box-shadow: 0 0 0 6px color-mix(in srgb, var(--state) 0%, transparent); }
        100% { box-shadow: 0 0 0 0 color-mix(in srgb, var(--state) 0%, transparent); }
    }

    .desc {
        margin: .55rem 0 .8rem;
        font-size: var(--text-sm);
        line-height: 1.45;
        color: var(--text-2);
    }
    .card-foot { display: flex; align-items: center; gap: .55rem; flex-wrap: wrap; }
    .badge {
        font-size: var(--text-xs);
        font-weight: 600;
        color: var(--state);
        background: color-mix(in srgb, var(--state) 13%, transparent);
        border-radius: 999px;
        padding: .2rem .6rem;
        white-space: nowrap;
    }
    .hint { font-size: var(--text-xs); color: var(--text-muted); }

    .card.skeleton {
        height: 132px;
        border-color: var(--border);
        background:
            linear-gradient(90deg, transparent 0%, color-mix(in srgb, var(--text-1) 6%, transparent) 50%, transparent 100%)
            var(--surface-1);
        background-size: 220% 100%;
        animation: rise .4s cubic-bezier(.22, 1, .36, 1) both, shimmer 1.4s linear infinite;
        animation-delay: calc(var(--i) * 55ms), 0s;
    }
    @keyframes shimmer { from { background-position: 120% 0; } to { background-position: -120% 0; } }

    @keyframes rise {
        from { opacity: 0; transform: translateY(10px); }
        to   { opacity: 1; transform: translateY(0); }
    }

    .empty {
        margin: 0;
        padding: 2rem 1rem;
        text-align: center;
        font-size: var(--text-sm);
        color: var(--text-2);
        background: var(--surface-1);
        border: 1px dashed var(--border);
        border-radius: 12px;
    }

    .note {
        margin: 1.6rem 0 0;
        text-align: center;
        font-size: var(--text-xs);
        color: var(--text-muted);
    }

    .actions {
        display: flex;
        justify-content: center;
        align-items: center;
        gap: .75rem;
        margin-top: 1.1rem;
        flex-wrap: wrap;
    }
    .btn-primary,
    .btn-ghost {
        text-decoration: none;
        font-size: var(--text-sm);
        font-weight: 600;
        border-radius: 8px;
        padding: .5rem 1.1rem;
        transition: background .15s, color .15s, border-color .15s;
    }
    .btn-primary {
        background: var(--color-primary);
        color: #fff;
    }
    .btn-primary:hover { background: var(--color-primary-hover); }
    .btn-ghost {
        border: 1px solid var(--border);
        color: var(--text-2);
    }
    .btn-ghost:hover { color: var(--text-1); border-color: var(--text-muted); }

    @media (max-width: 640px) {
        .wrap { padding: 1.5rem 1rem 2.5rem; }
        .hero {
            flex-direction: column;
            align-items: flex-start;
            gap: 1.1rem;
            padding: 1.5rem 1.25rem;
        }
        .grid { grid-template-columns: 1fr; }
    }

    /* Wer Bewegung reduziert haben will, bekommt dieselbe Seite ohne Animation —
       die Zustände sind über Farbe, Kante und Text vollständig ablesbar. */
    @media (prefers-reduced-motion: reduce) {
        .blob-a, .blob-b, .ring, .halo, .live-dot,
        .meta-bar-fill, .card, .card.skeleton, .hero,
        .card.degraded .dot, .card.down .dot {
            animation: none !important;
        }
        .card { opacity: 1; transform: none; }
        .meta-bar-fill { transform: scaleX(1); }
        .card:hover { transform: none; }
    }
</style>
