<!--
  Die Eingabe des Füllstands von Tank bzw. Akku — dieselbe im Fahrer-Link, wo
  die Besatzung selbst meldet, und in der Tracking-Ansicht, wo die Führung
  eine über Funk durchgegebene Meldung nachträgt. Gemeinsame Komponente aus
  demselben Grund wie `StaerkeForm`: Grenzen und Rundung gelten an beiden
  Stellen, und zwar gleich.

  Die Schnellwahl folgt der Tankanzeige im Fahrzeug (Reserve, ¼, ½, ¾, voll),
  weil dort niemand Prozent abliest. Sie füllt nur das Feld — gemeldet wird
  erst auf Knopfdruck, wie bei der Stärke: ein verrutschter Finger an der
  Handschuhkante soll keine Meldung sein.

  Gemeldet wird hier nichts. Die Zahl geht an `onMelden`, und was damit
  geschieht, weiß der Aufrufer: der Fahrer-Link schickt sie über seinen
  WebSocket, die Tracking-Ansicht über `PATCH …/fuellstand`.
-->
<script lang="ts">
	import { untrack } from 'svelte';
	import { MAX_PROZENT, MIN_PROZENT, SCHNELLWAHL, klemmProzent } from '$lib/tracking/fuellstand';

	let {
		titel = 'Füllstand melden (Tank/Akku)',
		knopf = '⛽ Füllstand melden',
		vorgabe = null,
		quittungstext = 'Füllstand gemeldet',
		testid = 'fuellstand-form',
		onMelden,
	}: {
		titel?: string;
		knopf?: string;
		/**
		 * Ausgangsstand des Feldes — eine **bestehende Meldung**, die korrigiert
		 * wird, sonst leer. Ausdrücklich nicht der eingetragene Stand aus der
		 * Planung: der ist keine Meldung, und vorausgefüllt würde er bestätigt
		 * statt abgelesen.
		 */
		vorgabe?: number | null;
		quittungstext?: string;
		testid?: string;
		/**
		 * Nimmt den geprüften Füllstand in Prozent entgegen. Ein `false` (oder
		 * eine Ausnahme) heißt „nicht zugestellt" — dann bleibt die Quittung aus.
		 */
		onMelden: (prozent: number) => boolean | void | Promise<boolean | void>;
	} = $props();

	// `untrack` wie in `StaerkeForm`: gemeint ist genau der Anfangswert.
	// Leer beginnt das Feld mit `null`, nicht mit 0 — 0 % hieße „leer gefahren".
	let eingabe = $state<number | null>(untrack(() => vorgabe ?? null));
	let quittung = $state(false);
	let laeuft = $state(false);
	let timer: ReturnType<typeof setTimeout> | null = null;

	const wert = $derived(klemmProzent(eingabe));

	async function melden() {
		if (laeuft || wert == null) return;
		laeuft = true;
		try {
			const ergebnis = await onMelden(wert);
			if (ergebnis === false) return;
			eingabe = wert;
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

<div class="fuellstand-melden" data-testid={testid}>
	<div class="sub-label">{titel}</div>
	<div class="schnellwahl" role="group" aria-label="Stellung der Tankanzeige">
		{#each SCHNELLWAHL as s}
			<button
				type="button"
				class="schnell"
				class:gewaehlt={wert === s.prozent}
				aria-pressed={wert === s.prozent}
				title="{s.label} = {s.prozent} %"
				onclick={() => (eingabe = s.prozent)}
			>{s.label}</button>
		{/each}
	</div>
	<label class="prozent-feld">
		<span>Füllstand in %</span>
		<input
			type="number"
			inputmode="numeric"
			min={MIN_PROZENT}
			max={MAX_PROZENT}
			step="1"
			placeholder="0–100"
			bind:value={eingabe}
		/>
	</label>
	<button class="btn-primary" onclick={melden} disabled={laeuft || wert == null}>{knopf}</button>
	{#if quittung}<p class="hint hint-active">{quittungstext}</p>{/if}
</div>

<style>
	.fuellstand-melden { margin-top: .6rem; padding-top: .6rem; border-top: 1px solid var(--border); }
	.sub-label { font-size: var(--text-xs); color: var(--text-muted); }
	/* Große Flächen: gedrückt wird im Fahrzeug, oft mit Handschuh. */
	.schnellwahl { display: flex; gap: .35rem; margin: .35rem 0 .45rem; }
	.schnell {
		flex: 1 1 0; min-width: 0; min-height: 44px; padding: .35rem .2rem;
		background: var(--surface-2); color: var(--text-1); border: 2px solid var(--border);
		border-radius: 8px; cursor: pointer; font-weight: 700; font-size: var(--text-sm);
		font-family: inherit;
	}
	.schnell:hover { border-color: var(--color-primary); }
	.schnell.gewaehlt { border-color: var(--color-primary); box-shadow: inset 0 0 0 1px var(--color-primary); }
	.prozent-feld { display: flex; align-items: center; gap: .5rem; margin-bottom: .5rem; font-size: .75rem; }
	.prozent-feld span { flex: 0 0 auto; color: var(--text-2); }
	.prozent-feld input { flex: 1; min-width: 0; min-height: 40px; padding: .3rem; text-align: center; font-variant-numeric: tabular-nums; font-size: var(--text-sm); }
	.btn-primary { width: 100%; min-height: 44px; padding: .5rem 1rem; background: var(--color-primary); color: white; border: none; border-radius: 6px; font-weight: 600; cursor: pointer; font-size: var(--text-sm); }
	.btn-primary:disabled { opacity: .5; cursor: not-allowed; }
	.btn-primary:hover:not(:disabled) { background: var(--color-primary-hover); }
	.hint { font-size: var(--text-xs); color: var(--text-muted); font-style: italic; margin: .35rem 0 0; line-height: 1.4; }
	.hint.hint-active { color: #f1c40f; font-style: normal; }
</style>
