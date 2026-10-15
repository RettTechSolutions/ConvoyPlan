<script lang="ts">
	/**
	 * Abschnitt „Fotos von unterwegs" in einer Aktionsseiten-Karte (Plan
	 * 2026-10-13, § 8.4): welche Telegram-Gruppe zu welchem Konvoi gehört und
	 * wer freigeben darf. Gearbeitet wird in Telegram; hier wird verbunden.
	 *
	 * Codes stehen nur bis zu ihrem Ablauf da und verschwinden dann von selbst
	 * — ein abgelaufener Code auf dem Bildschirm schickte jemanden mit einem
	 * Befehl in die Gruppe, auf den der Bot nur noch „unbekannt" antwortet.
	 *
	 * Die Beiträge stehen hier als Übersicht und Notnagel: dieselben Aktionen
	 * wie die Knöpfe in Telegram, und die Karte in der Gruppe zieht mit. Der
	 * Zähler steht auch zugeklappt da — wartende Beiträge dürfen nicht hinter
	 * einem geschlossenen Abschnitt verschwinden.
	 */
	import { onDestroy, onMount } from 'svelte';
	import {
		aktionsseitenTelegramApi,
		type Aktionsseite,
		type AktionsseiteBeitrag,
		type AktionsseiteTelegram,
		type BeitragAenderung,
		type TelegramCode
	} from '$lib/api';

	const DIENSTNAME: Record<string, string> = {
		instagram: 'Instagram',
		youtube: 'YouTube',
		facebook: 'Facebook',
		tiktok: 'TikTok'
	};

	let { seite, botBereit }: { seite: Aktionsseite; botBereit: boolean } = $props();

	let offen = $state(false);
	let daten = $state<AktionsseiteTelegram | null>(null);
	let fehler = $state('');
	let codes = $state<Record<string, TelegramCode>>({});
	let presseCode = $state<TelegramCode | null>(null);
	let jetzt = $state(Date.now());
	let beitraege = $state<AktionsseiteBeitrag[]>([]);
	let filter = $state<'alle' | AktionsseiteBeitrag['status']>('alle');
	let textFuer = $state<string | null>(null);
	let textEntwurf = $state('');
	let terminFuer = $state<string | null>(null);
	let terminEntwurf = $state('');

	const STATUS_TEXT: Record<AktionsseiteBeitrag['status'], string> = {
		wartet: 'wartet auf Presse',
		freigegeben: 'in der Warteschlange',
		abgelehnt: 'abgelehnt',
		zurueckgezogen: 'zurückgezogen'
	};

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
			[daten, beitraege] = await Promise.all([
				aktionsseitenTelegramApi.seite(seite.id),
				aktionsseitenTelegramApi.beitraege(seite.id)
			]);
		} catch (e) {
			fehler = e instanceof Error ? e.message : 'Laden fehlgeschlagen';
		}
	}

	onMount(laden);

	function umschalten(e: Event) {
		offen = (e.currentTarget as HTMLDetailsElement).open;
	}

	async function aendern(b: AktionsseiteBeitrag, aenderung: BeitragAenderung) {
		fehler = '';
		try {
			const neu = await aktionsseitenTelegramApi.beitragAendern(seite.id, b.id, aenderung);
			beitraege = beitraege.map((x) => (x.id === b.id ? neu : x));
			textFuer = null;
			terminFuer = null;
		} catch (e) {
			fehler = e instanceof Error ? e.message : 'Ändern fehlgeschlagen';
		}
	}

	function textBearbeiten(b: AktionsseiteBeitrag) {
		textFuer = b.id;
		textEntwurf = b.text_public ?? '';
	}

	/** `datetime-local` kennt keine Zeitzone — der Browser rechnet in seiner. */
	function terminSpeichern(b: AktionsseiteBeitrag) {
		const t = new Date(terminEntwurf);
		if (Number.isNaN(t.getTime())) return;
		aendern(b, { not_before: t.toISOString() });
	}

	/**
	 * Vorschaubilder holt der API-Client: Ein `<img src>` mit der Pfadadresse
	 * schickte nur das Cookie, nicht `X-Org-Slug`, und das Backend wiese ab.
	 */
	function geschuetzt(img: HTMLImageElement, photoId: string) {
		let url: string | null = null;
		let aktiv = true;
		async function laden(id: string) {
			try {
				const neu = await aktionsseitenTelegramApi.bild(seite.id, id, 'klein');
				if (!aktiv) return URL.revokeObjectURL(neu);
				if (url) URL.revokeObjectURL(url);
				url = neu;
				img.src = neu;
			} catch {
				img.classList.add('fehlt');
			}
		}
		laden(photoId);
		return {
			update: laden,
			destroy() {
				aktiv = false;
				if (url) URL.revokeObjectURL(url);
			}
		};
	}

	/** Das Fenster gleich öffnen — nach dem Laden ließe ein Popup-Blocker es nicht mehr zu. */
	async function grossOeffnen(photoId: string) {
		const fenster = window.open('', '_blank');
		try {
			const url = await aktionsseitenTelegramApi.bild(seite.id, photoId, 'gross');
			if (fenster) fenster.location.href = url;
			else window.location.href = url;
		} catch (e) {
			fenster?.close();
			fehler = e instanceof Error ? e.message : 'Bild nicht geladen';
		}
	}

	function konvoiName(id: string): string {
		return seite.convoys.find((k) => k.convoy_id === id)?.display_name ?? '?';
	}

	function zeit(iso: string): string {
		return new Date(iso).toLocaleString('de-DE', { day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit' });
	}

	const zaehler = $derived({
		wartet: beitraege.filter((b) => b.status === 'wartet').length,
		schlange: beitraege.filter((b) => b.status === 'freigegeben' && !b.public_since).length,
		oeffentlich: beitraege.filter((b) => b.status === 'freigegeben' && b.public_since).length
	});
	const gezeigt = $derived(filter === 'alle' ? beitraege : beitraege.filter((b) => b.status === filter));

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
		{#if daten}
			<span class="zaehler" data-testid="beitrag-zaehler">
				· <span class:auffaellig={zaehler.wartet > 0}>{zaehler.wartet} warten</span>
				· {zaehler.schlange} in der Warteschlange · {zaehler.oeffentlich} öffentlich
			</span>
		{/if}
	</summary>
	{#if zusammenfassung && offen}<p class="hint">{zusammenfassung}</p>{/if}

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
		<h4>Beiträge</h4>
		<label class="filter">
			Zeigen
			<select bind:value={filter}>
				<option value="alle">alle</option>
				<option value="wartet">wartend</option>
				<option value="freigegeben">freigegeben</option>
				<option value="abgelehnt">abgelehnt</option>
				<option value="zurueckgezogen">zurückgezogen</option>
			</select>
		</label>
		<ul class="beitraege">
			{#each gezeigt as b (b.id)}
				<li data-testid="beitrag" data-status={b.status}>
					{#if b.link_url}
						<!-- Am Link ist das Bild die Vorschau des Dienstes, die mit hinausgeht. -->
						<a
							class="vorschau link"
							class:mit-bild={b.photos[0]}
							href={b.link_url}
							target="_blank"
							rel="noopener noreferrer nofollow"
							data-testid="beitrag-link"
							title={b.link_url}
						>
							{#if b.photos[0]}
								<img use:geschuetzt={b.photos[0].id} alt="Vorschaubild von {DIENSTNAME[b.link_dienst ?? ''] ?? 'Link'}" />
							{:else}
								🔗
							{/if}
							<span>{DIENSTNAME[b.link_dienst ?? ''] ?? 'Link'}</span>
						</a>
					{:else if b.photos[0]}
						<button
							type="button"
							class="vorschau"
							title="Groß ansehen"
							onclick={() => grossOeffnen(b.photos[0].id)}
						>
							<img
								use:geschuetzt={b.photos[0].id}
								alt={b.text_public ?? `Foto von ${konvoiName(b.convoy_id)}`}
							/>
							{#if b.photos.length > 1}<span class="anzahl">{b.photos.length}</span>{/if}
						</button>
					{/if}
					<div class="inhalt">
						<p class="kopf">
							<strong>{konvoiName(b.convoy_id)}</strong> · {zeit(b.taken_at)}
							{#if b.sender_name}<span class="hint">· von {b.sender_name}</span>{/if}
							<span class="status {b.status}">
								{b.status === 'freigegeben' && b.public_since ? `öffentlich seit ${zeit(b.public_since)}` : STATUS_TEXT[b.status]}
							</span>
						</p>
						{#if textFuer === b.id}
							<form class="text-form" onsubmit={(e) => { e.preventDefault(); aendern(b, { text_public: textEntwurf.trim() || null }); }}>
								<textarea bind:value={textEntwurf} maxlength="500" rows="2" aria-label="Öffentlicher Text"></textarea>
								<span class="knoepfe">
									<button class="btn-small" type="submit">Text speichern</button>
									<button class="btn-small" type="button" onclick={() => (textFuer = null)}>Abbrechen</button>
								</span>
							</form>
						{:else}
							<p class="text">{b.text_public ? `„${b.text_public}"` : '(ohne Text)'}</p>
							{#if b.text_raw && b.text_raw !== b.text_public}
								<p class="hint">in Telegram: „{b.text_raw}"</p>
							{/if}
						{/if}
						{#if b.not_before && !b.public_since}
							<p class="hint" data-testid="termin">⏰ frühestens {zeit(b.not_before)} (Termin der Presse)</p>
						{/if}
						{#if terminFuer === b.id}
							<form class="text-form" onsubmit={(e) => { e.preventDefault(); terminSpeichern(b); }}>
								<input type="datetime-local" bind:value={terminEntwurf} aria-label="Erst ab" required />
								<span class="knoepfe">
									<button class="btn-small" type="submit">Termin speichern</button>
									{#if b.not_before}
										<button class="btn-small" type="button" onclick={() => aendern(b, { not_before: null })}>Termin entfernen</button>
									{/if}
									<button class="btn-small" type="button" onclick={() => (terminFuer = null)}>Abbrechen</button>
								</span>
								<span class="hint">Später, nie früher: eine Zeit vor der Verzögerung gilt nicht.</span>
							</form>
						{/if}
						<span class="knoepfe">
							{#if b.status === 'wartet'}
								<button class="btn-small" onclick={() => aendern(b, { aktion: 'frei' })}>Freigeben</button>
								<button class="btn-small" onclick={() => textBearbeiten(b)}>Text ändern</button>
								<button class="btn-small" onclick={() => { terminFuer = b.id; terminEntwurf = ''; }}>Erst ab …</button>
								<button class="btn-small" onclick={() => aendern(b, { aktion: 'ablehnen' })}>Ablehnen</button>
							{:else if b.status === 'freigegeben'}
								<button class="btn-small" onclick={() => textBearbeiten(b)}>Text ändern</button>
								{#if !b.public_since}
									<button class="btn-small" onclick={() => { terminFuer = b.id; terminEntwurf = ''; }}>Erst ab …</button>
								{/if}
								<button class="btn-small" onclick={() => aendern(b, { aktion: 'zurueck' })}>Zurückziehen</button>
							{:else}
								<button class="btn-small" onclick={() => aendern(b, { aktion: 'frei' })}>Doch freigeben</button>
							{/if}
						</span>
					</div>
				</li>
			{:else}
				<li class="hint">Keine Beiträge{filter !== 'alle' ? ' mit diesem Status' : ''}.</li>
			{/each}
		</ul>
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
	.zaehler { color: var(--text-muted); font-size: var(--text-sm); }
	.auffaellig { color: #b26a00; font-weight: 700; }
	.filter { display: inline-flex; align-items: center; gap: .4rem; font-size: var(--text-sm); color: var(--text-2); }
	.filter select { padding: .2rem .4rem; border: 1px solid var(--border); border-radius: 4px; background: var(--surface-2); color: var(--text-1); }
	.beitraege { list-style: none; margin: .5rem 0; padding: 0; }
	.beitraege li { display: flex; gap: .75rem; padding: .5rem 0; border-top: 1px solid var(--border); }
	.beitraege li:first-child { border-top: none; }
	.vorschau { position: relative; flex: 0 0 auto; padding: 0; border: 0; background: none; cursor: pointer; }
	.vorschau img:not([src]), .vorschau :global(img.fehlt) { visibility: hidden; }
	.vorschau.link { width: 4.5rem; height: 4.5rem; box-sizing: border-box; display: flex; flex-direction: column; align-items: center; justify-content: center; gap: .1rem; border-radius: 4px; border: 1px solid var(--border); background: var(--surface-2); font-size: 1.3rem; text-decoration: none; color: var(--text-1); }
	.vorschau.link span { font-size: var(--text-xs); }
	.vorschau.link.mit-bild { padding: 0; overflow: hidden; border: 0; }
	.vorschau.link.mit-bild span { position: absolute; left: 0; right: 0; bottom: 0; padding: .05rem 0; text-align: center; background: rgba(0, 0, 0, .6); color: #fff; border-radius: 0 0 4px 4px; }
	.vorschau img { width: 4.5rem; height: 4.5rem; object-fit: cover; border-radius: 4px; border: 1px solid var(--border); background: var(--surface-2); display: block; }
	.anzahl { position: absolute; top: -.35rem; right: -.35rem; background: var(--color-primary); color: #fff; font-size: var(--text-xs); font-weight: 700; border-radius: 999px; padding: 0 .35rem; }
	.inhalt { flex: 1 1 auto; min-width: 0; display: flex; flex-direction: column; gap: .2rem; }
	.kopf, .text { margin: 0; overflow-wrap: anywhere; }
	.status { margin-left: .25rem; font-size: var(--text-xs); padding: .05rem .4rem; border-radius: 999px; border: 1px solid var(--border); }
	.status.wartet { border-color: #d4a017; color: #b26a00; }
	.status.freigegeben { border-color: #2e7d32; color: #2e7d32; }
	.text-form { display: flex; flex-direction: column; gap: .3rem; }
	.text-form input { padding: .3rem .5rem; border: 1px solid var(--border); border-radius: 6px; background: var(--surface-2); color: var(--text-1); font: inherit; width: fit-content; }
	.text-form textarea { padding: .4rem .5rem; border: 1px solid var(--border); border-radius: 6px; background: var(--surface-2); color: var(--text-1); font: inherit; }
	.knoepfe { display: flex; gap: .3rem; flex-wrap: wrap; }
</style>
