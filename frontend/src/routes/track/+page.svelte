<script lang="ts">
	import { onMount } from 'svelte';
	import { goto } from '$app/navigation';
	import AppLogo from '$lib/components/AppLogo.svelte';
	import TrackingPwaHead from '$lib/components/TrackingPwaHead.svelte';
	import { pwaStore, canShowInstall } from '$lib/stores/pwa';

	const LAST_ID_KEY = 'track_last_id';

	let trackingId = $state('');
	let lastId = $state('');
	let error = $state('');
	let installing = $state(false);
	let showIOSHint = $state(false);

	// Akzeptiert sowohl eine reine Tracking-ID als auch einen kompletten
	// Tracking-Link (z. B. https://web.convoyplan.de/track/AbC123 → AbC123).
	function normalizeId(raw: string): string {
		let v = raw.trim();
		if (!v) return '';
		const marker = '/track/';
		const idx = v.indexOf(marker);
		if (idx !== -1) v = v.slice(idx + marker.length);
		// Query-/Hash-Anhänge und etwaige Slashes entfernen
		v = v.split(/[?#/]/)[0];
		return v.trim();
	}

	function open(id?: string) {
		const value = normalizeId(id ?? trackingId);
		if (!value) {
			error = 'Bitte eine Tracking-ID eingeben.';
			return;
		}
		if (!/^[A-Za-z0-9]+$/.test(value)) {
			error = 'Ungültige Tracking-ID. Erlaubt sind nur Buchstaben und Ziffern.';
			return;
		}
		try {
			localStorage.setItem(LAST_ID_KEY, value);
		} catch { /* ignore */ }
		goto(`/track/${value}`);
	}

	function onInput() {
		if (error) error = '';
	}

	async function install() {
		if ($pwaStore.isIOS) {
			showIOSHint = true;
			return;
		}
		installing = true;
		try {
			await pwaStore.install();
		} finally {
			installing = false;
		}
	}

	onMount(() => {
		pwaStore.init();
		try {
			lastId = localStorage.getItem(LAST_ID_KEY) ?? '';
		} catch { /* ignore */ }
	});
</script>

<TrackingPwaHead />

<svelte:head>
	<title>Tracking – Tracking-ID eingeben</title>
</svelte:head>

<main class="launch">
	<div class="card">
		<div class="logo">
			<AppLogo variant="main" width={160} />
		</div>

		<h1>Live-Tracking</h1>
		<p class="sub">Gib die <strong>Tracking-ID</strong> ein, die du erhalten hast, um den Marschverband live zu verfolgen.</p>

		<form onsubmit={(e) => { e.preventDefault(); open(); }}>
			<label class="field">
				<span>Tracking-ID</span>
				<input
					type="text"
					bind:value={trackingId}
					oninput={onInput}
					placeholder="z. B. AbC123Xy"
					autocomplete="off"
					autocapitalize="off"
					autocorrect="off"
					spellcheck="false"
					inputmode="text"
					aria-label="Tracking-ID"
				/>
			</label>

			{#if error}
				<p class="error" role="alert">{error}</p>
			{/if}

			<button type="submit" class="btn-primary">Tracking öffnen</button>
		</form>

		{#if lastId && lastId !== trackingId}
			<button type="button" class="btn-last" onclick={() => open(lastId)}>
				Zuletzt verwendet: <strong>{lastId}</strong>
			</button>
		{/if}

		{#if $canShowInstall && !$pwaStore.isStandalone}
			<div class="install-hint">
				<button type="button" class="btn-install" onclick={install} disabled={installing}>
					{#if installing}
						Installiere…
					{:else}
						⊕ Tracking als App installieren
					{/if}
				</button>
				<span class="install-note">Schneller Zugriff direkt vom Homescreen – die App fragt beim Öffnen die Tracking-ID ab.</span>
			</div>
		{/if}
	</div>
</main>

{#if showIOSHint}
	<!-- svelte-ignore a11y_no_static_element_interactions -->
	<div class="ios-overlay" onclick={() => (showIOSHint = false)}>
		<div class="ios-hint" onclick={(e) => e.stopPropagation()}>
			<button class="ios-close" onclick={() => (showIOSHint = false)} aria-label="Schließen">✕</button>
			<strong>Tracking auf dem iPhone / iPad installieren</strong>
			<ol>
				<li>Tippe auf das <span>⬆️</span> <strong>Teilen</strong>-Symbol in Safari</li>
				<li>Wähle <strong>„Zum Home-Bildschirm"</strong></li>
				<li>Tippe auf <strong>„Hinzufügen"</strong></li>
			</ol>
			<p class="ios-foot">Beim Öffnen der App wird die Tracking-ID abgefragt.</p>
		</div>
		<div class="ios-arrow" aria-hidden="true"></div>
	</div>
{/if}

<style>
	.launch {
		min-height: 100dvh;
		display: flex;
		align-items: center;
		justify-content: center;
		padding: 1.5rem;
		background: var(--bg, #0f1419);
	}

	.card {
		width: 100%;
		max-width: 26rem;
		background: var(--surface-1, #161f2e);
		border: 1px solid var(--border, rgba(255, 255, 255, 0.1));
		border-radius: 1rem;
		padding: 2rem 1.75rem 1.75rem;
		box-shadow: 0 12px 40px rgba(0, 0, 0, 0.35);
		text-align: center;
	}

	.logo {
		display: flex;
		justify-content: center;
		margin-bottom: 1.25rem;
	}

	h1 {
		margin: 0 0 0.5rem;
		font-size: 1.4rem;
		color: var(--text-1, #e8edf2);
	}

	.sub {
		margin: 0 0 1.5rem;
		font-size: 0.9rem;
		line-height: 1.5;
		color: var(--text-2, rgba(255, 255, 255, 0.6));
	}

	form {
		display: flex;
		flex-direction: column;
		gap: 0.85rem;
		text-align: left;
	}

	.field span {
		display: block;
		font-size: 0.8rem;
		font-weight: 600;
		margin-bottom: 0.35rem;
		color: var(--text-2, rgba(255, 255, 255, 0.6));
	}

	.field input {
		width: 100%;
		padding: 0.75rem 0.9rem;
		font-size: 1.05rem;
		border-radius: 0.6rem;
		border: 1px solid var(--border, rgba(255, 255, 255, 0.18));
		background: var(--surface-2, #1e2d3d);
		color: var(--text-1, #e8edf2);
		letter-spacing: 0.04em;
	}

	.field input:focus {
		outline: none;
		border-color: var(--color-primary, #e23d28);
	}

	.error {
		margin: -0.25rem 0 0;
		color: #f87171;
		font-size: 0.82rem;
	}

	.btn-primary {
		margin-top: 0.25rem;
		padding: 0.8rem 1rem;
		font-size: 0.95rem;
		font-weight: 600;
		border: none;
		border-radius: 0.6rem;
		background: var(--color-primary, #e23d28);
		color: #fff;
		cursor: pointer;
		transition: background 0.15s;
	}

	.btn-primary:hover { background: var(--color-primary-hover, #c23020); }

	.btn-last {
		margin-top: 1rem;
		background: none;
		border: none;
		color: var(--text-2, rgba(255, 255, 255, 0.6));
		font-size: 0.85rem;
		cursor: pointer;
		text-decoration: underline;
	}

	.btn-last strong { color: var(--text-1, #e8edf2); }

	.install-hint {
		margin-top: 1.75rem;
		padding-top: 1.25rem;
		border-top: 1px solid var(--border, rgba(255, 255, 255, 0.1));
		display: flex;
		flex-direction: column;
		gap: 0.5rem;
		align-items: center;
	}

	.btn-install {
		background: transparent;
		border: 1px solid var(--border, rgba(255, 255, 255, 0.2));
		color: var(--text-1, #e8edf2);
		border-radius: 0.6rem;
		padding: 0.55rem 1rem;
		font-size: 0.9rem;
		font-weight: 600;
		cursor: pointer;
		transition: background 0.15s, color 0.15s;
	}

	.btn-install:hover:not(:disabled) { background: var(--surface-2, #1e2d3d); }
	.btn-install:disabled { opacity: 0.6; cursor: not-allowed; }

	.install-note {
		font-size: 0.75rem;
		line-height: 1.45;
		color: var(--text-2, rgba(255, 255, 255, 0.55));
		max-width: 22rem;
	}

	.ios-overlay {
		position: fixed;
		inset: 0;
		z-index: 9001;
		background: rgba(0, 0, 0, 0.55);
		display: flex;
		align-items: flex-end;
		justify-content: center;
		padding-bottom: 4rem;
	}

	.ios-hint {
		background: var(--surface-1, #1e2d3d);
		border: 1px solid var(--border, rgba(255, 255, 255, 0.12));
		border-radius: 1rem;
		padding: 1.25rem 1.5rem 1.5rem;
		max-width: 22rem;
		width: calc(100% - 2rem);
		color: var(--text-1, #e8edf2);
		position: relative;
	}

	.ios-hint strong { display: block; font-size: 1rem; margin-bottom: 0.75rem; }
	.ios-hint ol { margin: 0; padding-left: 1.25rem; font-size: 0.875rem; line-height: 1.7; color: var(--text-2, rgba(255, 255, 255, 0.8)); }
	.ios-foot { margin: 0.75rem 0 0; font-size: 0.8rem; color: var(--text-2, rgba(255, 255, 255, 0.6)); }

	.ios-close {
		position: absolute;
		top: 0.75rem;
		right: 0.75rem;
		background: transparent;
		border: none;
		color: var(--text-2, rgba(255, 255, 255, 0.55));
		font-size: 1rem;
		cursor: pointer;
		padding: 0.25rem;
		line-height: 1;
	}

	.ios-arrow {
		width: 0;
		height: 0;
		border-left: 0.75rem solid transparent;
		border-right: 0.75rem solid transparent;
		border-top: 0.75rem solid var(--surface-1, #1e2d3d);
		margin-top: -1px;
	}
</style>
