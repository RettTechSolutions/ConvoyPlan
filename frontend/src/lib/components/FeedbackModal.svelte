<script lang="ts">
	/**
	 * Melden, was nicht stimmt — oder was fehlt.
	 *
	 * Der Dialog hängt einmal im Org-Layout und wird über `feedbackStore`
	 * geöffnet. Er nimmt mit, was zur Einordnung nötig ist (Seite, Browser,
	 * Fassung, Fenstergröße) und zeigt es **ausklappbar an**, statt es still
	 * mitzuschicken: wer meldet, soll sehen können, was er abschickt.
	 *
	 * Das Bildschirmfoto ist freiwillig und der wertvollste Teil. Für die
	 * Aufnahme blendet sich der Dialog selbst aus — sonst zeigte das Bild den
	 * Dialog statt des Fehlers.
	 */
	import { onMount } from 'svelte';
	import { feedbackStore } from '$lib/stores/feedback';
	import { feedbackApi, type FeedbackKind, type FeedbackSeverity } from '$lib/api';
	import { ApiError } from '$lib/api/client';
	import {
		AufnahmeAbgebrochen,
		aufnahmeMoeglich,
		bildAusZwischenablage,
		bildschirmAufnehmen,
		bytesEinerDataUrl,
		dateiUebernehmen,
	} from '$lib/screenshot';

	let kind = $state<FeedbackKind>('bug');
	let title = $state('');
	let description = $state('');
	let severity = $state<FeedbackSeverity>('normal');
	let screenshot = $state<string | null>(null);

	let busy = $state(false);
	let error = $state('');
	let gesendet = $state(false);
	let umgebungOffen = $state(false);
	// Während der Bildschirmaufnahme: der Dialog verschwindet, bleibt aber
	// gemountet — ein Unmount verlöre den halb getippten Text.
	let versteckt = $state(false);
	let dateiFeld: HTMLInputElement | null = $state(null);
	let kannAufnehmen = $state(false);

	onMount(() => {
		kannAufnehmen = aufnahmeMoeglich();
	});

	// Beim Öffnen: Art übernehmen, alles Übrige zurücksetzen. Eine abgeschickte
	// Meldung soll beim nächsten Öffnen nicht noch einmal im Formular stehen.
	$effect(() => {
		if ($feedbackStore.offen) {
			kind = $feedbackStore.kind;
		}
	});

	const UMGEBUNG = () => ({
		page_url: typeof location !== 'undefined' ? location.href.slice(0, 500) : null,
		user_agent: typeof navigator !== 'undefined' ? navigator.userAgent.slice(0, 400) : null,
		app_version: typeof __APP_VERSION__ !== 'undefined' ? __APP_VERSION__ : null,
		viewport:
			typeof window !== 'undefined' ? `${window.innerWidth}×${window.innerHeight}` : null,
	});

	function schliessen() {
		if (busy) return;
		feedbackStore.close();
		// Verzögert zurücksetzen, damit das Formular nicht während der
		// Ausblendeanimation leer wird.
		setTimeout(() => {
			title = '';
			description = '';
			severity = 'normal';
			screenshot = null;
			error = '';
			gesendet = false;
			umgebungOffen = false;
		}, 200);
	}

	async function aufnehmen() {
		error = '';
		versteckt = true;
		try {
			// Ein Tick, damit der Browser den Dialog wirklich aus dem Bild
			// genommen hat, bevor der Freigabedialog aufgeht.
			await new Promise((r) => setTimeout(r, 150));
			screenshot = await bildschirmAufnehmen();
		} catch (e) {
			if (!(e instanceof AufnahmeAbgebrochen)) error = (e as Error).message;
		} finally {
			versteckt = false;
		}
	}

	async function dateiGewaehlt(event: Event) {
		const datei = (event.target as HTMLInputElement).files?.[0];
		if (!datei) return;
		error = '';
		try {
			screenshot = await dateiUebernehmen(datei);
		} catch (e) {
			error = (e as Error).message;
		}
	}

	async function einfuegen(event: ClipboardEvent) {
		const datei = bildAusZwischenablage(event);
		if (!datei) return;
		event.preventDefault();
		error = '';
		try {
			screenshot = await dateiUebernehmen(datei);
		} catch (e) {
			error = (e as Error).message;
		}
	}

	async function absenden() {
		error = '';
		if (title.trim().length < 3) {
			error = 'Bitte eine kurze Überschrift angeben.';
			return;
		}
		if (description.trim().length < 10) {
			error = 'Bitte beschreiben, was passiert ist — in ein, zwei Sätzen.';
			return;
		}
		busy = true;
		try {
			await feedbackApi.submit({
				kind,
				title: title.trim(),
				description: description.trim(),
				severity,
				screenshot,
				...UMGEBUNG(),
			});
			gesendet = true;
		} catch (e) {
			// Nur die Begründung des Backends anzeigen; ein Netzwerkfehler
			// bekommt einen eigenen Satz.
			error =
				e instanceof ApiError && e.detail
					? e.detail
					: 'Die Meldung ließ sich nicht abschicken. Bitte später noch einmal versuchen.';
		} finally {
			busy = false;
		}
	}

	function onKeydown(e: KeyboardEvent) {
		if (e.key === 'Escape') schliessen();
	}

	const kb = (bytes: number) => `${Math.round(bytes / 1024)} kB`;

	const PLATZHALTER: Record<FeedbackKind, string> = {
		bug: 'Was haben Sie getan, was ist passiert, was hätte passieren sollen?\n\n1. …\n2. …\n\nErwartet: …\nStattdessen: …',
		feature: 'Was fehlt Ihnen — und wobei würde es helfen? Je konkreter der Einsatzfall, desto eher lässt sich etwas daraus bauen.',
	};
</script>

<svelte:window on:keydown={onKeydown} />

{#if $feedbackStore.offen}
	<!-- svelte-ignore a11y_no_noninteractive_element_interactions -->
	<div
		class="overlay"
		class:versteckt
		role="dialog"
		aria-modal="true"
		aria-label="Rückmeldung geben"
		onpaste={einfuegen}
	>
		<button class="backdrop" onclick={schliessen} aria-label="Schließen" tabindex="-1"></button>

		<div class="dialog">
			<div class="kopf">
				<h2>{gesendet ? 'Danke!' : kind === 'bug' ? 'Fehler melden' : 'Funktion vorschlagen'}</h2>
				<button class="x" onclick={schliessen} aria-label="Schließen">✕</button>
			</div>

			{#if gesendet}
				<div class="inhalt quittung">
					<p class="gross">Die Meldung ist angekommen.</p>
					<p class="klein">
						Sie liegt jetzt im Adminportal der Instanz. Rückfragen kommen, falls nötig, an
						die Adresse Ihres Kontos.
					</p>
					<div class="fuss">
						<button class="primaer" onclick={schliessen}>Schließen</button>
					</div>
				</div>
			{:else}
				<div class="inhalt">
					<div class="art" role="radiogroup" aria-label="Art der Meldung">
						<button
							type="button"
							role="radio"
							aria-checked={kind === 'bug'}
							class:aktiv={kind === 'bug'}
							onclick={() => (kind = 'bug')}
						>
							🐞 Fehler
						</button>
						<button
							type="button"
							role="radio"
							aria-checked={kind === 'feature'}
							class:aktiv={kind === 'feature'}
							onclick={() => (kind = 'feature')}
						>
							💡 Wunsch
						</button>
					</div>

					<label class="feld">
						<span>Überschrift</span>
						<input
							type="text"
							bind:value={title}
							maxlength="200"
							placeholder={kind === 'bug'
								? 'Route wird nach dem Speichern nicht neu berechnet'
								: 'Marschbefehl als PDF zusammenfassen'}
						/>
					</label>

					<label class="feld">
						<span>Beschreibung</span>
						<textarea
							bind:value={description}
							rows="7"
							maxlength="8000"
							placeholder={PLATZHALTER[kind]}
						></textarea>
					</label>

					<label class="feld">
						<span>{kind === 'bug' ? 'Wie schwer wiegt es?' : 'Wie wichtig wäre es?'}</span>
						<select bind:value={severity}>
							<option value="niedrig">Niedrig — kosmetisch, stört kaum</option>
							<option value="normal">Normal — nervt, geht aber</option>
							<option value="hoch">Hoch — behindert die Arbeit</option>
							<option value="kritisch">Kritisch — Einsatz nicht planbar</option>
						</select>
					</label>

					<div class="feld">
						<span>Bildschirmfoto <em>(freiwillig, hilft am meisten)</em></span>
						{#if screenshot}
							<div class="vorschau">
								<img src={screenshot} alt="Aufgenommenes Bildschirmfoto" />
								<div class="vorschau-fuss">
									<span>{kb(bytesEinerDataUrl(screenshot))}</span>
									<button type="button" class="link" onclick={() => (screenshot = null)}>
										Entfernen
									</button>
								</div>
							</div>
						{:else}
							<div class="bild-knoepfe">
								{#if kannAufnehmen}
									<button type="button" onclick={aufnehmen}>📸 Bildschirm aufnehmen</button>
								{/if}
								<button type="button" onclick={() => dateiFeld?.click()}>
									📎 Datei wählen
								</button>
							</div>
							<p class="hinweis">
								{#if kannAufnehmen}
									Beim Aufnehmen fragt der Browser, was geteilt wird — der Dialog blendet
									sich dafür kurz aus. Alternativ ein Bild mit Strg+V einfügen.
								{:else}
									Ein Bild lässt sich hier mit Strg+V einfügen oder als Datei wählen
									(PNG, JPEG, WebP).
								{/if}
							</p>
						{/if}
						<input
							bind:this={dateiFeld}
							type="file"
							accept="image/png,image/jpeg,image/webp"
							onchange={dateiGewaehlt}
							hidden
						/>
					</div>

					<details class="umgebung" bind:open={umgebungOffen}>
						<summary>Was mitgeschickt wird</summary>
						<dl>
							{#each Object.entries(UMGEBUNG()) as [schluessel, wert]}
								<dt>{schluessel}</dt>
								<dd>{wert ?? '—'}</dd>
							{/each}
							<dt>Konto</dt>
							<dd>Name, E-Mail-Adresse und Organisation Ihrer Anmeldung</dd>
						</dl>
						<p class="hinweis">
							Sichtbar ist das alles nur für den Betreiber dieser Instanz — nicht für
							andere Organisationen und nicht öffentlich.
						</p>
					</details>

					{#if error}<p class="fehler">{error}</p>{/if}

					<div class="fuss">
						<button class="sekundaer" onclick={schliessen} disabled={busy}>Abbrechen</button>
						<button class="primaer" onclick={absenden} disabled={busy}>
							{busy ? 'Wird gesendet …' : 'Absenden'}
						</button>
					</div>
				</div>
			{/if}
		</div>
	</div>
{/if}

<style>
	.overlay {
		position: fixed;
		inset: 0;
		height: 100vh;
		height: 100dvh;
		z-index: 4000;
		display: flex;
		align-items: center;
		justify-content: center;
		padding: 1rem;
		padding-bottom: calc(1rem + env(safe-area-inset-bottom));
	}
	/* Während der Bildschirmaufnahme: unsichtbar und unantastbar, aber gemountet. */
	.overlay.versteckt {
		opacity: 0;
		pointer-events: none;
	}
	.backdrop {
		position: absolute;
		inset: 0;
		background: rgba(0, 0, 0, 0.5);
		border: none;
		padding: 0;
		cursor: pointer;
	}
	.dialog {
		position: relative;
		background: var(--surface-1, #fff);
		color: var(--text-1);
		border-radius: 10px;
		box-shadow: 0 18px 50px rgba(0, 0, 0, 0.3);
		width: min(620px, 100%);
		/* `dvh` statt `vh`: auf iOS endet ein Dialog über die volle `vh`-Höhe
		   hinter der Adressleiste. `vh` bleibt als Rückfall. */
		max-height: min(90vh, 900px);
		max-height: min(90dvh, 900px);
		display: flex;
		flex-direction: column;
	}
	.kopf {
		display: flex;
		align-items: center;
		justify-content: space-between;
		padding: 1rem 1.15rem;
		border-bottom: 1px solid var(--border);
	}
	.kopf h2 {
		margin: 0;
		font-size: var(--text-base);
	}
	.x {
		background: none;
		border: none;
		cursor: pointer;
		color: var(--text-muted);
		font-size: 1rem;
	}
	.inhalt {
		padding: 1.15rem;
		overflow-y: auto;
		display: flex;
		flex-direction: column;
		gap: 0.9rem;
	}
	.art {
		display: flex;
		gap: 0.5rem;
	}
	.art button {
		flex: 1;
		padding: 0.6rem;
		border: 1px solid var(--border);
		background: var(--surface-2);
		color: var(--text-2);
		border-radius: 6px;
		cursor: pointer;
		font-size: var(--text-sm);
	}
	.art button.aktiv {
		border-color: var(--color-primary);
		color: var(--color-primary);
		background: var(--surface-1);
		font-weight: 600;
	}
	.feld {
		display: flex;
		flex-direction: column;
		gap: 0.35rem;
		font-size: var(--text-sm);
	}
	.feld > span {
		color: var(--text-2);
		font-weight: 500;
	}
	.feld em {
		font-style: normal;
		font-weight: 400;
		color: var(--text-muted);
	}
	.feld input[type='text'],
	.feld textarea,
	.feld select {
		width: 100%;
		padding: 0.5rem 0.6rem;
		border: 1px solid var(--border);
		border-radius: 6px;
		background: var(--surface-1);
		color: var(--text-1);
		font: inherit;
		font-size: var(--text-sm);
	}
	.feld textarea {
		resize: vertical;
		min-height: 7rem;
	}
	.bild-knoepfe {
		display: flex;
		gap: 0.5rem;
		flex-wrap: wrap;
	}
	.bild-knoepfe button {
		padding: 0.5rem 0.75rem;
		border: 1px solid var(--border);
		background: var(--surface-2);
		color: var(--text-1);
		border-radius: 6px;
		cursor: pointer;
		font-size: var(--text-sm);
	}
	.vorschau img {
		width: 100%;
		max-height: 220px;
		object-fit: contain;
		border: 1px solid var(--border);
		border-radius: 6px;
		background: var(--surface-2);
	}
	.vorschau-fuss {
		display: flex;
		justify-content: space-between;
		align-items: center;
		font-size: var(--text-xs);
		color: var(--text-muted);
		margin-top: 0.3rem;
	}
	.link {
		background: none;
		border: none;
		color: var(--color-primary);
		cursor: pointer;
		font-size: var(--text-xs);
		padding: 0;
	}
	.hinweis {
		margin: 0.25rem 0 0;
		font-size: var(--text-xs);
		color: var(--text-muted);
		line-height: 1.45;
	}
	.umgebung {
		border: 1px solid var(--border);
		border-radius: 6px;
		padding: 0.5rem 0.7rem;
		font-size: var(--text-xs);
	}
	.umgebung summary {
		cursor: pointer;
		color: var(--text-2);
	}
	.umgebung dl {
		display: grid;
		grid-template-columns: 8rem 1fr;
		gap: 0.2rem 0.6rem;
		margin: 0.6rem 0 0;
	}
	.umgebung dt {
		color: var(--text-muted);
	}
	.umgebung dd {
		margin: 0;
		overflow-wrap: anywhere;
	}
	.fehler {
		margin: 0;
		color: var(--color-primary);
		font-size: var(--text-sm);
	}
	.fuss {
		display: flex;
		justify-content: flex-end;
		gap: 0.5rem;
		padding-top: 0.3rem;
	}
	.primaer,
	.sekundaer {
		padding: 0.55rem 1.1rem;
		border-radius: 6px;
		cursor: pointer;
		font-size: var(--text-sm);
		border: 1px solid var(--border);
	}
	.primaer {
		background: var(--color-primary);
		border-color: var(--color-primary);
		color: #fff;
		font-weight: 600;
	}
	.primaer:disabled,
	.sekundaer:disabled {
		opacity: 0.6;
		cursor: default;
	}
	.sekundaer {
		background: var(--surface-2);
		color: var(--text-1);
	}
	.quittung {
		text-align: left;
	}
	.quittung .gross {
		margin: 0;
		font-size: var(--text-base);
		font-weight: 600;
	}
	.quittung .klein {
		margin: 0.4rem 0 0;
		font-size: var(--text-sm);
		color: var(--text-2);
		line-height: 1.5;
	}
	@media (max-width: 600px) {
		.dialog {
			max-height: 100%;
			height: 100%;
			border-radius: 0;
			width: 100%;
		}
		.umgebung dl {
			grid-template-columns: 1fr;
		}
	}
</style>
