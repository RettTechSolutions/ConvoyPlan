<script lang="ts">
	/**
	 * Hängt die eingeschaltete Saison an die Seite: `data-saison` auf `<html>`
	 * (Farben und Deko in `saisons.css`), ein Band am oberen Rand, die
	 * Partikel und den Gruß beim Einschalten. Eingehängt einmal im
	 * Wurzel-Layout; wo die Saison sich zeigen darf, sagt `erlaubt()`.
	 *
	 * Zweiter Auslöser neben dem Knopf: der Konami-Code.
	 */
	import { onMount } from 'svelte';
	import { page } from '$app/state';
	import { erlaubt, saisonStore } from './store';
	import './saisons.css';

	const sichtbar = $derived(
		$saisonStore.aktiv && $saisonStore.saison !== null && erlaubt(page.url.pathname),
	);
	const saison = $derived(sichtbar ? $saisonStore.saison : null);

	let ruhig = $state(false);
	onMount(() => {
		const anfrage = window.matchMedia('(prefers-reduced-motion: reduce)');
		ruhig = anfrage.matches;
		const wechsel = (e: MediaQueryListEvent) => (ruhig = e.matches);
		anfrage.addEventListener('change', wechsel);
		return () => anfrage.removeEventListener('change', wechsel);
	});

	$effect(() => {
		const html = document.documentElement;
		if (saison) html.dataset.saison = saison.id;
		else delete html.dataset.saison;
	});

	// Gruß: nur nach einem Einschalten, nicht bei jedem Laden einer Seite.
	let gruss = $state<string | null>(null);
	let gegruesst = 0;
	$effect(() => {
		const wann = $saisonStore.eingeschaltet;
		const zeilen = saison?.gruss ?? [];
		if (!wann || wann === gegruesst || !zeilen.length) return;
		gegruesst = wann;
		let i = 0;
		gruss = zeilen[0];
		const takt = setInterval(() => {
			i += 1;
			gruss = i < zeilen.length ? zeilen[i] : null;
			if (i >= zeilen.length) clearInterval(takt);
		}, 3500);
		return () => {
			clearInterval(takt);
			gruss = null;
		};
	});

	const KONAMI = ['ArrowUp', 'ArrowUp', 'ArrowDown', 'ArrowDown', 'ArrowLeft', 'ArrowRight', 'ArrowLeft', 'ArrowRight', 'b', 'a'];
	let stand = 0;
	function taste(e: KeyboardEvent) {
		const ziel = e.target as HTMLElement | null;
		if (ziel?.closest('input, textarea, select, [contenteditable="true"]')) return;
		const erwartet = KONAMI[stand];
		// Ein drittes „hoch" fängt nicht von vorn an: es sind dann wieder zwei.
		if (e.key.toLowerCase() === erwartet.toLowerCase()) stand += 1;
		else stand = e.key === 'ArrowUp' ? (stand === 2 ? 2 : 1) : 0;
		if (stand === KONAMI.length) {
			stand = 0;
			if ($saisonStore.saison && erlaubt(page.url.pathname)) saisonStore.umschalten();
		}
	}
</script>

<svelte:window onkeydown={taste} />

{#if saison}
	<div class="saison-band" aria-hidden="true"></div>
	{#if saison.id === 'halloween'}
		<div class="saison-spinne" aria-hidden="true"><span>🕷️</span></div>
	{/if}
	{#if saison.id === 'ostern' && !ruhig}
		<div class="saison-hase" aria-hidden="true">🐇</div>
	{/if}
	{#if saison.partikel && !ruhig}
		{#await import('./Partikel.svelte') then { default: Partikel }}
			<Partikel art={saison.partikel} />
		{/await}
	{/if}
{/if}

{#if gruss}
	<div class="saison-gruss" role="status">{gruss}</div>
{/if}

<style>
	.saison-gruss {
		position: fixed;
		left: 50%;
		bottom: calc(2rem + env(safe-area-inset-bottom, 0px));
		transform: translateX(-50%);
		max-width: min(32rem, calc(100vw - 2rem));
		padding: .6rem 1rem;
		border-radius: 10px;
		background: var(--surface-2);
		color: var(--text-1);
		border: 1px solid var(--border);
		box-shadow: 0 6px 24px rgba(0, 0, 0, .25);
		font-size: var(--text-sm);
		text-align: center;
		z-index: 2001;
		pointer-events: none;
	}
</style>
