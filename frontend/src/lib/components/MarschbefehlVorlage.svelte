<script lang="ts">
	/**
	 * Word-Vorlage für den Marschbefehl im Org-Admin: Beispiel herunterladen,
	 * eigene hochladen, wieder entfernen.
	 *
	 * Geprüft wird beim Hochladen im Backend (`services/marschbefehl_vorlage.py`):
	 * Tippfehler in Feldnamen, kaputte Platzhalter, Makros. Die Meldung von dort
	 * steht hier unverändert — sie nennt das Feld, und genau das braucht, wer die
	 * Vorlage in Word korrigiert. Die Feldübersicht kommt aus derselben Quelle wie
	 * die in der Beispieldatei.
	 */
	import { klappbar } from '$lib/klappbar/klappbar';
	import { onMount } from 'svelte';
	import { marschbefehlVorlageApi, type MarschbefehlVorlageStatus, type VorlageFelder } from '$lib/api';

	let status = $state<MarschbefehlVorlageStatus | null>(null);
	let felder = $state<VorlageFelder | null>(null);
	let fehler = $state('');
	let erfolg = $state('');
	let laeuft = $state(false);
	let dateiFeld = $state<HTMLInputElement | null>(null);

	function meldung(e: unknown, ersatz: string): string {
		if (e && typeof e === 'object' && 'detail' in e && typeof e.detail === 'string') return e.detail;
		return e instanceof Error && e.message ? e.message : ersatz;
	}

	onMount(async () => {
		try {
			[status, felder] = await Promise.all([marschbefehlVorlageApi.status(), marschbefehlVorlageApi.felder()]);
		} catch (e) {
			fehler = meldung(e, 'Vorlage konnte nicht geladen werden');
		}
	});

	async function beispiel() {
		fehler = '';
		try {
			await marschbefehlVorlageApi.beispiel();
		} catch (e) {
			fehler = meldung(e, 'Download fehlgeschlagen');
		}
	}

	async function eigene() {
		if (!status?.dateiname) return;
		fehler = '';
		try {
			await marschbefehlVorlageApi.eigene(status.dateiname);
		} catch (e) {
			fehler = meldung(e, 'Download fehlgeschlagen');
		}
	}

	async function hochladen(ev: Event) {
		const input = ev.currentTarget as HTMLInputElement;
		const datei = input.files?.[0];
		if (!datei) return;
		fehler = '';
		erfolg = '';
		laeuft = true;
		try {
			status = await marschbefehlVorlageApi.hochladen(datei);
			erfolg = 'Vorlage geprüft und gespeichert. Der Word-Export nutzt sie ab sofort.';
		} catch (e) {
			fehler = meldung(e, 'Hochladen fehlgeschlagen');
		} finally {
			laeuft = false;
			input.value = '';
		}
	}

	async function entfernen() {
		if (!confirm('Eigene Vorlage entfernen? Der Word-Export nutzt danach wieder die Beispielvorlage.')) return;
		fehler = '';
		erfolg = '';
		try {
			status = await marschbefehlVorlageApi.entfernen();
		} catch (e) {
			fehler = meldung(e, 'Entfernen fehlgeschlagen');
		}
	}

	function datum(iso: string | null): string {
		return iso ? new Date(iso).toLocaleString('de-DE', { dateStyle: 'medium', timeStyle: 'short' }) : '';
	}
</script>

<div class="section" use:klappbar={{ id: 'org-marschbefehl', offen: true }}>
	<div class="section-header"><strong>Marschbefehl-Vorlage (Word)</strong></div>
	<p class="hint">
		Der Marschbefehl lässt sich neben dem PDF auch als Word-Dokument exportieren — aus einer
		eigenen Vorlage mit Kopf, Gliederung und Textbausteinen der Organisation. Die Beispielvorlage
		herunterladen, in Word anpassen und hier wieder hochladen. Platzhalter wie
		<code>{'{{ konvoi.name }}'}</code> füllt ConvoyPlan beim Export aus.
	</p>

	{#if fehler}
		<div class="error-bar" role="alert">{fehler} <button onclick={() => (fehler = '')} aria-label="Schließen">✕</button></div>
	{/if}
	{#if erfolg}
		<div class="success-bar">{erfolg}</div>
	{/if}

	<p class="stand" data-testid="vorlage-stand">
		{#if status === null}
			…
		{:else if status.eigene}
			Eigene Vorlage: <strong>{status.dateiname}</strong>
			<span class="leise">— hochgeladen {datum(status.hochgeladen_at)}</span>
		{:else}
			Keine eigene Vorlage — der Word-Export nutzt die Beispielvorlage.
		{/if}
	</p>

	<div class="knoepfe">
		<button class="btn-small" onclick={beispiel}>⬇ Beispielvorlage herunterladen</button>
		{#if status?.eigene}
			<button class="btn-small" onclick={eigene}>⬇ Eigene Vorlage herunterladen</button>
		{/if}
		<button class="btn-small primary" disabled={laeuft} onclick={() => dateiFeld?.click()}>
			{laeuft ? 'Wird geprüft…' : status?.eigene ? '⬆ Neue Vorlage hochladen' : '⬆ Vorlage hochladen'}
		</button>
		{#if status?.eigene}
			<button class="btn-small danger" onclick={entfernen}>Eigene Vorlage entfernen</button>
		{/if}
		<input
			bind:this={dateiFeld}
			type="file"
			accept=".docx,application/vnd.openxmlformats-officedocument.wordprocessingml.document"
			onchange={hochladen}
			hidden
			data-testid="vorlage-datei"
		/>
	</div>

	{#if felder}
		<details class="felder">
			<summary>Verfügbare Platzhalter</summary>
			<p class="hint">
				Ein Feld steht in doppelten geschweiften Klammern. Abschnitte, die nur erscheinen, wenn
				ein Feld gefüllt ist, und Tabellen mit einer Zeile je Fahrzeug oder Halt zeigt die
				Beispielvorlage mit ihren grauen Steuerzeilen.
			</p>
			{#each felder.gruppen as g (g.name)}
				<h4>{g.titel}</h4>
				<table class="feldtabelle">
					<tbody>
						{#each g.felder as f (f.name)}
							<tr><td><code>{`{{ ${g.name}.${f.name} }}`}</code></td><td>{f.beschreibung}</td></tr>
						{/each}
					</tbody>
				</table>
			{/each}
			{#each felder.listen as l (l.name)}
				<h4>Liste „{l.name}“ — {l.titel}</h4>
				<table class="feldtabelle">
					<tbody>
						{#each l.felder as f (f.name)}
							<tr><td><code>{`{{ ${l.name[0]}.${f.name} }}`}</code></td><td>{f.beschreibung}</td></tr>
						{/each}
					</tbody>
				</table>
			{/each}
		</details>
	{/if}
</div>

<style>
	.section { background: var(--surface-1); border: 1px solid var(--border); border-radius: 8px; padding: 1rem; margin-bottom: 1rem; box-shadow: var(--shadow); }
	.section-header { display: flex; justify-content: space-between; align-items: center; gap: .5rem; flex-wrap: wrap; margin-bottom: .75rem; font-size: var(--text-sm); font-weight: 500; color: var(--text-1); }
	.hint { color: var(--text-muted); font-size: var(--text-sm); margin: .25rem 0 .75rem; max-width: 48rem; }
	.stand { font-size: var(--text-sm); color: var(--text-1); margin: .5rem 0; }
	.leise { color: var(--text-muted); font-size: var(--text-xs); }
	.knoepfe { display: flex; gap: .4rem; flex-wrap: wrap; }
	.error-bar { background: var(--color-primary-hover); color: white; padding: .4rem .75rem; border-radius: 4px; margin-bottom: 1rem; display: flex; justify-content: space-between; gap: .5rem; }
	.error-bar button { background: none; border: none; color: white; cursor: pointer; }
	.success-bar { background: rgba(107,127,77,.15); border: 1px solid rgba(107,127,77,.4); color: #a8c070; padding: .4rem .75rem; border-radius: 4px; margin-bottom: 1rem; font-size: var(--text-sm); }
	.btn-small { padding: .2rem .5rem; font-size: var(--text-xs); border-radius: 3px; border: 1px solid var(--border); background: var(--surface-2); color: var(--text-2); cursor: pointer; }
	.btn-small:hover { background: var(--surface-1); }
	.btn-small:disabled { opacity: .5; cursor: not-allowed; }
	.btn-small.danger { border-color: var(--color-primary); color: var(--color-primary); }
	.btn-small.primary { background: #2563eb; color: #fff; border-color: #2563eb; }
	code { font-size: var(--text-xs); background: var(--surface-2); padding: .05rem .3rem; border-radius: 3px; }
	.felder { margin-top: 1rem; }
	.felder summary { cursor: pointer; font-size: var(--text-sm); color: var(--text-2); }
	.felder h4 { font-size: var(--text-sm); color: var(--text-1); margin: .9rem 0 .3rem; }
	.feldtabelle { border-collapse: collapse; font-size: var(--text-sm); color: var(--text-1); width: 100%; max-width: 48rem; }
	.feldtabelle td { text-align: left; padding: .25rem .5rem; border-bottom: 1px solid var(--border); vertical-align: top; }
	.feldtabelle td:first-child { white-space: nowrap; width: 1%; }
</style>
