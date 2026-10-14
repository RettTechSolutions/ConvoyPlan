<script lang="ts">
	/**
	 * Abschnitt „Fotos von unterwegs" in einer Aktionsseiten-Karte (Plan
	 * 2026-10-13, § 8.4): welche Telegram-Gruppe zu welchem Konvoi gehört und
	 * wer freigeben darf. Gearbeitet wird in Telegram; hier wird verbunden.
	 *
	 * Codes stehen nur bis zu ihrem Ablauf da und verschwinden dann von selbst
	 * — ein abgelaufener Code auf dem Bildschirm schickte jemanden mit einem
	 * Befehl in die Gruppe, auf den der Bot nur noch „unbekannt" antwortet.
	 * Die Beitragsliste kommt mit Schritt 4 dazu.
	 */
	import { onDestroy } from 'svelte';
	import {
		aktionsseitenTelegramApi,
		type Aktionsseite,
		type AktionsseiteTelegram,
		type TelegramCode
	} from '$lib/api';

	let { seite, botBereit }: { seite: Aktionsseite; botBereit: boolean } = $props();

	let offen = $state(false);
	let daten = $state<AktionsseiteTelegram | null>(null);
	let fehler = $state('');
	let codes = $state<Record<string, TelegramCode>>({});
	let presseCode = $state<TelegramCode | null>(null);
	let jetzt = $state(Date.now());

	const uhr = setInterval(() => (jetzt = Date.now()), 1000);
	onDestroy(() => clearInterval(uhr));

	function gueltig(c: TelegramCode | null | undefined): c is TelegramCode {
		return !!c && new Date(c.expires_at).getTime() > jetzt;
	}

	function rest(c: TelegramCode): string {
		const s = Math.max(0, Math.round((new Date(c.expires_at).getTime() - jetzt) / 1000));
		return s >= 3600 ? `${Math.round(s / 3600)} Std.` : `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')} min`;
	}

	async function laden() {
		fehler = '';
		try {
			daten = await aktionsseitenTelegramApi.seite(seite.id);
		} catch (e) {
			fehler = e instanceof Error ? e.message : 'Laden fehlgeschlagen';
		}
	}

	function umschalten(e: Event) {
		offen = (e.currentTarget as HTMLDetailsElement).open;
		if (offen && daten === null) laden();
	}

	async function codeFuer(convoyId: string) {
		try {
			codes = { ...codes, [convoyId]: await aktionsseitenTelegramApi.verbindenCode(seite.id, convoyId) };
		} catch (e) {
			fehler = e instanceof Error ? e.message : 'Code fehlgeschlagen';
		}
	}

	async function trennen(convoyId: string, name: string) {
		if (!confirm(`Gruppe von „${name}" trennen?\n\nEs kommen keine neuen Fotos mehr an. Vorhandene Beiträge bleiben, freigegebene auch öffentlich.`))
			return;
		try {
			await aktionsseitenTelegramApi.trennen(seite.id, convoyId);
			await laden();
		} catch (e) {
			fehler = e instanceof Error ? e.message : 'Trennen fehlgeschlagen';
		}
	}

	async function neuerPresseCode() {
		try {
			presseCode = await aktionsseitenTelegramApi.presseCode(seite.id);
		} catch (e) {
			fehler = e instanceof Error ? e.message : 'Code fehlgeschlagen';
		}
	}

	async function presseEntfernen(id: number, name: string) {
		if (!confirm(`${name} aus der Presse entfernen?\n\nWirkt sofort: Die Knöpfe in Telegram gelten dann nicht mehr.`))
			return;
		try {
			await aktionsseitenTelegramApi.presseEntfernen(seite.id, id);
			await laden();
		} catch (e) {
			fehler = e instanceof Error ? e.message : 'Entfernen fehlgeschlagen';
		}
	}

	async function kopieren(text: string) {
		try {
			await navigator.clipboard.writeText(text);
		} catch {
			/* Markieren geht auch von Hand (user-select: all). */
		}
	}

	const zusammenfassung = $derived(
		daten
			? `${daten.gruppen.length} von ${seite.convoys.length} ${seite.convoys.length === 1 ? 'Konvoi' : 'Konvois'} verbunden · ${daten.presse.length} Presse`
			: ''
	);
</script>

<details class="fotos" data-testid="fotos-von-unterwegs" ontoggle={umschalten}>
	<summary>
		<strong>Fotos von unterwegs</strong>
		{#if zusammenfassung}<span class="hint"> · {zusammenfassung}</span>{/if}
	</summary>

	{#if !botBereit}
		<p class="hint gesperrt">Erst oben einen Telegram-Bot eintragen — ohne ihn kommen keine Fotos an.</p>
	{/if}
	{#if fehler}
		<p class="fehler" role="alert">{fehler}</p>
	{/if}

	{#if offen && daten}
		<h4>Gruppen</h4>
		<ul class="liste">
			{#each seite.convoys as k (k.convoy_id)}
				{@const gruppe = daten.gruppen.find((g) => g.convoy_id === k.convoy_id)}
				{@const code = codes[k.convoy_id]}
				<li data-testid="gruppe-{k.convoy_id}">
					<span><strong>{k.display_name}</strong></span>
					{#if gruppe}
						<span>→ {gruppe.thema ? 'Thema in' : 'Gruppe'} „{gruppe.chat_title ?? 'ohne Namen'}"</span>
						<button class="btn-small" onclick={() => trennen(k.convoy_id, k.display_name)}>trennen</button>
					{:else if gueltig(code)}
						<span class="code-zeile">
							In die Gruppe oder das Thema des Konvois schreiben:
							<code class="code" data-testid="verbinden-code">/verbinden {code.code}</code>
							<button class="btn-small" onclick={() => kopieren(`/verbinden ${code.code}`)}>Kopieren</button>
							<span class="hint">noch {rest(code)}</span>
							<button class="btn-small" onclick={laden}>Verbunden? Neu laden</button>
						</span>
					{:else}
						<span class="hint">nicht verbunden</span>
						<button class="btn-small" disabled={!botBereit} onclick={() => codeFuer(k.convoy_id)}>Code erzeugen</button>
					{/if}
				</li>
			{:else}
				<li class="hint">Der Seite sind noch keine Konvois zugeordnet.</li>
			{/each}
		</ul>

		<h4>Presse</h4>
		<p class="hint">Wer hier steht, gibt in Telegram frei, ändert Texte und zieht zurück.</p>
		<ul class="liste">
			{#each daten.presse as p (p.telegram_user_id)}
				<li>
					<span><strong>{p.display_name}</strong>{#if p.username} <span class="hint">@{p.username}</span>{/if}</span>
					<button class="btn-small" onclick={() => presseEntfernen(p.telegram_user_id, p.display_name)}>entfernen</button>
				</li>
			{:else}
				<li class="hint">Noch niemand.</li>
			{/each}
		</ul>
		{#if gueltig(presseCode)}
			<p class="code-zeile">
				Dem Bot <strong>privat</strong> schicken:
				<code class="code" data-testid="presse-code">/presse {presseCode.code}</code>
				<button class="btn-small" onclick={() => kopieren(`/presse ${presseCode!.code}`)}>Kopieren</button>
				<span class="hint">gilt noch {rest(presseCode)}, für mehrere Personen</span>
			</p>
		{:else}
			<button class="btn-small" disabled={!botBereit} onclick={neuerPresseCode}>Presse-Code erzeugen</button>
		{/if}
	{:else if offen}
		<p class="hint">Lade…</p>
	{/if}
</details>

<style>
	.fotos { margin-top: .75rem; border-top: 1px solid var(--border); padding-top: .5rem; font-size: var(--text-sm); color: var(--text-1); }
	summary { cursor: pointer; padding: .2rem 0; }
	h4 { margin: .75rem 0 .25rem; font-size: var(--text-sm); color: var(--text-2); }
	.liste { list-style: none; margin: .25rem 0; padding: 0; }
	.liste li { display: flex; align-items: center; gap: .5rem; padding: .25rem 0; flex-wrap: wrap; border-top: 1px solid var(--border); }
	.liste li:first-child { border-top: none; }
	.hint { color: var(--text-muted); font-size: var(--text-sm); margin: .25rem 0; }
	.gesperrt { font-style: italic; }
	.fehler { color: var(--color-primary); font-size: var(--text-sm); }
	.code-zeile { display: flex; align-items: center; gap: .4rem; flex-wrap: wrap; }
	.code { font-size: var(--text-sm); padding: .1rem .4rem; background: var(--surface-2); border: 1px solid var(--border); border-radius: 4px; user-select: all; }
	.btn-small { padding: .2rem .5rem; font-size: var(--text-xs); border-radius: 3px; border: 1px solid var(--border); background: var(--surface-2); color: var(--text-2); cursor: pointer; }
	.btn-small:disabled { opacity: .5; cursor: not-allowed; }
</style>
