<script lang="ts">
	/**
	 * Adventskalender (`adventskalender.ts`): das heutige Türchen an seinem
	 * Anker, und ist es offen, an derselben Stelle ein Kalender zum Nachlesen
	 * und Nachholen. Ein Kalender zum Nachholen gibt es also erst, wenn das
	 * heutige gefunden ist — den Weg drumherum gibt es nicht. Türchen 24
	 * schickt einen Schlittenkonvoi über den Schirm.
	 */
	import { onMount } from 'svelte';
	import { mitverfolgen, platzieren } from './anker';
	import { bisTag, kalenderStore, lage, TUERCHEN, tuerchenHeute, versteck } from './adventskalender';

	let { schluessel, ruhig = false }: { schluessel: string; ruhig?: boolean } = $props();

	const GROESSE = 24;
	let ort = $state<{ x: number; y: number } | null>(null);
	let heute = $state<number | null>(null);
	let bis = $state(0);
	let offen = $state(false);
	let gezeigt = $state<number | null>(null);
	let schlitten = $state(0);
	let dialog = $state<HTMLDivElement>();

	$effect(() => kalenderStore.laden(schluessel));

	/** Heute noch zu finden? Dann liegt ein Geschenk da, sonst der Kalender. */
	const geschenk = $derived(heute !== null && !$kalenderStore.offen.includes(heute));

	function verteilen() {
		const jetzt = new Date();
		heute = tuerchenHeute(jetzt);
		bis = bisTag(jetzt);
		const tag = heute ?? 24;
		const el = document.querySelector(`[data-tour="${versteck(tag, schluessel)}"]`);
		ort = el ? platzieren(el, lage(tag, schluessel), GROESSE) : null;
	}

	function zeigen(tag: number) {
		kalenderStore.oeffnen(tag);
		gezeigt = tag;
		offen = true;
		if (tag === 24 && !ruhig) schlitten += 1;
	}

	function klick() {
		if (geschenk && heute !== null) zeigen(heute);
		else {
			gezeigt = null;
			offen = true;
		}
	}

	function schliessen() {
		offen = false;
	}

	$effect(() => {
		if (offen) dialog?.focus();
	});

	onMount(() => mitverfolgen(verteilen));
</script>

{#if ort && bis > 0}
	<button
		class="advent-tuer"
		class:geschenk
		style="left:{ort.x}px; top:{ort.y}px"
		data-advent={geschenk ? 'tuerchen' : 'kalender'}
		aria-label={geschenk ? `Adventstürchen ${heute}` : 'Adventskalender öffnen'}
		onclick={(e) => { e.stopPropagation(); klick(); }}
	>{#if geschenk}<span>🎁</span><b>{heute}</b>{:else}📅{/if}</button>
{/if}

{#if offen}
	<!-- svelte-ignore a11y_click_events_have_key_events, a11y_no_static_element_interactions -->
	<div class="advent-hintergrund" onclick={schliessen}>
		<!-- svelte-ignore a11y_click_events_have_key_events, a11y_no_noninteractive_element_interactions -->
		<div
			class="advent-dialog"
			role="dialog"
			aria-modal="true"
			aria-labelledby="advent-titel"
			tabindex="-1"
			bind:this={dialog}
			onclick={(e) => e.stopPropagation()}
			onkeydown={(e) => { if (e.key === 'Escape') schliessen(); }}
		>
			<div class="advent-kopf">
				<h2 id="advent-titel">{gezeigt ? `Türchen ${gezeigt}` : 'Adventskalender'}</h2>
				<button class="advent-zu" onclick={schliessen} aria-label="Schließen">✕</button>
			</div>

			{#if gezeigt}
				<p class="advent-inhalt"><span class="advent-symbol">{TUERCHEN[gezeigt - 1].symbol}</span>{TUERCHEN[gezeigt - 1].text}</p>
			{:else}
				<p class="advent-inhalt">{$kalenderStore.offen.length} von 24 Türchen geöffnet. Verpasste Tage lassen sich nachholen – das heutige muss man finden.</p>
			{/if}

			<ol class="advent-raster">
				{#each TUERCHEN as t, i (i)}
					{@const tag = i + 1}
					{@const istOffen = $kalenderStore.offen.includes(tag)}
					<li>
						{#if istOffen}
							<button class="advent-feld auf" class:aktiv={gezeigt === tag} onclick={() => zeigen(tag)} aria-label="Türchen {tag}, geöffnet">
								<small>{tag}</small>{t.symbol}
							</button>
						{:else if tag <= bis}
							<button class="advent-feld zu" onclick={() => zeigen(tag)} aria-label="Türchen {tag} nachholen">
								<small>{tag}</small>
							</button>
						{:else}
							<button class="advent-feld" disabled aria-label="Türchen {tag}, noch geschlossen">
								<small>{tag}</small>🔒
							</button>
						{/if}
					</li>
				{/each}
			</ol>
		</div>
	</div>
{/if}

{#key schlitten}
	{#if schlitten > 0}
		<div class="advent-schlitten" aria-hidden="true">🦌🦌🦌🛷🎅&nbsp;&nbsp;🚒&nbsp;🚑&nbsp;🚓&nbsp;🚐</div>
	{/if}
{/key}

<style>
	.advent-tuer {
		position: fixed;
		width: 24px;
		height: 24px;
		padding: 0;
		display: grid;
		place-items: center;
		border: none;
		border-radius: 6px;
		background: none;
		font-size: 18px;
		line-height: 1;
		cursor: pointer;
		z-index: 2002;
		filter: drop-shadow(0 1px 2px rgba(0, 0, 0, .35));
		transition: transform .15s;
	}
	.advent-tuer:hover, .advent-tuer:focus-visible { transform: scale(1.2) rotate(-6deg); }
	.advent-tuer.geschenk { animation: advent-wackeln 3s ease-in-out infinite; }
	.advent-tuer b {
		position: absolute;
		right: -6px;
		bottom: -4px;
		min-width: 14px;
		padding: 0 3px;
		border-radius: 7px;
		background: #b91c1c;
		color: #fff;
		font-size: 9px;
		line-height: 14px;
	}
	@keyframes advent-wackeln {
		0%, 85%, 100% { transform: rotate(0); }
		88% { transform: rotate(-12deg); }
		92% { transform: rotate(10deg); }
		96% { transform: rotate(-6deg); }
	}

	.advent-hintergrund {
		position: fixed;
		inset: 0;
		display: grid;
		place-items: center;
		padding: 1rem;
		background: rgba(0, 0, 0, .45);
		z-index: 2004;
	}
	.advent-dialog {
		width: min(28rem, 100%);
		max-height: calc(100dvh - 2rem);
		overflow: auto;
		padding: 1rem 1.1rem 1.2rem;
		border-radius: 14px;
		background: var(--surface-1);
		color: var(--text-1);
		border: 1px solid var(--border);
		box-shadow: 0 12px 40px rgba(0, 0, 0, .35);
		outline: none;
	}
	.advent-kopf { display: flex; align-items: center; justify-content: space-between; gap: 1rem; }
	.advent-kopf h2 { margin: 0; font-size: var(--text-lg); }
	.advent-zu { background: none; border: none; color: var(--text-2); font-size: 1rem; cursor: pointer; padding: .25rem .4rem; }
	.advent-inhalt { margin: .75rem 0 1rem; font-size: var(--text-base); line-height: 1.45; color: var(--text-2); }
	.advent-symbol { font-size: 1.6rem; display: block; margin-bottom: .35rem; }

	.advent-raster {
		list-style: none;
		margin: 0;
		padding: 0;
		display: grid;
		grid-template-columns: repeat(6, 1fr);
		gap: .4rem;
	}
	.advent-feld {
		position: relative;
		width: 100%;
		aspect-ratio: 1;
		display: grid;
		place-items: center;
		border-radius: 8px;
		border: 1px solid var(--border);
		background: var(--surface-2);
		color: var(--text-muted);
		font-size: 1.1rem;
		cursor: default;
	}
	.advent-feld small { position: absolute; top: 3px; left: 5px; font-size: .62rem; color: var(--text-muted); }
	.advent-feld.zu {
		cursor: pointer;
		background: linear-gradient(135deg, #7f1d1d, #b91c1c);
		border-color: #991b1b;
	}
	.advent-feld.zu small { color: #fde68a; font-size: .8rem; position: static; }
	.advent-feld.auf { cursor: pointer; color: inherit; }
	.advent-feld.aktiv { border-color: var(--color-primary); }

	/* Der Schlittenkonvoi: einmal von rechts nach links durchs obere Drittel. */
	.advent-schlitten {
		position: fixed;
		top: 18vh;
		left: 100vw;
		white-space: nowrap;
		font-size: 1.8rem;
		pointer-events: none;
		z-index: 2005;
		animation: advent-flug 11s linear 1 forwards, advent-schweben 1.4s ease-in-out infinite alternate;
	}
	@keyframes advent-flug {
		from { left: 100vw; }
		to { left: -60rem; }
	}
	@keyframes advent-schweben {
		from { margin-top: -6px; }
		to { margin-top: 6px; }
	}

	@media (prefers-reduced-motion: reduce) {
		.advent-tuer, .advent-tuer.geschenk { animation: none; transition: none; }
	}
	@media print {
		.advent-tuer, .advent-hintergrund, .advent-schlitten { display: none; }
	}
</style>
