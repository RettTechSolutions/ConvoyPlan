<script lang="ts">
	import { onMount } from 'svelte';
	import { pwaStore, canShowInstall } from '$lib/stores/pwa';

	let showIOSHint = $state(false);
	let installing = $state(false);

	onMount(() => {
		pwaStore.init();
		// Show banner after 3s if not dismissed
		setTimeout(() => {
			if ($canShowInstall && !$pwaStore.dismissed) visible = true;
		}, 3000);
	});

	let visible = $state(false);

	async function install() {
		installing = true;
		try {
			await pwaStore.install();
			visible = false;
		} finally {
			installing = false;
		}
	}

	function openIOSHint() {
		showIOSHint = true;
	}

	function dismiss() {
		pwaStore.dismiss();
		visible = false;
		showIOSHint = false;
	}
</script>

{#if visible && !$pwaStore.dismissed}
	<div class="install-banner" role="complementary" aria-label="App installieren">
		<div class="install-content">
			<img src="/icons/icon-192.png" alt="" class="install-icon" aria-hidden="true" />
			<div class="install-text">
				<strong>Als App installieren</strong>
				<span>Schneller Zugriff direkt vom Homescreen</span>
			</div>
		</div>
		<div class="install-actions">
			{#if $pwaStore.deferredPrompt}
				<button class="btn-install" onclick={install} disabled={installing}>
					{installing ? 'Installiere…' : 'Installieren'}
				</button>
			{:else if $pwaStore.isIOS}
				<button class="btn-install" onclick={openIOSHint}>Anleitung</button>
			{/if}
			<button class="btn-dismiss" onclick={dismiss} aria-label="Schließen">✕</button>
		</div>
	</div>
{/if}

{#if showIOSHint}
	<!-- svelte-ignore a11y_no_static_element_interactions -->
	<div class="ios-overlay" onclick={dismiss}>
		<div class="ios-hint" onclick={(e) => e.stopPropagation()}>
			<button class="ios-close" onclick={dismiss} aria-label="Schließen">✕</button>
			<strong>Auf dem iPhone / iPad installieren</strong>
			<ol>
				<li>Tippe auf das <span class="ios-icon">⬆️</span> <strong>Teilen</strong>-Symbol in Safari</li>
				<li>Wähle <strong>„Zum Home-Bildschirm"</strong></li>
				<li>Tippe auf <strong>„Hinzufügen"</strong></li>
			</ol>
		</div>
		<div class="ios-arrow" aria-hidden="true"></div>
	</div>
{/if}

<style>
	.install-banner {
		position: fixed;
		bottom: 1.25rem;
		left: 50%;
		transform: translateX(-50%);
		z-index: 9000;
		display: flex;
		align-items: center;
		gap: 0.75rem;
		padding: 0.75rem 1rem;
		background: var(--surface-1, #1e2d3d);
		border: 1px solid var(--border, rgba(255,255,255,.12));
		border-radius: 1rem;
		box-shadow: 0 8px 32px rgba(0,0,0,.45);
		max-width: calc(100vw - 2rem);
		width: max-content;
		animation: slide-up 0.3s ease;
	}

	@keyframes slide-up {
		from { opacity: 0; transform: translateX(-50%) translateY(1rem); }
		to   { opacity: 1; transform: translateX(-50%) translateY(0); }
	}

	.install-icon {
		width: 2.5rem;
		height: 2.5rem;
		border-radius: 0.5rem;
		flex-shrink: 0;
	}

	.install-content {
		display: flex;
		align-items: center;
		gap: 0.75rem;
	}

	.install-text {
		display: flex;
		flex-direction: column;
		gap: 0.1rem;
		color: var(--text-1, #e8edf2);
		font-size: 0.875rem;
	}

	.install-text strong { font-size: 0.9rem; }
	.install-text span { font-size: 0.75rem; color: var(--text-2, rgba(255,255,255,.55)); }

	.install-actions {
		display: flex;
		align-items: center;
		gap: 0.5rem;
		flex-shrink: 0;
	}

	.btn-install {
		background: var(--color-primary, #E23D28);
		color: #fff;
		border: none;
		border-radius: 0.5rem;
		padding: 0.45rem 0.9rem;
		font-size: 0.85rem;
		font-weight: 600;
		cursor: pointer;
		transition: background 0.15s;
		white-space: nowrap;
	}

	.btn-install:hover:not(:disabled) { background: var(--color-primary-hover, #C23020); }
	.btn-install:disabled { opacity: 0.6; cursor: not-allowed; }

	.btn-dismiss {
		background: transparent;
		border: none;
		color: var(--text-2, rgba(255,255,255,.55));
		cursor: pointer;
		font-size: 1rem;
		padding: 0.25rem 0.4rem;
		border-radius: 0.25rem;
		line-height: 1;
		transition: color 0.15s;
	}

	.btn-dismiss:hover { color: var(--text-1, #e8edf2); }

	.ios-overlay {
		position: fixed;
		inset: 0;
		z-index: 9001;
		background: rgba(0,0,0,.55);
		display: flex;
		align-items: flex-end;
		justify-content: center;
		padding-bottom: 4rem;
	}

	.ios-hint {
		background: var(--surface-1, #1e2d3d);
		border: 1px solid var(--border, rgba(255,255,255,.12));
		border-radius: 1rem;
		padding: 1.25rem 1.5rem 1.5rem;
		max-width: 22rem;
		width: calc(100% - 2rem);
		color: var(--text-1, #e8edf2);
		position: relative;
	}

	.ios-hint strong { display: block; font-size: 1rem; margin-bottom: 0.75rem; }
	.ios-hint ol { margin: 0; padding-left: 1.25rem; font-size: 0.875rem; line-height: 1.7; color: var(--text-2, rgba(255,255,255,.8)); }
	.ios-icon { font-style: normal; }

	.ios-close {
		position: absolute;
		top: 0.75rem;
		right: 0.75rem;
		background: transparent;
		border: none;
		color: var(--text-2, rgba(255,255,255,.55));
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
