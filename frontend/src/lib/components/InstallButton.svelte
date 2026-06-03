<script lang="ts">
	import { pwaStore, canShowInstall } from '$lib/stores/pwa';

	let showIOSHint = $state(false);
	let installing = $state(false);

	async function handleClick() {
		if ($pwaStore.isIOS) {
			showIOSHint = true;
			return;
		}
		if ($pwaStore.deferredPrompt) {
			installing = true;
			try {
				await pwaStore.install();
			} finally {
				installing = false;
			}
		}
	}

	function closeHint() {
		showIOSHint = false;
	}
</script>

{#if $canShowInstall && !$pwaStore.isStandalone}
	<button
		class="install-btn"
		onclick={handleClick}
		disabled={installing}
		title="Als App installieren"
		aria-label="Als App installieren"
	>
		{#if installing}
			⏳
		{:else}
			⊕
		{/if}
		<span>App</span>
	</button>
{/if}

{#if showIOSHint}
	<!-- svelte-ignore a11y_no_static_element_interactions -->
	<div class="ios-overlay" onclick={closeHint}>
		<div class="ios-hint" onclick={(e) => e.stopPropagation()}>
			<button class="ios-close" onclick={closeHint} aria-label="Schließen">✕</button>
			<strong>Auf dem iPhone / iPad installieren</strong>
			<ol>
				<li>Tippe auf das <span>⬆️</span> <strong>Teilen</strong>-Symbol in Safari</li>
				<li>Wähle <strong>„Zum Home-Bildschirm"</strong></li>
				<li>Tippe auf <strong>„Hinzufügen"</strong></li>
			</ol>
		</div>
		<div class="ios-arrow" aria-hidden="true"></div>
	</div>
{/if}

<style>
	.install-btn {
		display: flex;
		align-items: center;
		gap: 0.3rem;
		background: none;
		border: 1px solid var(--border);
		border-radius: 6px;
		color: var(--text-2);
		font-size: var(--text-sm);
		padding: 0.25rem 0.5rem;
		cursor: pointer;
		transition: background 0.15s, color 0.15s;
		white-space: nowrap;
	}

	.install-btn:hover:not(:disabled) {
		background: var(--surface-2);
		color: var(--text-1);
	}

	.install-btn:disabled { opacity: 0.5; cursor: not-allowed; }

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
