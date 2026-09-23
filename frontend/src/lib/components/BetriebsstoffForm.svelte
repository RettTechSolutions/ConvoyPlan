<!--
  Eingabe der Betriebsstofflage, mit der die Führung eine per Funk
  durchgegebene Meldung nachträgt. Die Besatzung selbst meldet aus der
  Companion-App; hier ist der Weg, wenn sie das nicht kann.

  Gemeldet wird hier nichts — wie bei `StaerkeForm` gehen die Werte an
  `onMelden`, und der Aufrufer weiß, wohin.

  Vorbelegt wird mit der bestehenden Meldung, und wo die fehlt, Tank und
  Verbrauch aus den Stammdaten. Der Füllstand nie: was geplant ist, ist keine
  Tankanzeige. Bei einem E-Fahrzeug gibt es nur den Ladestand — Liter kennt
  es nicht, und die kWh der Stammdaten kennt die Meldung nicht.
-->
<script lang="ts">
	import { untrack } from 'svelte';
	import {
		MAX_FUELLSTAND,
		MAX_TANK,
		MAX_VERBRAUCH,
		type Betriebsstoff,
	} from '$lib/tracking/betriebsstoff';

	let {
		titel = 'Betriebsstoff melden',
		knopf = '⛽ Betriebsstoff melden',
		vorgabe = null,
		stammTank = null,
		stammVerbrauch = null,
		elektrisch = false,
		quittungstext = 'Betriebsstoff gemeldet',
		testid = 'betriebsstoff-form',
		onMelden,
	}: {
		titel?: string;
		knopf?: string;
		/** Die bestehende Meldung — Ausgangsstand für eine Korrektur. */
		vorgabe?: Betriebsstoff | null;
		/** Stammdaten des Fahrzeugs, wo die Meldung Tank oder Verbrauch offen lässt. */
		stammTank?: number | null;
		stammVerbrauch?: number | null;
		elektrisch?: boolean;
		quittungstext?: string;
		testid?: string;
		/** Ein `false` (oder eine Ausnahme) heißt „nicht zugestellt" — dann keine Quittung. */
		onMelden: (lage: Betriebsstoff) => boolean | void | Promise<boolean | void>;
	} = $props();

	const MARKEN = [
		{ label: '¼', wert: 25 },
		{ label: '½', wert: 50 },
		{ label: '¾', wert: 75 },
		{ label: 'Voll', wert: 100 },
	];

	type Eingabe = { verbrauch: number | null; tank: number | null; fuellstand: number | null };

	// `untrack` wie in `StaerkeForm`: gemeint ist der Anfangswert, eine
	// nachgereichte Vorgabe darf eine halbfertige Eingabe nicht überschreiben.
	let eingabe = $state<Eingabe>(
		untrack(() => ({
			verbrauch: elektrisch ? null : (vorgabe?.verbrauch ?? stammVerbrauch ?? null),
			tank: elektrisch ? null : (vorgabe?.tank ?? (stammTank !== null ? Math.round(stammTank) : null)),
			fuellstand: vorgabe?.fuellstand ?? null,
		})),
	);
	let fehler = $state<string | null>(null);
	let quittung = $state(false);
	let laeuft = $state(false);
	let timer: ReturnType<typeof setTimeout> | null = null;

	/** Ein leeres Zahlenfeld liefert `null` oder `''` — beides heißt „keine Angabe". */
	const zahl = (x: unknown): number | null =>
		x === null || x === undefined || x === '' || Number.isNaN(Number(x)) ? null : Number(x);

	/**
	 * Prüft wie der Server und sagt, was nicht passt — statt zu klemmen: eine
	 * stillschweigend auf 100 gesetzte 140 wäre eine Meldung, die niemand so
	 * abgegeben hat.
	 */
	function pruefen(): Betriebsstoff | string {
		const verbrauch = elektrisch ? null : zahl(eingabe.verbrauch);
		const tank = elektrisch ? null : zahl(eingabe.tank);
		const fuellstand = zahl(eingabe.fuellstand);
		if (verbrauch === null && tank === null && fuellstand === null) {
			return 'Ohne Angabe ist das keine Meldung — mindestens ein Feld ausfüllen.';
		}
		if (verbrauch !== null && !(verbrauch > 0 && verbrauch <= MAX_VERBRAUCH)) {
			return `Verbrauch über 0 bis ${MAX_VERBRAUCH} l/100 km.`;
		}
		if (tank !== null && !(Number.isInteger(tank) && tank > 0 && tank <= MAX_TANK)) {
			return `Tank in ganzen Litern, über 0 bis ${MAX_TANK}.`;
		}
		if (fuellstand !== null && !(Number.isInteger(fuellstand) && fuellstand >= 0 && fuellstand <= MAX_FUELLSTAND)) {
			return `${elektrisch ? 'Ladestand' : 'Füllstand'} in ganzen Prozent, 0 bis ${MAX_FUELLSTAND}.`;
		}
		return {
			verbrauch: verbrauch === null ? null : Math.round(verbrauch * 10) / 10,
			tank,
			fuellstand,
		};
	}

	async function melden() {
		if (laeuft) return;
		const lage = pruefen();
		if (typeof lage === 'string') {
			fehler = lage;
			return;
		}
		fehler = null;
		laeuft = true;
		try {
			const ergebnis = await onMelden(lage);
			if (ergebnis === false) return;
			quittung = true;
			if (timer) clearTimeout(timer);
			timer = setTimeout(() => { quittung = false; }, 2500);
		} catch {
			// Der Aufrufer sagt, was schiefging — er kennt den Weg.
		} finally {
			laeuft = false;
		}
	}
</script>

<div class="bs-melden" data-testid={testid}>
	<div class="sub-label">{titel}</div>
	<div class="bs-felder">
		<label class="bs-feld">
			<span>{elektrisch ? 'Ladestand (%)' : 'Füllstand (%)'}</span>
			<input type="number" min="0" max={MAX_FUELLSTAND} step="5" bind:value={eingabe.fuellstand} />
		</label>
		{#if !elektrisch}
			<label class="bs-feld">
				<span>Tank (l)</span>
				<input type="number" min="1" max={MAX_TANK} bind:value={eingabe.tank} />
			</label>
			<label class="bs-feld">
				<span>Verbrauch (l/100 km)</span>
				<input type="number" min="0.1" max={MAX_VERBRAUCH} step="0.1" bind:value={eingabe.verbrauch} />
			</label>
		{/if}
	</div>
	<div class="bs-marken" role="group" aria-label="{elektrisch ? 'Ladestand' : 'Füllstand'} schnell setzen">
		{#each MARKEN as marke}
			<button
				type="button"
				class="bs-marke"
				class:aktiv={zahl(eingabe.fuellstand) === marke.wert}
				aria-pressed={zahl(eingabe.fuellstand) === marke.wert}
				onclick={() => (eingabe.fuellstand = marke.wert)}
			>{marke.label}</button>
		{/each}
	</div>
	{#if fehler}<p class="hint hint-fehler" role="alert">{fehler}</p>{/if}
	<button class="btn-primary" onclick={melden} disabled={laeuft}>{knopf}</button>
	{#if quittung}<p class="hint hint-active">{quittungstext}</p>{/if}
</div>

<style>
	.bs-melden { margin-top: .6rem; padding-top: .6rem; border-top: 1px solid var(--border); }
	.sub-label { font-size: var(--text-xs); color: var(--text-muted); }
	.bs-felder { display: flex; gap: .4rem; margin: .35rem 0 .4rem; }
	.bs-feld { display: flex; flex-direction: column; gap: .15rem; flex: 1; min-width: 0; font-size: .7rem; }
	.bs-feld input { width: 100%; padding: .3rem; text-align: center; font-variant-numeric: tabular-nums; }
	.bs-marken { display: flex; gap: .3rem; margin-bottom: .5rem; }
	.bs-marke { flex: 1; padding: .25rem 0; background: none; border: 1px solid var(--border); border-radius: 4px; color: inherit; cursor: pointer; font-size: .8rem; }
	.bs-marke.aktiv { border-color: var(--color-primary); color: var(--color-primary); }
	.btn-primary { width: 100%; padding: .5rem 1rem; background: var(--color-primary); color: white; border: none; border-radius: 6px; font-weight: 600; cursor: pointer; font-size: var(--text-sm); }
	.btn-primary:disabled { opacity: .5; cursor: not-allowed; }
	.btn-primary:hover:not(:disabled) { background: var(--color-primary-hover); }
	.hint { font-size: var(--text-xs); color: var(--text-muted); font-style: italic; margin: .35rem 0 0; line-height: 1.4; }
	.hint.hint-active { color: #f1c40f; font-style: normal; }
	.hint.hint-fehler { color: #e74c3c; font-style: normal; }
</style>
