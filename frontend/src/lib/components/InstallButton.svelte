<script lang="ts">
	import { pwaStore, canShowInstall } from '$lib/stores/pwa';

	let showHint = $state(false);
	let installing = $state(false);

	async function handleClick() {
		if ($pwaStore.isIOS) {
			showHint = true;
			return;
		}
		if ($pwaStore.deferredPrompt) {
			installing = true;
			try {
				await pwaStore.install();
			} finally {
				installing = false;
			}
			return;
		}
		// No native prompt available — show manual instructions
		showHint = true;
	}

	function closeHint() {
		showHint = false;
	}

	$derived: {
		// If native prompt becomes available after mount, close manual hint
		if ($pwaStore.deferredPrompt && showHint) showHint = false;
	}
</script>

{#if $canShowInstall}
	<button
		class="install-btn"
		onclick={handleClick}
		disabled={installing}
		title="Als App installieren"
		aria-label="Als App installieren"
	>
		{installing ? '⏳' : '⊕'}
		<span>App</span>
	</button>
{/if}

{#if showHint}
	<!-- svelte-ignore a11y_no_static_element_interactions -->
	<div class="hint-overlay" onclick={closeHint}>
		<div class="hint-box" onclick={(e) => e.stopPropagation()}>
			<button class="hint-close" onclick={closeHint} aria-label="Schließen">✕</button>
			{#if $pwaStore.isIOS}
				<strong>Auf dem iPhone / iPad installieren</strong>
				<ol>
					<li>Tippe auf das <strong>⬆️ Teilen</strong>-Symbol in Safari</li>
					<li>Wähle <strong>„Zum Home-Bildschirm"</strong></li>
					<li>Tippe auf <strong>„Hinzufügen"</strong></li>
				</ol>
			{:else}
				<strong>Als App installieren</strong>
				<p>Klicke in der Adressleiste deines Browsers auf das <strong>Install</strong>-Symbol (⊕ oder ↓) oder öffne das Browser-Menü und wähle <strong>„App installieren"</strong> bzw. <strong>„Zum Startbildschirm hinzufügen"</strong>.</p>
			{/if}
		</div>
		<div class="hint-arrow" aria-hidden="true"></div>
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

	.hint-overlay {
		position: fixed;
		inset: 0;
		z-index: 9001;
		background: rgba(0,0,0,.55);
		display: flex;
		align-items: flex-end;
		justify-content: center;
		padding-bottom: 4rem;
	}

	.hint-box {
		background: var(--surface-1, #1e2d3d);
		border: 1px solid var(--border, rgba(255,255,255,.12));
		border-radius: 1rem;
		padding: 1.25rem 1.5rem 1.5rem;
		max-width: 22rem;
		width: calc(100% - 2rem);
		color: var(--text-1, #e8edf2);
		position: relative;
	}

	.hint-box strong { display: block; font-size: 1rem; margin-bottom: 0.75rem; }
	.hint-box ol, .hint-box p {
		margin: 0;
		padding-left: 1.25rem;
		font-size: 0.875rem;
		line-height: 1.7;
		color: var(--text-2, rgba(255,255,255,.8));
	}
	.hint-box p { padding-left: 0; }

	.hint-close {
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

	.hint-arrow {
		width: 0;
		height: 0;
		border-left: 0.75rem solid transparent;
		border-right: 0.75rem solid transparent;
		border-top: 0.75rem solid var(--surface-1, #1e2d3d);
		margin-top: -1px;
	}
</style>
