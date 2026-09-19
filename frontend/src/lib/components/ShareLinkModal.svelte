<script lang="ts">
	import { onMount } from 'svelte';
	import QrShare from '$lib/components/QrShare.svelte';
	import {
		shareLinksApi,
		type ShareLink,
		type ShareLinkCreated,
		type ShareLinkPasswordMode,
		type ShareLinkScope,
	} from '$lib/api';

	let {
		convoyId,
		convoyName = '',
		onClose,
	}: { convoyId: string; convoyName?: string; onClose: () => void } = $props();

	let links = $state<ShareLink[]>([]);
	let loading = $state(true);
	let error = $state('');
	let busy = $state(false);

	let scope = $state<ShareLinkScope>('track');
	let passwordMode = $state<ShareLinkPasswordMode>('none');
	let passwordInput = $state('');

	let lastCreated = $state<ShareLinkCreated | null>(null);
	let copyHint = $state('');

	// QR-Code eines bereits bestehenden Links. Die Adresse steht schon in der
	// Liste (`url`); gezeichnet wird daraus im Browser.
	let qrLink = $state<ShareLink | null>(null);

	async function load() {
		loading = true;
		error = '';
		try {
			links = await shareLinksApi.list(convoyId);
		} catch (e) {
			error = (e as Error).message;
		} finally {
			loading = false;
		}
	}

	async function create() {
		busy = true;
		error = '';
		try {
			const body = {
				password_mode: passwordMode,
				password: passwordMode === 'set' ? passwordInput : null,
				scope,
			};
			const created = await shareLinksApi.create(convoyId, body);
			lastCreated = created;
			passwordInput = '';
			passwordMode = 'none';
			scope = 'track';
			await load();
		} catch (e) {
			error = (e as Error).message;
		} finally {
			busy = false;
		}
	}

	async function revoke(id: string) {
		if (!confirm('Diesen Link widerrufen? Er ist danach nicht mehr erreichbar.')) return;
		busy = true;
		try {
			await shareLinksApi.revoke(convoyId, id);
			if (lastCreated?.id === id) lastCreated = null;
			if (qrLink?.id === id) qrLink = null;
			await load();
		} catch (e) {
			error = (e as Error).message;
		} finally {
			busy = false;
		}
	}

	async function copy(text: string) {
		try {
			await navigator.clipboard.writeText(text);
			copyHint = 'Kopiert!';
			setTimeout(() => (copyHint = ''), 1500);
		} catch {
			copyHint = 'Kopieren fehlgeschlagen';
		}
	}

	function closeQr() {
		qrLink = null;
	}

	function scopeLabel(scope: string) {
		return scope === 'driver' ? '🚗 Fahrer' : '👁 Viewer';
	}

	/** Was auf dem Ausdruck unter der Überschrift steht. */
	function rollenzeile(scope: string) {
		return scope === 'driver'
			? 'Fahrer-Link: Fahrzeug wählen, Position und Status senden'
			: 'Nur ansehen: Verband live verfolgen';
	}

	/** Der Hinweis am Fuß des Ausdrucks — nie das Passwort selbst. */
	function druckhinweis(link: ShareLink) {
		return link.requires_password
			? 'Dieser Zugang ist passwortgeschützt. Das Passwort wird getrennt mitgeteilt — es steht nicht auf diesem Blatt und nicht im QR-Code.'
			: 'Dieser Zugang ist ohne Passwort erreichbar. Blatt entsprechend behandeln.';
	}

	function onKeydown(e: KeyboardEvent) {
		if (e.key === 'Escape' && qrLink) {
			e.stopPropagation();
			closeQr();
		}
	}

	function fmtDate(iso: string | null) {
		if (!iso) return '–';
		return new Date(iso).toLocaleString('de-DE');
	}

	onMount(load);
</script>

<svelte:window onkeydown={onKeydown} />

<div class="sl-backdrop" onclick={onClose} role="presentation">
	<div class="sl-modal" onclick={(e) => e.stopPropagation()} role="dialog" aria-modal="true">
		<header>
			<h2>Live-Tracking teilen</h2>
			<button class="sl-close" onclick={onClose} aria-label="Schließen">✕</button>
		</header>

		<div class="sl-body">
			{#if error}
				<p class="sl-error">{error}</p>
			{/if}

			<section class="sl-create">
				<h3>Neuen Tracking-Link erstellen</h3>
				<div class="sl-radios sl-scope">
					<label>
						<input type="radio" name="scope" value="track" bind:group={scope} />
						<span><strong>Nur ansehen</strong> – Empfänger sehen den Verband live (Viewer)</span>
					</label>
					<label>
						<input type="radio" name="scope" value="driver" bind:group={scope} />
						<span><strong>Fahrer</strong> – Empfänger können ohne Login ein Fahrzeug wählen und Position/Status senden</span>
					</label>
				</div>
				{#if scope === 'driver'}
					<p class="sl-warn">⚠ Jeder mit diesem Link kann für ein beliebiges Fahrzeug Position und Status senden. Für Fahrer-Links wird ein Passwort empfohlen.</p>
				{/if}
				<div class="sl-radios">
					<label>
						<input type="radio" name="pwmode" value="none" bind:group={passwordMode} />
						Ohne Passwort (offen erreichbar)
					</label>
					<label>
						<input type="radio" name="pwmode" value="generate" bind:group={passwordMode} />
						Passwort generieren
					</label>
					<label>
						<input type="radio" name="pwmode" value="set" bind:group={passwordMode} />
						Passwort selbst setzen
					</label>
					{#if passwordMode === 'set'}
						<input
							type="text"
							class="sl-input"
							placeholder="Passwort (min. 4 Zeichen)"
							bind:value={passwordInput}
						/>
					{/if}
				</div>
				<button class="sl-btn-primary" onclick={create} disabled={busy || (passwordMode === 'set' && passwordInput.length < 4)}>
					{busy ? 'Erstelle…' : 'Link erstellen'}
				</button>
			</section>

			{#if lastCreated}
				<section class="sl-result">
					<h3>Neuer Link bereit</h3>
					<div class="sl-result-grid">
						<QrShare
							url={lastCreated.url}
							filename="tracking-{lastCreated.slug}"
							printTitle="{convoyName || 'Konvoi'} — Live-Tracking"
							printSubtitle={rollenzeile(lastCreated.scope)}
							printNote={druckhinweis(lastCreated)}
						/>
						<div class="sl-result-info">
							<label>URL</label>
							<div class="sl-copy-row">
								<input class="sl-input" readonly value={lastCreated.url} />
								<button class="sl-btn-secondary" onclick={() => copy(lastCreated!.url)}>Kopieren</button>
							</div>
							{#if lastCreated.password_plain}
								<label>Passwort <span class="sl-hint">(wird nur jetzt angezeigt!)</span></label>
								<div class="sl-copy-row">
									<input class="sl-input sl-pw" readonly value={lastCreated.password_plain} />
									<button class="sl-btn-secondary" onclick={() => copy(lastCreated!.password_plain!)}>Kopieren</button>
								</div>
							{/if}
							{#if copyHint}
								<p class="sl-copy-hint">{copyHint}</p>
							{/if}
						</div>
					</div>
				</section>
			{/if}

			<section class="sl-list">
				<h3>Vorhandene Links</h3>
				{#if loading}
					<p class="sl-muted">Lade…</p>
				{:else if links.length === 0}
					<p class="sl-muted">Noch keine Tracking-Links angelegt.</p>
				{:else}
					<table>
						<thead>
							<tr>
								<th>Slug</th>
								<th>Typ</th>
								<th>PW</th>
								<th>Erstellt</th>
								<th>Letzter Zugriff</th>
								<th>Aufrufe</th>
								<th>Status</th>
								<th></th>
							</tr>
						</thead>
						<tbody>
							{#each links as link}
								<tr class:revoked={link.revoked}>
									<td><code>{link.slug}</code></td>
									<td>
										<span class="sl-badge" class:driver={link.scope === 'driver'}>{scopeLabel(link.scope)}</span>
									</td>
									<td>{link.requires_password ? '🔒' : '—'}</td>
									<td>{fmtDate(link.created_at)}</td>
									<td>{fmtDate(link.last_accessed_at)}</td>
									<td>{link.access_count}</td>
									<td>{link.revoked ? 'widerrufen' : 'aktiv'}</td>
									<td class="sl-actions">
										{#if !link.revoked}
											<button class="sl-btn-small" onclick={() => (qrLink = link)} title="QR-Code anzeigen">
												QR
											</button>
											<button class="sl-btn-small danger" onclick={() => revoke(link.id)} disabled={busy}>
												Widerrufen
											</button>
										{/if}
									</td>
								</tr>
							{/each}
						</tbody>
					</table>
				{/if}
			</section>
		</div>
	</div>
</div>

{#if qrLink}
	<div class="sl-backdrop sl-qr-backdrop" onclick={closeQr} role="presentation">
		<div class="sl-modal sl-qr-modal" onclick={(e) => e.stopPropagation()} role="dialog" aria-modal="true">
			<header>
				<h2>QR-Code · {qrLink.slug}</h2>
				<button class="sl-close" onclick={closeQr} aria-label="Schließen">✕</button>
			</header>
			<div class="sl-body sl-qr-body">
				<span class="sl-badge" class:driver={qrLink.scope === 'driver'}>{scopeLabel(qrLink.scope)}</span>
				<QrShare
					url={qrLink.url}
					filename="tracking-{qrLink.slug}"
					printTitle="{convoyName || 'Konvoi'} — Live-Tracking"
					printSubtitle={rollenzeile(qrLink.scope)}
					printNote={druckhinweis(qrLink)}
					size={260}
				/>
				<div class="sl-copy-row">
					<input class="sl-input" readonly value={qrLink.url} />
					<button class="sl-btn-secondary" onclick={() => copy(qrLink!.url)}>Kopieren</button>
				</div>
				{#if copyHint}
					<p class="sl-copy-hint">{copyHint}</p>
				{/if}
				{#if qrLink.requires_password}
					<p class="sl-warn">🔒 Dieser Link ist passwortgeschützt. Das Passwort wurde nur bei der Erstellung angezeigt und lässt sich nicht erneut abrufen — wer es nicht mehr hat, erstellt einen neuen Link.</p>
				{/if}
			</div>
		</div>
	</div>
{/if}

<style>
	/* `100dvh` statt `vh`: iOS Safari rechnet `vh` gegen die Anzeigefläche mit
	   eingefahrener Adressleiste — ein Dialog über die volle `vh`-Höhe endet
	   hinter der Leiste. `vh` bleibt als Rückfall für Browser ohne `dvh`. */
	.sl-backdrop {
		position: fixed; inset: 0; height: 100vh; height: 100dvh;
		background: rgba(0, 0, 0, .55); z-index: 1000;
		display: flex; align-items: flex-start; justify-content: center;
		padding: 2rem 1rem; padding-bottom: calc(2rem + env(safe-area-inset-bottom));
		overflow-y: auto; overscroll-behavior: contain;
	}
	.sl-modal {
		background: white; color: #1a1a1a; border-radius: 10px;
		width: 100%; max-width: 820px; margin: auto; display: flex; flex-direction: column;
		max-height: 100%; box-shadow: 0 12px 48px rgba(0, 0, 0, .45);
	}
	header {
		display: flex; align-items: center; gap: .75rem;
		padding: 1rem 1.25rem; border-bottom: 2px solid #0F1B24;
		background: #0F1B24; border-radius: 10px 10px 0 0; flex-shrink: 0;
	}
	header h2 { margin: 0; font-size: 1.1rem; color: white; flex: 1; }
	.sl-close { background: none; border: none; color: rgba(255, 255, 255, .55); cursor: pointer; font-size: 1.1rem; }
	.sl-close:hover { color: white; }

	.sl-body { padding: 1.25rem; overflow-y: auto; display: flex; flex-direction: column; gap: 1.25rem; }

	h3 { margin: 0 0 .5rem; font-size: .85rem; font-weight: 700; text-transform: uppercase; letter-spacing: .06em; color: #0F1B24; }

	.sl-radios { display: flex; flex-direction: column; gap: .35rem; margin-bottom: .75rem; }
	.sl-radios label { display: flex; align-items: center; gap: .5rem; font-size: .9rem; }
	.sl-scope { margin-bottom: .5rem; }
	.sl-scope label { align-items: flex-start; }
	.sl-scope input { margin-top: .2rem; }
	.sl-warn { background: #fff7ed; border: 1px solid #fdba74; color: #9a3412; border-radius: 6px; padding: .5rem .75rem; font-size: .82rem; margin: 0 0 .75rem; }
	.sl-badge { display: inline-block; padding: .1rem .4rem; border-radius: 999px; font-size: .72rem; font-weight: 600; background: #eef2f7; color: #334; white-space: nowrap; }
	.sl-badge.driver { background: #fef3c7; color: #92400e; }

	.sl-input { padding: .5rem .65rem; border-radius: 5px; border: 1.5px solid #ccc; background: white; color: #111; font-size: .9rem; font-family: inherit; width: 100%; box-sizing: border-box; }
	.sl-input:focus { outline: none; border-color: #0F1B24; }
	.sl-pw { font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-weight: 600; }

	.sl-btn-primary { padding: .55rem 1.1rem; border-radius: 5px; border: none; background: #0F1B24; color: white; cursor: pointer; font-size: .88rem; font-weight: 600; }
	.sl-btn-primary:hover:not(:disabled) { background: #1a2f42; }
	.sl-btn-primary:disabled { opacity: .5; cursor: not-allowed; }

	.sl-btn-secondary { padding: .5rem .9rem; border-radius: 5px; border: 1.5px solid #ccc; background: white; color: #333; cursor: pointer; font-size: .85rem; white-space: nowrap; }
	.sl-btn-secondary:hover { background: #f0f0f0; }

	.sl-btn-small { padding: .25rem .5rem; border-radius: 4px; border: 1px solid #ccc; background: white; color: #444; cursor: pointer; font-size: .78rem; white-space: nowrap; }
	.sl-btn-small:hover:not(:disabled) { background: #f0f0f0; }
	.sl-btn-small.danger { color: #b91c1c; border-color: #f4b4b4; }
	.sl-btn-small.danger:hover { background: #fef2f2; }

	.sl-result { border: 1px solid #d6e4ef; background: #f4f9fd; border-radius: 8px; padding: 1rem; }
	.sl-result-grid { display: flex; gap: 1rem; flex-wrap: wrap; }
	.sl-result-info { flex: 1; min-width: 240px; display: flex; flex-direction: column; gap: .4rem; }
	.sl-result-info label { font-size: .75rem; font-weight: 600; color: #555; text-transform: uppercase; letter-spacing: .05em; margin-top: .25rem; }
	.sl-hint { font-weight: 400; text-transform: none; letter-spacing: 0; color: #b45309; }
	.sl-copy-row { display: flex; gap: .4rem; }
	.sl-copy-hint { color: #16a34a; font-size: .8rem; margin: .25rem 0 0; }

	.sl-list { overflow-x: auto; }
	.sl-list table { width: 100%; border-collapse: collapse; font-size: .85rem; }
	.sl-list th, .sl-list td { padding: .4rem .5rem; border-bottom: 1px solid #eee; text-align: left; }
	.sl-list th { color: #666; font-size: .72rem; font-weight: 600; text-transform: uppercase; letter-spacing: .05em; }
	.sl-list tr.revoked { color: #999; text-decoration: line-through; }
	.sl-list code { font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: .88rem; }

	.sl-actions { display: flex; gap: .35rem; justify-content: flex-end; }
	.sl-qr-backdrop { z-index: 1010; }
	.sl-qr-modal { max-width: 420px; }
	.sl-qr-body { align-items: center; text-align: center; gap: .75rem; }
	.sl-qr-body .sl-copy-row, .sl-qr-body .sl-warn { width: 100%; }
	.sl-qr-body .sl-warn { margin: 0; text-align: left; }

	.sl-muted { color: #777; font-size: .88rem; }
	.sl-error { color: #b91c1c; background: #fef2f2; border: 1px solid #fecaca; border-radius: 6px; padding: .5rem .75rem; font-size: .85rem; margin: 0; }
</style>
