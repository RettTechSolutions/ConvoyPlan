<script lang="ts">
	/**
	 * Geisterjagd (`geisterjagd.ts`): In Abständen lugt ein Geist an einem
	 * gerade sichtbaren Anker hervor. Angetippt ist er gefangen, und es gibt
	 * Süßes oder Saures. Pausiert, solange der Tab verdeckt ist.
	 */
	import { onMount } from 'svelte';
	import { platzieren, wuerfeln } from './anker';
	import { VERSTECKE } from './ostereier';
	import { ABSTAND_MS, ausgang, ERSTER_MS, geisterStore, SICHTBAR_MS, ZIEL, type Saures } from './geisterjagd';

	let { schluessel, ruhig = false }: { schluessel: string; ruhig?: boolean } = $props();

	const GROESSE = 28;
	let geist = $state<{ anker: string; x: number; y: number; nr: number } | null>(null);
	let meldung = $state<string | null>(null);
	let saures = $state<Saures | null>(null);
	let saeuerlich = 0;
	let nummer = 0;

	$effect(() => geisterStore.laden(schluessel));

	function erscheinen() {
		if (document.hidden) return;
		// Nur Anker, die gerade zu sehen sind — sonst spukt es im falschen Reiter.
		const kandidaten = VERSTECKE.map((a) => {
			const el = document.querySelector(`[data-tour="${a}"]`);
			const lage = wuerfeln(`geist-${nummer}-${a}:${schluessel}`);
			const ort = el ? platzieren(el, lage, GROESSE) : null;
			return ort ? { anker: a, ...ort } : null;
		}).filter((k) => k !== null);
		if (!kandidaten.length) return;
		nummer += 1;
		geist = { ...kandidaten[Math.floor(Math.random() * kandidaten.length)], nr: nummer };
		const meiner = nummer;
		setTimeout(() => {
			if (geist?.nr === meiner) geist = null;
		}, SICHTBAR_MS);
	}

	function fangen() {
		geist = null;
		geisterStore.fangen();
		const n = $geisterStore.gefangen;
		if (n === ZIEL) {
			meldung = `🎃 ${ZIEL} Geister gefangen – du bist offiziell Geisterjäger!`;
			ausloesen('schwarm');
			return;
		}
		const a = ausgang(Math.random());
		meldung = `${a.text} (👻 ${n})`;
		if (a.saures) ausloesen(a.saures);
	}

	function ausloesen(art: Saures) {
		if (ruhig) return;
		saures = art;
		document.documentElement.dataset.saures = art;
		clearTimeout(saeuerlich);
		saeuerlich = window.setTimeout(() => {
			saures = null;
			delete document.documentElement.dataset.saures;
		}, 2600);
	}

	$effect(() => {
		if (!meldung) return;
		const t = setTimeout(() => (meldung = null), 3500);
		return () => clearTimeout(t);
	});

	onMount(() => {
		let zeit = window.setTimeout(function weiter() {
			erscheinen();
			const [min, max] = ABSTAND_MS;
			zeit = window.setTimeout(weiter, min + Math.random() * (max - min));
		}, ERSTER_MS);
		return () => {
			clearTimeout(zeit);
			clearTimeout(saeuerlich);
			delete document.documentElement.dataset.saures;
		};
	});
</script>

{#if geist}
	{#key geist.nr}
		<button
			class="geist"
			class:ruhig
			style="left:{geist.x}px; top:{geist.y}px"
			data-geist={geist.anker}
			aria-label="Geist fangen"
			onclick={(e) => { e.stopPropagation(); fangen(); }}
		><span>👻</span></button>
	{/key}
{/if}

{#if meldung}
	<div class="geist-meldung" role="status">{meldung}</div>
{/if}

{#if saures === 'schwarm'}
	<div class="geist-schwarm" aria-hidden="true">
		{#each [0, 1, 2, 3, 4, 5, 6] as i (i)}
			<span style="--i:{i}">🦇</span>
		{/each}
	</div>
{/if}

<style>
	.geist {
		position: fixed;
		width: 28px;
		height: 28px;
		padding: 0;
		border: none;
		background: none;
		font-size: 24px;
		line-height: 1;
		cursor: pointer;
		z-index: 2002;
		filter: drop-shadow(0 0 6px rgba(167, 139, 250, .8));
	}
	/* Nur das Gespenst schwebt, die Trefferfläche bleibt stehen — am Telefon
	   trifft man sonst daneben. */
	.geist span { display: block; animation: geist-auftauchen 5s ease-in-out 1 forwards; }
	.geist.ruhig span { animation: none; }
	@keyframes geist-auftauchen {
		0% { opacity: 0; transform: translateY(8px) scale(.6); }
		12% { opacity: .95; transform: translateY(0) scale(1); }
		50% { transform: translateY(-4px) rotate(-6deg); }
		85% { opacity: .95; transform: translateY(0) rotate(4deg); }
		100% { opacity: 0; transform: translateY(-10px) scale(.8); }
	}

	.geist-meldung {
		position: fixed;
		left: 50%;
		bottom: calc(5rem + env(safe-area-inset-bottom, 0px));
		transform: translateX(-50%);
		max-width: min(30rem, calc(100vw - 2rem));
		padding: .5rem .9rem;
		border-radius: 10px;
		background: var(--surface-2);
		color: var(--text-1);
		border: 1px solid var(--border);
		box-shadow: 0 6px 24px rgba(0, 0, 0, .25);
		font-size: var(--text-sm);
		text-align: center;
		z-index: 2003;
		pointer-events: none;
	}

	/* Saures: ein Schwarm, einmal schräg durchs Bild. */
	.geist-schwarm {
		position: fixed;
		inset: 0;
		pointer-events: none;
		z-index: 2001;
		overflow: hidden;
	}
	.geist-schwarm span {
		position: absolute;
		left: -3rem;
		top: calc(20% + var(--i) * 7%);
		font-size: calc(1.2rem + var(--i) * .15rem);
		animation: geist-flattern 2.4s linear 1 forwards;
		animation-delay: calc(var(--i) * 90ms);
	}
	@keyframes geist-flattern {
		from { transform: translate(0, 0); }
		to { transform: translate(calc(100vw + 6rem), -18vh); }
	}

	@media print {
		.geist, .geist-meldung, .geist-schwarm { display: none; }
	}
</style>
