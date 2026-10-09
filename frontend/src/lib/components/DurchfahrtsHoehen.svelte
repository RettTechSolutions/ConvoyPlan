<script lang="ts">
	/**
	 * Höhenbeschränkungen entlang der berechneten Route (Backend:
	 * `services/durchfahrtshoehe.py`). Gesperrt hat das Routing schon — hier
	 * steht, wie knapp es unter dem Rest hindurchgeht.
	 *
	 * `eintraege === null` heißt: die Route stammt von vor der Auswertung
	 * oder aus einem Import. Dann steht hier nichts, statt „keine Beschränkung"
	 * zu behaupten.
	 */
	import type { DurchfahrtshoeheEntry } from '$lib/api';

	let {
		eintraege,
		fahrzeughoeheM = null,
		ohneHoehe = 0,
	}: {
		eintraege: DurchfahrtshoeheEntry[] | null | undefined;
		/** Höchstes Fahrzeug, mit dem gesperrt wurde (`routing_params.max_height_m`). */
		fahrzeughoeheM?: number | null;
		/** Fahrzeuge im Verband ohne Höhenangabe — die zählen beim Sperren nicht mit. */
		ohneHoehe?: number;
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

	const meter = (m: number, stellen: number) => `${m.toFixed(stellen).replace('.', ',')} m`;
	const cm = (m: number) => `${m >= 0 ? '+' : '−'}${Math.round(Math.abs(m) * 100)} cm`;
</script>

{#if eintraege}
	<section class="dh" class:eng aria-label="Durchfahrtshöhen">
		<p class="dh-titel">↕ Durchfahrtshöhen</p>
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
				<ul class="dh-liste">
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

		<p class="dh-hinweis">
			Aus OpenStreetMap, auf 10 cm gerundet. Unterführungen ohne Angabe fehlen.
			Maßgeblich ist die Beschilderung vor Ort.
		</p>
	</section>
{/if}

<style>
	/* Wie die Hinweisblöcke daneben in der Seitenleiste (Tankstopp, Halte). */
	.dh { background: rgba(127,140,160,.12); border: 1px solid rgba(127,140,160,.4); border-radius: 6px; padding: .65rem; margin-top: .5rem; display: flex; flex-direction: column; gap: .3rem; }
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
	.dh-hinweis { font-size: .75rem; font-style: italic; color: var(--text-muted); }
</style>
