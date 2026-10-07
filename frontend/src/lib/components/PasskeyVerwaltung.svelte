<script lang="ts">
	/**
	 * Die eigenen Passkeys: auflisten, hinzufügen, entfernen.
	 *
	 * Steht im Konto-Bereich der Planung und im Adminportal — dieselbe
	 * Komponente, weil es dasselbe Konto ist. Die Sitzung ergibt sich aus der
	 * Adresse (`$lib/api/client`), hier muss dafür nichts übergeben werden.
	 */
	import { onMount } from 'svelte';
	import { passkeyApi, type PasskeyInfo } from '$lib/api';
	import { istAbbruch, passkeyErstellen, passkeysVerfuegbar } from '$lib/passkey';

	let verfuegbar = $state(false);
	let liste = $state<PasskeyInfo[]>([]);
	let geladen = $state(false);
	let formOffen = $state(false);
	let passwort = $state('');
	let name = $state('');
	let arbeitet = $state(false);
	let fehler = $state('');
	let erfolg = $state('');

	async function laden() {
		try {
			liste = await passkeyApi.list();
		} catch (e) {
			fehler = e instanceof Error ? e.message : 'Passkeys konnten nicht geladen werden';
		} finally {
			geladen = true;
		}
	}

	onMount(() => {
		verfuegbar = passkeysVerfuegbar();
		laden();
	});

	function datum(iso: string | null): string {
		if (!iso) return 'noch nie';
		return new Date(iso).toLocaleDateString('de-DE', { day: '2-digit', month: '2-digit', year: 'numeric' });
	}

	async function hinzufuegen() {
		if (!passwort) return;
		arbeitet = true;
		fehler = '';
		erfolg = '';
		try {
			const { challenge_id, options } = await passkeyApi.registerOptions(passwort);
			const credential = await passkeyErstellen(options);
			const neu = await passkeyApi.register(challenge_id, credential, name.trim() || undefined);
			liste = [...liste, neu];
			formOffen = false;
			passwort = '';
			name = '';
			erfolg = `Passkey „${neu.name}" eingerichtet. Du kannst dich ab jetzt damit anmelden.`;
			setTimeout(() => { erfolg = ''; }, 5000);
		} catch (e) {
			if (istAbbruch(e)) {
				fehler = 'Abgebrochen — es wurde kein Passkey angelegt.';
			} else if (e instanceof DOMException && e.name === 'InvalidStateError') {
				fehler = 'Auf diesem Gerät ist schon ein Passkey für dein Konto eingerichtet.';
			} else {
				fehler = e instanceof Error ? e.message : 'Passkey konnte nicht eingerichtet werden';
			}
		} finally {
			arbeitet = false;
		}
	}

	async function entfernen(p: PasskeyInfo) {
		if (!confirm(`Passkey „${p.name}" entfernen?\n\nAuf dem Gerät bleibt er gespeichert, anmelden kann man sich damit aber nicht mehr.`)) return;
		arbeitet = true;
		fehler = '';
		try {
			await passkeyApi.remove(p.id);
			liste = liste.filter((x) => x.id !== p.id);
		} catch (e) {
			fehler = e instanceof Error ? e.message : 'Passkey konnte nicht entfernt werden';
		} finally {
			arbeitet = false;
		}
	}
</script>

<div class="passkeys" data-testid="passkey-verwaltung">
	<p class="hint">
		Mit einem Passkey meldest du dich per Fingerabdruck, Gesichtserkennung oder Geräte-PIN an —
		ohne Passwort und ohne Code aus der Authenticator-App.
	</p>

	{#if fehler}
		<p class="fehler" role="alert">{fehler}</p>
	{/if}
	{#if erfolg}
		<p class="erfolg">{erfolg}</p>
	{/if}

	{#if geladen && liste.length > 0}
		<ul class="liste">
			{#each liste as p (p.id)}
				<li>
					<div class="info">
						<span class="name">{p.name}</span>
						<span class="meta">
							{p.backed_up ? 'synchronisiert' : 'an ein Gerät gebunden'} ·
							angelegt {datum(p.created_at)} · zuletzt benutzt {datum(p.last_used_at)}
						</span>
					</div>
					<button class="knopf klein gefahr" onclick={() => entfernen(p)} disabled={arbeitet}>Entfernen</button>
				</li>
			{/each}
		</ul>
	{:else if geladen}
		<p class="leer">Noch kein Passkey eingerichtet.</p>
	{/if}

	{#if !verfuegbar}
		<p class="hint">Dieser Browser unterstützt keine Passkeys.</p>
	{:else if !formOffen}
		<button class="knopf" onclick={() => { formOffen = true; fehler = ''; }} disabled={arbeitet}>
			Passkey hinzufügen
		</button>
	{:else}
		<form class="formular" onsubmit={(e) => { e.preventDefault(); hinzufuegen(); }}>
			<label>
				<span>Aktuelles Passwort</span>
				<input type="password" autocomplete="current-password" bind:value={passwort} required />
			</label>
			<label>
				<span>Name (optional)</span>
				<input type="text" maxlength="100" placeholder="z. B. Diensthandy" bind:value={name} />
			</label>
			<div class="zeile">
				<button type="submit" class="knopf" disabled={arbeitet || !passwort}>
					{arbeitet ? 'Warte auf Gerät…' : 'Weiter'}
				</button>
				<button type="button" class="knopf klein" onclick={() => { formOffen = false; passwort = ''; }} disabled={arbeitet}>
					Abbrechen
				</button>
			</div>
		</form>
	{/if}
</div>

<style>
	.passkeys { display: flex; flex-direction: column; gap: .6rem; }
	.hint, .leer { margin: 0; font-size: var(--text-sm); color: var(--text-2); line-height: 1.4; }
	.fehler, .erfolg {
		margin: 0;
		padding: .45rem .6rem;
		border-radius: 6px;
		font-size: var(--text-sm);
	}
	.fehler { background: rgba(226, 61, 40, .12); color: var(--color-primary); }
	.erfolg { background: rgba(34, 160, 90, .12); color: var(--text-1); }
	.liste { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: .4rem; }
	.liste li {
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: .6rem;
		padding: .5rem .6rem;
		border: 1px solid var(--border);
		border-radius: 6px;
		background: var(--surface-2);
	}
	.info { display: flex; flex-direction: column; min-width: 0; }
	.name { font-weight: 600; color: var(--text-1); overflow-wrap: anywhere; }
	.meta { font-size: var(--text-xs); color: var(--text-muted); }
	.formular { display: flex; flex-direction: column; gap: .5rem; }
	.formular label { display: flex; flex-direction: column; gap: .2rem; font-size: var(--text-sm); color: var(--text-2); }
	.formular input {
		padding: .4rem .6rem;
		border: 1px solid var(--border);
		border-radius: 6px;
		background: var(--surface-2);
		color: var(--text-1);
		font-size: var(--text-base);
	}
	.formular input:focus { outline: none; border-color: var(--color-primary); }
	.zeile { display: flex; gap: .4rem; flex-wrap: wrap; }
	.knopf {
		align-self: flex-start;
		padding: .45rem .9rem;
		border: none;
		border-radius: 6px;
		background: var(--color-primary);
		color: #fff;
		font-weight: 600;
		font-size: var(--text-sm);
		cursor: pointer;
	}
	.knopf:hover:not(:disabled) { background: var(--color-primary-hover); }
	.knopf:disabled { opacity: .6; cursor: not-allowed; }
	.knopf.klein {
		background: transparent;
		color: var(--text-2);
		border: 1px solid var(--border);
		font-weight: 400;
		flex-shrink: 0;
	}
	.knopf.klein:hover:not(:disabled) { background: var(--surface-1); color: var(--text-1); }
	.knopf.gefahr { color: var(--color-primary); border-color: var(--color-primary); }
</style>
