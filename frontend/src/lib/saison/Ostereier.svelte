<script lang="ts">
	/**
	 * Legt die Ostereier an ihre Anker (`ostereier.ts`). Die Eier liegen fest
	 * über der Seite (`position: fixed`) und folgen ihrem Anker, solange er zu
	 * sehen ist; scrollt er aus seinem Bereich oder steht er in einem
	 * geschlossenen Reiter, ist auch das Ei weg.
	 */
	import { onMount } from 'svelte';
	import { anzahl, eierStore, GOLDENES_EI, lage, VERSTECKE, type Versteck } from './ostereier';
	import Partikel from './Partikel.svelte';

	let { schluessel, ruhig = false }: { schluessel: string; ruhig?: boolean } = $props();

	type Ei = { versteck: Versteck; x: number; y: number; farbton: number };
	let eier = $state<Ei[]>([]);
	let meldung = $state<string | null>(null);
	let feiern = $state(false);

	const ALLE = [...VERSTECKE, GOLDENES_EI] as Versteck[];
	const GROESSE = 20;

	$effect(() => eierStore.laden(schluessel));

	function anker(versteck: Versteck): Element | null {
		return versteck === GOLDENES_EI
			? document.querySelector('[data-versteck="gold"]')
			: document.querySelector(`[data-tour="${versteck}"]`);
	}

	/** Der sichtbare Teil eines Elements: geschnitten mit jedem scrollenden Vorfahren und dem Fenster. */
	function sichtbar(el: Element): DOMRect | null {
		let r = el.getBoundingClientRect();
		if (r.width === 0 || r.height === 0) return null;
		let links = Math.max(r.left, 0);
		let oben = Math.max(r.top, 0);
		let rechts = Math.min(r.right, window.innerWidth);
		let unten = Math.min(r.bottom, window.innerHeight);
		for (let p = el.parentElement; p; p = p.parentElement) {
			const s = getComputedStyle(p);
			if (s.overflowX !== 'visible' || s.overflowY !== 'visible') {
				const q = p.getBoundingClientRect();
				links = Math.max(links, q.left);
				oben = Math.max(oben, q.top);
				rechts = Math.min(rechts, q.right);
				unten = Math.min(unten, q.bottom);
			}
		}
		if (rechts - links < 1 || unten - oben < 1) return null;
		return new DOMRect(links, oben, rechts - links, unten - oben);
	}

	function verteilen() {
		const gefunden = $eierStore.gefunden;
		const neu: Ei[] = [];
		for (const versteck of ALLE) {
			if (gefunden.includes(versteck)) continue;
			const el = anker(versteck);
			if (!el) continue;
			const rahmen = el.getBoundingClientRect();
			const l = lage(versteck, schluessel);
			// Das Ei liegt auf der Kante seines Ankers, halb darüber hinaus.
			let x: number;
			let y: number;
			if (l.kante === 'rechts') {
				x = rahmen.right - GROESSE * 0.6;
				y = rahmen.top + rahmen.height * l.anteil - GROESSE / 2;
			} else {
				x = rahmen.left + rahmen.width * l.anteil - GROESSE / 2;
				y = l.kante === 'oben' ? rahmen.top - GROESSE * 0.45 : rahmen.bottom - GROESSE * 0.55;
			}
			// Nur zeigen, wenn die Mitte des Eis im sichtbaren Teil des Ankers liegt.
			const s = sichtbar(el);
			const mx = x + GROESSE / 2;
			const my = y + GROESSE / 2;
			if (!s || mx < s.left || mx > s.right || my < s.top - GROESSE || my > s.bottom + GROESSE) continue;
			neu.push({ versteck, x, y, farbton: l.farbton });
		}
		eier = neu;
	}

	function finden(versteck: Versteck) {
		eierStore.finden(versteck);
		const n = anzahl($eierStore.gefunden);
		if (versteck === GOLDENES_EI) {
			meldung = '🌟 Das goldene Ei! Ein Bonus für Org-Admins.';
		} else if (n === VERSTECKE.length) {
			meldung = `🐰 Alle ${VERSTECKE.length} Ostereier gefunden! Frohe Ostern!`;
			feiern = true;
			setTimeout(() => (feiern = false), 8000);
		} else {
			meldung = `🥚 ${n} von ${VERSTECKE.length} gefunden`;
		}
		verteilen();
	}

	$effect(() => {
		if (!meldung) return;
		const t = setTimeout(() => (meldung = null), 3500);
		return () => clearTimeout(t);
	});

	onMount(() => {
		verteilen();
		// Reiterwechsel, aufklappende Karten und Schubladen melden sich nicht —
		// ein kurzer Takt fängt alles, und scrollen/resize sofort.
		const takt = setInterval(verteilen, 400);
		let geplant = 0;
		const bald = () => {
			cancelAnimationFrame(geplant);
			geplant = requestAnimationFrame(verteilen);
		};
		window.addEventListener('scroll', bald, true);
		window.addEventListener('resize', bald);
		return () => {
			clearInterval(takt);
			cancelAnimationFrame(geplant);
			window.removeEventListener('scroll', bald, true);
			window.removeEventListener('resize', bald);
		};
	});
</script>

{#each eier as ei (ei.versteck)}
	<button
		class="osterei"
		class:gold={ei.versteck === GOLDENES_EI}
		style="left:{ei.x}px; top:{ei.y}px; --farbton:{ei.farbton}"
		data-versteck-ei={ei.versteck}
		aria-label="Osterei"
		onclick={(e) => { e.stopPropagation(); finden(ei.versteck); }}
	></button>
{/each}

{#if meldung}
	<div class="osterei-meldung" role="status">{meldung}</div>
{/if}

{#if feiern && !ruhig}
	<Partikel art="konfetti" />
{/if}

<style>
	.osterei {
		position: fixed;
		width: 20px;
		height: 26px;
		padding: 0;
		border: 1.5px solid rgba(0, 0, 0, .25);
		border-radius: 50% 50% 50% 50% / 60% 60% 40% 40%;
		background:
			radial-gradient(circle at 35% 30%, rgba(255, 255, 255, .7) 0 3px, transparent 4px),
			repeating-linear-gradient(170deg,
				hsl(var(--farbton) 80% 72%) 0 6px,
				hsl(calc(var(--farbton) + 60) 80% 82%) 6px 9px);
		box-shadow: 0 1px 3px rgba(0, 0, 0, .3);
		cursor: pointer;
		z-index: 2002;
		transform: rotate(-12deg);
		transition: transform .15s;
	}
	.osterei:hover, .osterei:focus-visible { transform: rotate(8deg) scale(1.2); }
	.osterei.gold {
		background:
			radial-gradient(circle at 35% 30%, rgba(255, 255, 255, .85) 0 3px, transparent 4px),
			linear-gradient(160deg, #fde68a, #f59e0b 55%, #b45309);
		animation: osterei-glanz 1.6s ease-in-out infinite alternate;
	}
	@keyframes osterei-glanz {
		from { box-shadow: 0 0 2px #f59e0b; }
		to { box-shadow: 0 0 10px #fbbf24; }
	}
	@media (prefers-reduced-motion: reduce) {
		.osterei, .osterei.gold { animation: none; transition: none; }
	}
	.osterei-meldung {
		position: fixed;
		left: 50%;
		bottom: calc(5rem + env(safe-area-inset-bottom, 0px));
		transform: translateX(-50%);
		padding: .5rem .9rem;
		border-radius: 10px;
		background: var(--surface-2);
		color: var(--text-1);
		border: 1px solid var(--border);
		box-shadow: 0 6px 24px rgba(0, 0, 0, .25);
		font-size: var(--text-sm);
		z-index: 2003;
		pointer-events: none;
	}
	@media print {
		.osterei, .osterei-meldung { display: none; }
	}
</style>
