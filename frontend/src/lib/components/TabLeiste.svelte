<script lang="ts">
    import type { Snippet } from 'svelte';

    /**
     * Reiterleiste, die seitlich scrollt, statt umzubrechen — und das auch
     * zeigt. Vorher war die Scrollleiste ausgeblendet, und am Telefon endete
     * die Leiste scheinbar bei „Pläne"; dass rechts noch acht Reiter liegen,
     * sah man nicht. Jetzt verläuft der Rand, auf der Seite mit verdeckten
     * Reitern steht ein Pfeil, und der aktive Reiter wird ins Bild gerollt.
     *
     * Die Reiter selbst (`.tab`) bringt die Seite mit, samt ihrer Stile.
     */
    let { children, aktiv }: { children: Snippet; aktiv?: unknown } = $props();

    let leiste: HTMLDivElement;
    let links = $state(false);
    let rechts = $state(false);

    function messen() {
        if (!leiste) return;
        // 1 px Spiel: gebrochene Pixel bei Zoom lassen scrollLeft nie ganz ans Ende kommen.
        links = leiste.scrollLeft > 1;
        rechts = leiste.scrollLeft + leiste.clientWidth < leiste.scrollWidth - 1;
    }

    function blaettern(richtung: 1 | -1) {
        leiste.scrollBy({ left: richtung * leiste.clientWidth * 0.7, behavior: 'smooth' });
    }

    $effect(() => {
        const beobachter = new ResizeObserver(messen);
        beobachter.observe(leiste);
        // Ein Reiter kann seine Breite ändern (Zähler bei „Meldungen").
        for (const kind of leiste.children) beobachter.observe(kind);
        messen();
        return () => beobachter.disconnect();
    });

    // Der aktive Reiter soll sichtbar sein — auch nach einem Wechsel per
    // Kontextmenü oder Verweis, nicht nur nach dem Tippen auf ihn.
    $effect(() => {
        void aktiv;
        const reiter = leiste?.querySelector<HTMLElement>('.active');
        if (!reiter) return;
        // .tab-bar ist offsetParent: offsetLeft zählt ab ihrem Inhaltsanfang, ungescrollt.
        const l = reiter.offsetLeft;
        const r = l + reiter.offsetWidth;
        if (l < leiste.scrollLeft || r > leiste.scrollLeft + leiste.clientWidth) {
            leiste.scrollTo({ left: l - (leiste.clientWidth - reiter.offsetWidth) / 2 });
        }
    });
</script>

<div class="tab-leiste" class:links class:rechts>
    <div class="tab-bar" bind:this={leiste} onscroll={messen}>
        {@render children()}
    </div>
    {#if links}
        <button type="button" class="pfeil pfeil-links" aria-label="Weitere Reiter links" tabindex="-1" onclick={() => blaettern(-1)}>‹</button>
    {/if}
    {#if rechts}
        <button type="button" class="pfeil pfeil-rechts" aria-label="Weitere Reiter rechts" tabindex="-1" onclick={() => blaettern(1)}>›</button>
    {/if}
</div>

<style>
    .tab-leiste {
        position: relative;
        margin-bottom: 1.5rem;
    }
    /* overflow-x statt Umbruch: Eine zweite Zeile würde die Unterkante
       zerreißen, an der die aktive Lasche hängt. */
    .tab-bar {
        position: relative;
        display: flex;
        gap: .25rem;
        /* Die Linie unten als Schatten im Scrollbereich und 1 px Platz dafür:
           Die Reiter rutschen mit margin-bottom: -1px auf die Linie, und als
           Rahmen außerhalb läge diese Lasche jenseits von overflow-y. */
        padding: .25rem .25rem 1px;
        box-shadow: inset 0 -1px 0 var(--border);
        overflow-x: auto;
        overflow-y: hidden;
        -webkit-overflow-scrolling: touch;
        scrollbar-width: none;
        scroll-behavior: smooth;
        /* Verdeckte Reiter laufen aus, statt hart abgeschnitten zu sein. */
        --fade-l: 0px;
        --fade-r: 0px;
        mask-image: linear-gradient(to right, transparent 0, #000 var(--fade-l), #000 calc(100% - var(--fade-r)), transparent 100%);
        -webkit-mask-image: linear-gradient(to right, transparent 0, #000 var(--fade-l), #000 calc(100% - var(--fade-r)), transparent 100%);
    }
    .tab-bar::-webkit-scrollbar { display: none; }
    .links .tab-bar { --fade-l: 2.5rem; }
    .rechts .tab-bar { --fade-r: 2.5rem; }

    .pfeil {
        position: absolute;
        top: 0;
        bottom: 1px;
        width: 2rem;
        display: flex;
        align-items: center;
        justify-content: center;
        padding: 0 0 .1rem;
        border: none;
        background: none;
        color: var(--color-primary);
        font-size: 1.5rem;
        line-height: 1;
        font-weight: 600;
        cursor: pointer;
    }
    .pfeil-links { left: 0; }
    .pfeil-rechts { right: 0; }
    .pfeil:hover { color: var(--text-1); }

    @media (max-width: 768px) {
        /* Randlos bis an den Bildschirmrand — die Seite hat .75rem Innenabstand. */
        .tab-leiste { margin: 0 -.75rem 1rem; }
        .tab-bar { padding: .25rem .75rem 1px; }
    }
</style>
