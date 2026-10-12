<script lang="ts">
	/**
	 * Höhenbeschränkungen entlang der berechneten Route (Backend:
	 * `services/durchfahrtshoehe.py`). Gesperrt hat das Routing schon — hier
	 * steht, wie knapp es unter dem Rest hindurchgeht.
	 *
	 * `eintraege === null` heißt: die Route stammt von vor der Auswertung
	 * oder aus einem Import. Dann steht hier nichts, statt „keine Beschränkung"
	 * zu behaupten.
	 *
	 * Eingeklappt steht nur der Befund in einer Zeile; aufgeklappt wird von
	 * selbst, sobald es etwas zu prüfen gibt (eng, knapp, Höhe fehlt, keine
	 * Fahrzeughöhe) oder eine Suche nach Brücken aussteht bzw. scheiterte. Die
	 * Seitenleiste soll nicht mit grünen Haken voll stehen, aber eine enge
	 * Stelle darf nicht hinter einem Klick liegen.
	 */
	import type { BrueckenPruefung, DurchfahrtshoeheEntry } from '$lib/api';

	let {
		eintraege,
		fahrzeughoeheM = null,
		ohneHoehe = 0,
		bruecken = null,
		suche = 'idle',
		onSuchen,
	}: {
		eintraege: DurchfahrtshoeheEntry[] | null | undefined;
		/** Höchstes Fahrzeug, mit dem gesperrt wurde (`routing_params.max_height_m`). */
		fahrzeughoeheM?: number | null;
		/** Fahrzeuge im Verband ohne Höhenangabe — die zählen beim Sperren nicht mit. */
		ohneHoehe?: number;
		/** Brücken über der Route ohne Höhenangabe (Backend: `services/bruecken.py`); null = nicht gesucht. */
		bruecken?: BrueckenPruefung | null;
		suche?: 'idle' | 'laeuft' | 'fehler';
		/** Fehlt, wer nicht suchen darf — dann gibt es keinen Knopf. */
		onSuchen?: () => void;
	} = $props();

	const STUFE: Record<DurchfahrtshoeheEntry['stufe'], string> = {
		eng: 'eng – vor Ort prüfen',
		knapp: 'knapp',
		unbekannt: 'Höhe fehlt',
		frei: '',
	};

	let alleZeigen = $state(false);
	const liste = $derived(eintraege ?? []);
	const auffaellig = $derived(liste.filter((e) => e.stufe !== 'frei'));
	const frei = $derived(liste.length - auffaellig.length);
	const sichtbar = $derived(alleZeigen ? liste : auffaellig);
	const eng = $derived(auffaellig.some((e) => e.stufe === 'eng'));

	let schnellZeigen = $state(false);
	const alleBruecken = $derived(bruecken?.eintraege ?? []);
	const brueckenEinzeln = $derived(alleBruecken.filter((b) => !b.schnellstrasse));
	const brueckenSchnell = $derived(alleBruecken.length - brueckenEinzeln.length);
	const brueckenSichtbar = $derived(schnellZeigen ? alleBruecken : brueckenEinzeln);

	const zaehle = (stufe: DurchfahrtshoeheEntry['stufe']) => liste.filter((e) => e.stufe === stufe).length;
	const befund = $derived.by(() => {
		const b: { text: string; art: 'rot' | 'gelb' | 'gruen' | 'grau' }[] = [];
		if (fahrzeughoeheM == null) b.push({ text: 'keine Fahrzeughöhe', art: 'gelb' });
		const n = { eng: zaehle('eng'), knapp: zaehle('knapp'), unbekannt: zaehle('unbekannt') };
		if (n.eng) b.push({ text: `${n.eng} eng`, art: 'rot' });
		if (n.knapp) b.push({ text: `${n.knapp} knapp`, art: 'gelb' });
		if (n.unbekannt) b.push({ text: `${n.unbekannt} Höhe fehlt`, art: 'gelb' });
		if (!b.length) b.push({ text: '✓ frei', art: 'gruen' });
		if (brueckenEinzeln.length) {
			b.push({ text: `${brueckenEinzeln.length} ${brueckenEinzeln.length === 1 ? 'Brücke' : 'Brücken'} o. Angabe`, art: 'grau' });
		}
		return b;
	});

	// Bei jeder neuen Route neu entschieden; danach gehört der Zustand dem Menschen.
	let offen = $state(false);
	$effect.pre(() => {
		offen = auffaellig.length > 0 || fahrzeughoeheM == null;
	});
	// Eine ausstehende oder gescheiterte Suche öffnet nur, schließt nie — sonst
	// klappte der Block unter dem Klick auf „Jetzt suchen" zu.
	$effect.pre(() => {
		if (suche === 'fehler' || (!bruecken && suche === 'idle' && onSuchen)) offen = true;
	});

	const meter = (m: number, stellen: number) => `${m.toFixed(stellen).replace('.', ',')} m`;
	const cm = (m: number) => `${m >= 0 ? '+' : '−'}${Math.round(Math.abs(m) * 100)} cm`;
</script>

{#if eintraege}
	<section class="dh" class:eng aria-label="Durchfahrtshöhen">
		<details bind:open={offen}>
			<summary class="dh-kopf">
				<span class="dh-titel">↕ Durchfahrtshöhen</span>
				{#if fahrzeughoeheM != null}<span class="dh-wert">{meter(fahrzeughoeheM, 2)}</span>{/if}
				<span class="dh-befund">
					{#each befund as b}<span class="dh-chip" data-art={b.art}>{b.text}</span>{/each}
				</span>
			</summary>
			<div class="dh-inhalt">
				{#if fahrzeughoeheM == null}
					<p class="dh-text dh-fehlt">
						Keine Fahrzeughöhe erfasst – die Route meidet keine Höhenbeschränkung.
					</p>
				{:else}
					<p class="dh-text">
						Höchstes Fahrzeug: <strong>{meter(fahrzeughoeheM, 2)}</strong>
						{#if ohneHoehe > 0}
							<span class="dh-ohne">
								· {ohneHoehe === 1 ? '1 Fahrzeug' : `${ohneHoehe} Fahrzeuge`} ohne Höhenangabe, nicht berücksichtigt
							</span>
						{/if}
					</p>
				{/if}

				{#if liste.length === 0}
					<p class="dh-text dh-ok">Keine Höhenbeschränkung auf der Strecke bekannt.</p>
				{:else}
					{#if auffaellig.length === 0 && !alleZeigen}
						<p class="dh-text dh-ok">
							✅ {frei === 1 ? '1 Höhenbeschränkung' : `${frei} Höhenbeschränkungen`}, alle mit mindestens 30 cm Spielraum.
						</p>
					{/if}
					{#if sichtbar.length}
						<ul class="dh-liste" aria-label="Bekannte Höhenbeschränkungen">
							{#each sichtbar as e}
								<li class="dh-eintrag" data-stufe={e.stufe}>
									<span class="dh-km">km {e.km.toFixed(1).replace('.', ',')}</span>
									<span class="dh-hoehe">{meter(e.hoehe_m, 1)}</span>
									{#if e.spielraum_m != null}<span class="dh-spielraum">{cm(e.spielraum_m)}</span>{/if}
									{#if STUFE[e.stufe]}<span class="dh-stufe">{STUFE[e.stufe]}</span>{/if}
								</li>
							{/each}
						</ul>
					{/if}
					{#if frei > 0 && auffaellig.length > 0 && !alleZeigen}
						<button type="button" class="dh-mehr" onclick={() => (alleZeigen = true)}>
							+ {frei} weitere mit mindestens 30 cm Spielraum
						</button>
					{:else if frei > 0 && auffaellig.length === 0 && !alleZeigen}
						<button type="button" class="dh-mehr" onclick={() => (alleZeigen = true)}>Anzeigen</button>
					{/if}
				{/if}

				<div class="dh-bruecken">
					<p class="dh-untertitel">Brücken ohne Höhenangabe</p>
					{#if suche === 'laeuft'}
						<p class="dh-text dh-ohne">Suche läuft …</p>
					{:else if suche === 'fehler'}
						<p class="dh-text dh-ohne">Suche fehlgeschlagen – OpenStreetMap-Dienst nicht erreichbar.</p>
						{#if onSuchen}<button type="button" class="dh-mehr" onclick={onSuchen}>Erneut suchen</button>{/if}
					{:else if !bruecken}
						<p class="dh-text dh-ohne">Nicht gesucht.</p>
						{#if onSuchen}<button type="button" class="dh-mehr" onclick={onSuchen}>Jetzt suchen</button>{/if}
					{:else if alleBruecken.length === 0}
						<p class="dh-text dh-ok">Keine Brücke ohne Höhenangabe über der Route gefunden.</p>
					{:else}
						{#if brueckenSichtbar.length}
							<ul class="dh-liste" aria-label="Brücken ohne Höhenangabe">
								{#each brueckenSichtbar as b}
									<li class="dh-eintrag dh-bruecke">
										<span class="dh-km">km {b.km.toFixed(1).replace('.', ',')}</span>
										<span class="dh-art">{b.art}</span>
										{#if b.name}<span class="dh-name">{b.name}</span>{/if}
										{#if b.osm_ids.length}
											<a class="dh-osm" href={`https://www.openstreetmap.org/way/${b.osm_ids[0]}`} target="_blank" rel="noopener noreferrer">OSM</a>
										{/if}
									</li>
								{/each}
							</ul>
						{/if}
						{#if brueckenSchnell > 0 && !schnellZeigen}
							<button type="button" class="dh-mehr" onclick={() => (schnellZeigen = true)}>
								+ {brueckenSchnell} auf Autobahn- oder Kraftfahrstraßenabschnitten
							</button>
						{/if}
					{/if}
				</div>

				<p class="dh-hinweis">
					Aus OpenStreetMap, auf 10 cm gerundet. Bei Brücken ohne Angabe ist die Höhe unbekannt.
					Maßgeblich ist die Beschilderung vor Ort.
				</p>
			</div>
		</details>
	</section>
{/if}

<style>
	/* Wie die Hinweisblöcke daneben in der Seitenleiste (Tankstopp, Halte). */
	.dh { background: rgba(127,140,160,.12); border: 1px solid rgba(127,140,160,.4); border-radius: 6px; padding: .45rem .65rem; margin-top: .5rem; }
	.dh-kopf { display: flex; flex-wrap: wrap; align-items: center; gap: .25rem .45rem; cursor: pointer; list-style: none; }
	.dh-kopf::-webkit-details-marker { display: none; }
	.dh-kopf::before { content: '▸'; font-size: .7rem; opacity: .6; transition: transform .15s; }
	details[open] > .dh-kopf::before { transform: rotate(90deg); }
	.dh-wert { font-size: .8rem; color: var(--text-muted); }
	.dh-befund { display: flex; flex-wrap: wrap; gap: .25rem; margin-left: auto; }
	.dh-chip { padding: .05rem .4rem; border-radius: 3px; font-size: .72rem; white-space: nowrap; background: rgba(127,127,127,.2); }
	.dh-chip[data-art='rot'] { background: rgba(226,61,40,.3); color: #ff9c8a; font-weight: 700; }
	.dh-chip[data-art='gelb'] { background: rgba(241,196,15,.22); color: #e0b928; }
	.dh-chip[data-art='gruen'] { background: rgba(111,191,142,.18); color: #6fbf8e; }
	.dh-inhalt { display: flex; flex-direction: column; gap: .3rem; margin-top: .4rem; }
	.dh.eng { background: rgba(226,61,40,.15); border-color: rgba(226,61,40,.5); }
	.dh p { margin: 0; }
	.dh-titel { font-weight: 700; font-size: .88rem; }
	.dh-text { font-size: .83rem; }
	.dh-ohne, .dh-fehlt { color: var(--text-muted); }
	.dh-ok { color: #6fbf8e; }
	.dh-liste { list-style: none; padding: 0; margin: .1rem 0 0; display: flex; flex-direction: column; gap: .25rem; }
	.dh-eintrag { display: flex; flex-wrap: wrap; align-items: baseline; gap: .2rem .5rem; padding: .3rem .4rem; background: rgba(127,127,127,.1); border-radius: 4px; font-size: .82rem; }
	.dh-km { min-width: 4.2rem; color: var(--text-muted); }
	.dh-hoehe { font-weight: 700; }
	.dh-stufe { margin-left: auto; padding: .05rem .35rem; border-radius: 3px; font-size: .75rem; background: rgba(127,127,127,.2); }
	[data-stufe='eng'] .dh-stufe { background: rgba(226,61,40,.3); color: #ff9c8a; font-weight: 700; }
	[data-stufe='knapp'] .dh-stufe { background: rgba(241,196,15,.22); color: #e0b928; }
	.dh-mehr { align-self: flex-start; background: none; border: none; padding: 0; color: inherit; text-decoration: underline; cursor: pointer; font-size: .8rem; opacity: .8; }
	.dh-bruecken { display: flex; flex-direction: column; gap: .25rem; border-top: 1px solid rgba(127,127,127,.25); padding-top: .4rem; margin-top: .1rem; }
	.dh-untertitel { font-weight: 600; font-size: .83rem; }
	.dh-art { font-weight: 600; }
	.dh-name { color: var(--text-muted); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; max-width: 100%; }
	.dh-osm { margin-left: auto; font-size: .75rem; color: inherit; opacity: .8; }
	.dh-hinweis { font-size: .75rem; font-style: italic; color: var(--text-muted); }
</style>
