<script lang="ts">
	/**
	 * Gewichtsgrenzen entlang der berechneten Route (Backend:
	 * `services/gewichtsgrenzen.py`). Gesperrt hat das Routing schon — außer bei
	 * „Anlieger frei", das nur gemieden wird; muss die Route dort trotzdem durch,
	 * steht die Stelle als überschritten da.
	 *
	 * `eintraege === null` heißt: nicht ermittelt (alte Route, Import, oder der
	 * Graph kennt `max_weight` noch nicht). Dann steht hier nichts.
	 *
	 * Eingeklappt wie `DurchfahrtsHoehen.svelte`: aufgeklappt von selbst, sobald
	 * eine Stelle über der Grenze, knapp oder ohne Gewicht ist oder kein
	 * Fahrzeuggewicht erfasst ist.
	 */
	import type { GewichtsgrenzeEntry } from '$lib/api';

	let {
		eintraege,
		fahrzeuggewichtT = null,
		achslastT = null,
		ohneGewicht = 0,
		onZeigen,
	}: {
		eintraege: GewichtsgrenzeEntry[] | null | undefined;
		/** Schwerstes Fahrzeug, mit dem gesperrt wurde (`routing_params.max_weight_t`). */
		fahrzeuggewichtT?: number | null;
		/** Größte Achslast im Verband, mit der gesperrt wurde (`routing_params.max_axle_load_t`). */
		achslastT?: number | null;
		/** Fahrzeuge im Verband ohne Gewicht — die zählen beim Sperren nicht mit. */
		ohneGewicht?: number;
		/** Stelle auf der Karte zeigen; fehlt er, bleibt der Kilometer reiner Text. */
		onZeigen?: (lat: number, lon: number) => void;
	} = $props();

	const STUFE: Record<GewichtsgrenzeEntry['stufe'], string> = {
		ueberschritten: 'über der Grenze',
		knapp: 'knapp',
		unbekannt: 'Gewicht fehlt',
		frei: '',
	};
	const AUSNAHME: Record<string, string> = {
		destination: 'Anlieger frei',
		delivery: 'Lieferverkehr frei',
		forestry: 'Forstverkehr frei',
	};

	let alleZeigen = $state(false);
	const liste = $derived(eintraege ?? []);
	const auffaellig = $derived(liste.filter((e) => e.stufe !== 'frei'));
	const frei = $derived(liste.length - auffaellig.length);
	const sichtbar = $derived(alleZeigen ? liste : auffaellig);
	const ueber = $derived(auffaellig.some((e) => e.stufe === 'ueberschritten'));

	const zaehle = (stufe: GewichtsgrenzeEntry['stufe']) => liste.filter((e) => e.stufe === stufe).length;
	const befund = $derived.by(() => {
		const b: { text: string; art: 'rot' | 'gelb' | 'gruen' }[] = [];
		if (fahrzeuggewichtT == null) b.push({ text: 'kein Fahrzeuggewicht', art: 'gelb' });
		const n = { ueber: zaehle('ueberschritten'), knapp: zaehle('knapp'), unbekannt: zaehle('unbekannt') };
		if (n.ueber) b.push({ text: `${n.ueber} über der Grenze`, art: 'rot' });
		if (n.knapp) b.push({ text: `${n.knapp} knapp`, art: 'gelb' });
		if (n.unbekannt) b.push({ text: `${n.unbekannt} Gewicht fehlt`, art: 'gelb' });
		if (!b.length) b.push({ text: '✓ frei', art: 'gruen' });
		return b;
	});

	// Bei jeder neuen Route neu entschieden; danach gehört der Zustand dem Menschen.
	let offen = $state(false);
	$effect.pre(() => {
		offen = auffaellig.length > 0 || fahrzeuggewichtT == null;
	});

	const tonnen = (t: number) => `${t.toFixed(1).replace('.', ',')} t`;
	const reserve = (t: number) => `${t >= 0 ? '+' : '−'}${Math.abs(t).toFixed(1).replace('.', ',')} t`;
</script>

{#snippet km(e: { km: number; lat: number; lon: number })}
	{@const text = `km ${e.km.toFixed(1).replace('.', ',')}`}
	{#if onZeigen}
		<button type="button" class="gg-km gg-zeigen" title="Auf der Karte zeigen" aria-label="{text} auf der Karte zeigen" onclick={() => onZeigen?.(e.lat, e.lon)}>📍 {text}</button>
	{:else}
		<span class="gg-km">{text}</span>
	{/if}
{/snippet}

{#if eintraege}
	<section class="gg" class:ueber aria-label="Gewichtsgrenzen">
		<details bind:open={offen}>
			<summary class="gg-kopf">
				<span class="gg-titel">⚖ Gewichtsgrenzen</span>
				{#if fahrzeuggewichtT != null}<span class="gg-wert">{tonnen(fahrzeuggewichtT)}</span>{/if}
				<span class="gg-befund">
					{#each befund as b}<span class="gg-chip" data-art={b.art}>{b.text}</span>{/each}
				</span>
			</summary>
			<div class="gg-inhalt">
				{#if fahrzeuggewichtT == null}
					<p class="gg-text gg-blass">Kein Fahrzeuggewicht erfasst – die Route meidet keine Gewichtsgrenze.</p>
				{:else}
					<p class="gg-text">
						Schwerstes Fahrzeug: <strong>{tonnen(fahrzeuggewichtT)}</strong>
						{#if ohneGewicht > 0}
							<span class="gg-blass">
								· {ohneGewicht === 1 ? '1 Fahrzeug' : `${ohneGewicht} Fahrzeuge`} ohne Gewicht, nicht berücksichtigt
							</span>
						{/if}
					</p>
				{/if}
				{#if achslastT != null}
					<p class="gg-text">Größte Achslast: <strong>{tonnen(achslastT)}</strong></p>
				{/if}

				{#if liste.length === 0}
					<p class="gg-text gg-ok">Keine Gewichtsgrenze auf der Strecke bekannt.</p>
				{:else}
					{#if auffaellig.length === 0 && !alleZeigen}
						<p class="gg-text gg-ok">
							✅ {frei === 1 ? '1 Grenze' : `${frei} Grenzen`}, alle mit ausreichender Reserve.
						</p>
					{/if}
					{#if sichtbar.length}
						<ul class="gg-liste" aria-label="Gewichtsgrenzen an der Route">
							{#each sichtbar as e}
								<li class="gg-eintrag" data-stufe={e.stufe}>
									{@render km(e)}
									<span class="gg-grenze">{e.art === 'achslast' ? `Achslast ${tonnen(e.grenze_t)}` : tonnen(e.grenze_t)}</span>
									{#if e.reserve_t != null}<span>{reserve(e.reserve_t)}</span>{/if}
									{#if e.ausnahme && AUSNAHME[e.ausnahme]}<span class="gg-blass">{AUSNAHME[e.ausnahme]}</span>{/if}
									{#if STUFE[e.stufe]}<span class="gg-stufe">{STUFE[e.stufe]}</span>{/if}
								</li>
							{/each}
						</ul>
					{/if}
					{#if frei > 0 && !alleZeigen}
						<button type="button" class="gg-mehr" onclick={() => (alleZeigen = true)}>
							{auffaellig.length ? `+ ${frei} weitere mit ausreichender Reserve` : 'Anzeigen'}
						</button>
					{/if}
				{/if}

				<p class="gg-hinweis">
					Aus OpenStreetMap (auch Lkw-Durchfahrtsverbote). Gewicht auf 0,1 t, Achslast auf 0,5 t gerundet, verglichen
					mit dem schwersten Fahrzeug bzw. der größten Achslast. Knapp: unter 2 t Reserve beim Gewicht, unter 1 t bei
					der Achslast. Maßgeblich ist die Beschilderung vor Ort.
				</p>
			</div>
		</details>
	</section>
{/if}

<style>
	/* Wie DurchfahrtsHoehen.svelte darüber. */
	.gg { background: rgba(127,140,160,.12); border: 1px solid rgba(127,140,160,.4); border-radius: 6px; padding: .45rem .65rem; margin-top: .5rem; }
	.gg-kopf { display: flex; flex-wrap: wrap; align-items: center; gap: .25rem .45rem; cursor: pointer; list-style: none; }
	.gg-kopf::-webkit-details-marker { display: none; }
	.gg-kopf::before { content: '▸'; font-size: .7rem; opacity: .6; transition: transform .15s; }
	details[open] > .gg-kopf::before { transform: rotate(90deg); }
	.gg-wert { font-size: .8rem; color: var(--text-muted); }
	.gg-befund { display: flex; flex-wrap: wrap; gap: .25rem; margin-left: auto; }
	.gg-chip { padding: .05rem .4rem; border-radius: 3px; font-size: .72rem; white-space: nowrap; background: rgba(127,127,127,.2); }
	.gg-chip[data-art='rot'] { background: rgba(226,61,40,.3); color: #ff9c8a; font-weight: 700; }
	.gg-chip[data-art='gelb'] { background: rgba(241,196,15,.22); color: #e0b928; }
	.gg-chip[data-art='gruen'] { background: rgba(111,191,142,.18); color: #6fbf8e; }
	.gg-inhalt { display: flex; flex-direction: column; gap: .3rem; margin-top: .4rem; }
	.gg.ueber { background: rgba(226,61,40,.15); border-color: rgba(226,61,40,.5); }
	.gg p { margin: 0; }
	.gg-titel { font-weight: 700; font-size: .88rem; }
	.gg-text { font-size: .83rem; }
	.gg-blass { color: var(--text-muted); }
	.gg-ok { color: #6fbf8e; }
	.gg-liste { list-style: none; padding: 0; margin: .1rem 0 0; display: flex; flex-direction: column; gap: .25rem; }
	.gg-eintrag { display: flex; flex-wrap: wrap; align-items: baseline; gap: .2rem .5rem; padding: .3rem .4rem; background: rgba(127,127,127,.1); border-radius: 4px; font-size: .82rem; }
	.gg-km { min-width: 4.2rem; color: var(--text-muted); }
	.gg-grenze { font-weight: 700; }
	.gg-stufe { margin-left: auto; padding: .05rem .35rem; border-radius: 3px; font-size: .75rem; background: rgba(127,127,127,.2); }
	[data-stufe='ueberschritten'] .gg-stufe { background: rgba(226,61,40,.3); color: #ff9c8a; font-weight: 700; }
	[data-stufe='knapp'] .gg-stufe { background: rgba(241,196,15,.22); color: #e0b928; }
	.gg-mehr { align-self: flex-start; background: none; border: none; padding: 0; color: inherit; text-decoration: underline; cursor: pointer; font-size: .8rem; opacity: .8; }
	.gg-hinweis { font-size: .75rem; font-style: italic; color: var(--text-muted); }
	.gg-zeigen { background: none; border: none; padding: 0; font: inherit; color: inherit; text-align: left; cursor: pointer; text-decoration: underline dotted; text-underline-offset: 2px; }
	.gg-zeigen:hover, .gg-zeigen:focus-visible { text-decoration-style: solid; }
</style>
