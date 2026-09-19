<!--
  Die Eingabe der Mannschaftsstärke — dieselbe im Fahrer-Link, wo die Besatzung
  selbst meldet, und in der Tracking-Ansicht, wo die Führung eine über Funk
  durchgegebene Stärke nachträgt. Gemeinsame Komponente aus demselben Grund wie
  `StaerkeBadge`: Notation, Grenzen und Rundung gelten an beiden Stellen, und
  zwar gleich.

  Gemeldet wird hier nichts. Die drei Zahlen gehen an `onMelden`, und was damit
  geschieht, weiß der Aufrufer: der Fahrer-Link schickt sie über seinen
  WebSocket, die Tracking-Ansicht über `PATCH …/staerke`.
-->
<script lang="ts">
	import { untrack } from 'svelte';
	import { MAX_JE_ROLLE, gesamt, type Staerke } from '$lib/tracking/staerke';

	let {
		titel = 'Mannschaftsstärke melden',
		knopf = '👥 Stärke melden',
		vorgabe = null,
		quittungstext = 'Stärke gemeldet',
		testid = 'staerke-form',
		onMelden,
	}: {
		titel?: string;
		knopf?: string;
		/**
		 * Ausgangsstand der Felder — eine **bestehende Meldung**, die korrigiert
		 * wird, sonst nichts. Ausdrücklich nicht das Soll: was geplant war, ist
		 * keine Meldung, und ein vorausgefülltes Soll machte das Bestätigen zur
		 * bequemsten Antwort. Genau den Unterschied hält `StaerkeBadge` fest.
		 */
		vorgabe?: Staerke | null;
		quittungstext?: string;
		testid?: string;
		/**
		 * Nimmt die geprüften Zahlen entgegen. Ein `false` (oder eine Ausnahme)
		 * heißt „nicht zugestellt" — dann bleibt die Quittung aus, statt einen
		 * Versand zu bestätigen, den es nicht gab.
		 */
		onMelden: (staerke: Staerke) => boolean | void | Promise<boolean | void>;
	} = $props();

	const LEER: Staerke = { fuehrer: 0, unterfuehrer: 0, mannschaften: 0 };

	// `untrack`, weil genau der Anfangswert gemeint ist: was danach getippt
	// wird, gehört dem Formular — eine nachgereichte Vorgabe dürfte die
	// halbfertige Eingabe nicht überschreiben.
	let eingabe = $state<Staerke>(untrack(() => ({ ...(vorgabe ?? LEER) })));
	let quittung = $state(false);
	let laeuft = $state(false);
	let timer: ReturnType<typeof setTimeout> | null = null;

	/** Was das Feld hergibt, auf das Erlaubte gebracht — dieselben Grenzen wie hinten. */
	const klemm = (n: number) => Math.min(MAX_JE_ROLLE, Math.max(0, Math.round(Number(n) || 0)));

	const werte = $derived<Staerke>({
		fuehrer: klemm(eingabe.fuehrer),
		unterfuehrer: klemm(eingabe.unterfuehrer),
		mannschaften: klemm(eingabe.mannschaften),
	});
	const summe = $derived(gesamt(werte));

	async function melden() {
		if (laeuft) return;
		laeuft = true;
		try {
			const ergebnis = await onMelden({ ...werte });
			if (ergebnis === false) return;
			eingabe = { ...werte };
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

<div class="staerke-melden" data-testid={testid}>
	<div class="sub-label">{titel}</div>
	<div class="staerke-felder">
		<label class="staerke-feld">
			<span>Führer</span>
			<input type="number" min="0" max={MAX_JE_ROLLE} bind:value={eingabe.fuehrer} />
		</label>
		<label class="staerke-feld">
			<span>Unterführer</span>
			<input type="number" min="0" max={MAX_JE_ROLLE} bind:value={eingabe.unterfuehrer} />
		</label>
		<label class="staerke-feld">
			<span>Mannschaften</span>
			<input type="number" min="0" max={MAX_JE_ROLLE} bind:value={eingabe.mannschaften} />
		</label>
		<div class="staerke-feld staerke-summe">
			<span>Gesamt</span>
			<output>{summe}</output>
		</div>
	</div>
	<button class="btn-primary" onclick={melden} disabled={laeuft}>{knopf}</button>
	{#if quittung}<p class="hint hint-active">{quittungstext}</p>{/if}
</div>

<style>
	.staerke-melden { margin-top: .6rem; padding-top: .6rem; border-top: 1px solid var(--border); }
	.sub-label { font-size: var(--text-xs); color: var(--text-muted); }
	.staerke-felder { display: flex; gap: .4rem; margin: .35rem 0 .5rem; }
	.staerke-feld { display: flex; flex-direction: column; gap: .15rem; flex: 1; min-width: 0; font-size: .7rem; }
	.staerke-feld input { width: 100%; padding: .3rem; text-align: center; font-variant-numeric: tabular-nums; }
	.staerke-summe output { display: block; padding: .3rem; text-align: center; font-weight: 700; font-variant-numeric: tabular-nums; }
	.btn-primary { width: 100%; padding: .5rem 1rem; background: var(--color-primary); color: white; border: none; border-radius: 6px; font-weight: 600; cursor: pointer; font-size: var(--text-sm); }
	.btn-primary:disabled { opacity: .5; cursor: not-allowed; }
	.btn-primary:hover:not(:disabled) { background: var(--color-primary-hover); }
	.hint { font-size: var(--text-xs); color: var(--text-muted); font-style: italic; margin: .35rem 0 0; line-height: 1.4; }
	.hint.hint-active { color: #f1c40f; font-style: normal; }
</style>
