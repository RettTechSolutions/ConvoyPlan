<script lang="ts">
	/**
	 * Der Telegram-Bot der Organisation, einmal oben im Reiter Aktionsseiten
	 * (Plan 2026-10-13, § 8.4).
	 *
	 * Den Token sieht man hier genau einmal: beim Eintippen. Nach dem Speichern
	 * wird das Feld geleert, und vom Server kommt nur `@BotName` mit Status
	 * zurück — e2e/aktionsseite-fotos.spec.ts prüft, dass er danach nirgends im
	 * DOM steht.
	 */
	import { onMount } from 'svelte';
	import { aktionsseitenTelegramApi, type TelegramBotStand } from '$lib/api';

	let { onStand }: { onStand?: (stand: TelegramBotStand) => void } = $props();

	let stand = $state<TelegramBotStand | null>(null);
	let token = $state('');
	let bearbeiten = $state(false);
	let speichern = $state(false);
	let fehler = $state('');

	const AMPEL: Record<string, { stufe: 'gruen' | 'gelb' | 'rot'; text: string }> = {
		bereit: { stufe: 'gruen', text: 'bereit — sieht Fotos in den Gruppen' },
		ungeprueft: { stufe: 'gelb', text: 'noch nicht geprüft' },
		privat: { stufe: 'gelb', text: 'sieht in Gruppen keine Fotos' },
		konflikt: { stufe: 'rot', text: 'ein anderes Programm holt für diesen Bot ab' },
		ungueltig: { stufe: 'rot', text: 'Telegram kennt den Token nicht mehr' },
		fehler: { stufe: 'rot', text: 'Telegram nicht erreichbar' }
	};

	function setzen(s: TelegramBotStand) {
		stand = s;
		onStand?.(s);
	}

	async function laden() {
		try {
			setzen(await aktionsseitenTelegramApi.bot());
		} catch (e) {
			fehler = e instanceof Error ? e.message : 'Laden fehlgeschlagen';
		}
	}

	onMount(laden);

	async function absenden(e: SubmitEvent) {
		e.preventDefault();
		speichern = true;
		fehler = '';
		try {
			setzen(await aktionsseitenTelegramApi.botSetzen(token.trim()));
			bearbeiten = false;
		} catch (err) {
			fehler = err instanceof Error ? err.message : 'Speichern fehlgeschlagen';
		} finally {
			// Weg aus dem Speicher der Seite, egal wie es ausging.
			token = '';
			speichern = false;
		}
	}

	async function entfernen() {
		if (!confirm('Bot trennen?\n\nEs kommen keine neuen Fotos mehr an. Gruppen, Presse und Beiträge bleiben.'))
			return;
		try {
			await aktionsseitenTelegramApi.botEntfernen();
			setzen({ eingerichtet: false });
		} catch (e) {
			fehler = e instanceof Error ? e.message : 'Trennen fehlgeschlagen';
		}
	}

	const ampel = $derived(stand?.status ? AMPEL[stand.status] : null);
</script>

<div class="section" data-testid="telegram-bot">
	<div class="section-header">
		<strong>Telegram-Bot für Fotos von unterwegs</strong>
		{#if stand?.eingerichtet && !bearbeiten}
			<div class="kopf-knoepfe">
				<button class="btn-small" onclick={() => (bearbeiten = true)}>Token ersetzen</button>
				<button class="btn-small danger" onclick={entfernen}>Bot trennen</button>
			</div>
		{/if}
	</div>

	{#if fehler}
		<p class="fehler" role="alert">{fehler}</p>
	{/if}

	{#if stand === null}
		<p class="hint">Lade…</p>
	{:else if stand.eingerichtet && !bearbeiten}
		<p class="zeile">
			<span class="ampel {ampel?.stufe ?? 'gelb'}" aria-hidden="true"></span>
			<strong>@{stand.bot_username}</strong> · {ampel?.text ?? stand.status}
		</p>
		{#if stand.status === 'privat'}
			<div class="warnung" data-testid="privacy-hinweis">
				Der Bot sieht in Gruppen nur Befehle, keine Fotos. Bei
				<a href="https://t.me/BotFather" target="_blank" rel="noopener noreferrer">@BotFather</a>:
				<code>/setprivacy</code> → den Bot wählen → <em>Disable</em>. Oder ihn in jeder Gruppe zum
				Admin machen.
			</div>
		{/if}
		{#if stand.last_error && stand.status !== 'bereit'}
			<p class="hint">Telegram sagt: {stand.last_error}</p>
		{/if}
	{:else}
		<p class="hint">
			Einen Bot legt man bei <a href="https://t.me/BotFather" target="_blank" rel="noopener noreferrer">@BotFather</a>
			mit <code>/newbot</code> an; der Token sieht aus wie <code>123456:ABC…</code>. Er wird verschlüsselt
			gespeichert und hier nie wieder angezeigt.
		</p>
		<form class="token-form" onsubmit={absenden} aria-label="Bot eintragen">
			<label>
				Bot-Token
				<input
					type="password"
					autocomplete="off"
					spellcheck="false"
					bind:value={token}
					placeholder="123456:ABC…"
				/>
			</label>
			<div class="knoepfe">
				<button class="btn-primary" type="submit" disabled={speichern || token.trim().length < 20}>
					{speichern ? 'Prüfe…' : 'Prüfen und speichern'}
				</button>
				{#if stand.eingerichtet}
					<button class="btn-secondary" type="button" onclick={() => ((bearbeiten = false), (token = ''))}>
						Abbrechen
					</button>
				{/if}
			</div>
		</form>
	{/if}
</div>

<style>
	.section { background: var(--surface-1); border: 1px solid var(--border); border-radius: 8px; padding: 1rem; margin-bottom: 1rem; box-shadow: var(--shadow); }
	.section-header { display: flex; justify-content: space-between; align-items: center; gap: .5rem; flex-wrap: wrap; margin-bottom: .5rem; font-size: var(--text-sm); font-weight: 500; color: var(--text-1); }
	.kopf-knoepfe, .knoepfe { display: flex; gap: .4rem; flex-wrap: wrap; }
	.knoepfe { margin-top: .5rem; }
	.hint { color: var(--text-muted); font-size: var(--text-sm); margin: .25rem 0; }
	.zeile { display: flex; align-items: center; gap: .4rem; font-size: var(--text-sm); color: var(--text-1); margin: .25rem 0; flex-wrap: wrap; }
	.ampel { width: .7rem; height: .7rem; border-radius: 50%; display: inline-block; }
	.ampel.gruen { background: #2e7d32; }
	.ampel.gelb { background: #d4a017; }
	.ampel.rot { background: var(--color-primary); }
	.warnung { background: rgba(212,160,23,.12); border: 1px solid rgba(212,160,23,.45); color: var(--text-1); padding: .4rem .6rem; border-radius: 4px; font-size: var(--text-sm); margin-top: .4rem; }
	.fehler { color: var(--color-primary); font-size: var(--text-sm); margin: .25rem 0; }
	.token-form label { display: flex; flex-direction: column; gap: .3rem; font-size: var(--text-sm); font-weight: 600; color: var(--text-2); max-width: var(--admin-field, 34rem); }
	.token-form input { padding: .5rem .75rem; border: 1px solid var(--border); border-radius: 6px; background: var(--surface-2); color: var(--text-1); font-size: var(--text-sm); font-weight: 400; font-family: monospace; }
	code { font-size: var(--text-xs); }
	.btn-small { padding: .2rem .5rem; font-size: var(--text-xs); border-radius: 3px; border: 1px solid var(--border); background: var(--surface-2); color: var(--text-2); cursor: pointer; }
	.btn-small.danger { border-color: var(--color-primary); color: var(--color-primary); }
	.btn-primary { padding: .5rem 1rem; background: var(--color-primary); color: white; border: none; border-radius: 6px; font-weight: 600; cursor: pointer; font-size: var(--text-sm); }
	.btn-primary:disabled { opacity: .5; cursor: not-allowed; }
	.btn-secondary { padding: .5rem 1rem; background: transparent; color: var(--text-2); border: 1px solid var(--border); border-radius: 6px; font-weight: 600; cursor: pointer; font-size: var(--text-sm); }
</style>
