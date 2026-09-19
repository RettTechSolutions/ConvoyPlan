<script lang="ts">
	/**
	 * Fußzeile der Planungs-Seitenleiste: Theme, Hilfe, Melden, Installation
	 * und der Build-Stand.
	 *
	 * Eigene Komponente, damit die Hülle unter `e2e/harness/` sie ohne die
	 * halbe Planungsseite zeigen kann: Wie eng die Zeile steht, sieht man ihr
	 * im Quelltext nicht an — nur auf einem Bildschirmfoto.
	 */
	import { themeStore } from '$lib/stores/theme';
	import { tutorialStore } from '$lib/stores/tutorial';
	import { feedbackStore } from '$lib/stores/feedback';
	import { versionStore } from '$lib/stores/version.svelte';
	import { formatVersion } from '$lib/version';
	import InstallButton from '$lib/components/InstallButton.svelte';

	// Nicht der rohe Wert: `git describe` liefert auf Nightly-Bauten
	// "2026.6.1-15-g951e75e" — zu lang für die 340px breite Leiste, und der
	// Commit-Zähler ("-15-") sagt niemandem etwas. Der volle Stand bleibt im
	// `title` erreichbar, weil man ihn für eine Fehlermeldung braucht.
	const build = formatVersion(__APP_VERSION__);
</script>

<div class="sidebar-footer" data-tour="sidebar-footer">
	<button class="theme-toggle" onclick={() => themeStore.toggle()} aria-label="Theme umschalten">
		{$themeStore === 'dark' ? '☀' : '☾'}
		<span>{$themeStore === 'dark' ? 'Light' : 'Dark'}</span>
	</button>
	<button class="theme-toggle" onclick={() => tutorialStore.open()} aria-label="Tutorial starten" title="Tutorial / Hilfe">
		?
		<span>Hilfe</span>
	</button>
	<!-- Neben der Hilfe und nicht als schwebender Knopf über der Karte:
	     dort verdeckte er genau das, worüber gemeldet wird. -->
	<button class="theme-toggle" onclick={() => feedbackStore.open('bug')} aria-label="Fehler melden oder Funktion vorschlagen" title="Fehler melden / Funktion vorschlagen">
		🐞
		<span>Melden</span>
	</button>
	<InstallButton />
	<span class="app-version" title="Build {__APP_VERSION__}">
		v{build.base}{#if build.commit}&nbsp;· {build.commit}{/if}
		{#if versionStore.data.update_available}
			<a
				class="update-hint"
				href="https://github.com/RettTechSolutions/ConvoyPlan/releases/latest"
				target="_blank"
				rel="noopener noreferrer"
				title="Neue Version {versionStore.data.latest} verfügbar"
			>· Update verfügbar</a>
		{/if}
	</span>
</div>

<style>
	/* `flex-wrap`, weil vier Knöpfe plus Version nicht in eine 340px breite
	   Zeile passen. Ohne den Umbruch gab Flexbox der Version, was übrig war —
	   45px —, und sie brach darin selbst um: ein zweizeiliger Rest am rechten
	   Rand, der nach Fehler aussah, weil er einer war. */
	.sidebar-footer {
		flex-shrink: 0;
		border-top: 1px solid var(--border);
		padding: .75rem 1rem;
		display: flex;
		flex-wrap: wrap;
		align-items: center;
		gap: .4rem .5rem;
	}
	.theme-toggle {
		display: flex;
		align-items: center;
		gap: .4rem;
		background: none;
		border: 1px solid var(--border);
		border-radius: 6px;
		color: var(--text-2);
		font-size: var(--text-sm);
		padding: .25rem .5rem;
		cursor: pointer;
		white-space: nowrap;
	}
	.theme-toggle:hover { background: var(--surface-2); }
	/* `margin-left: auto` hält die Version rechts, solange sie in die Zeile der
	   Knöpfe passt, und stellt sie sonst an den rechten Rand der nächsten. */
	.app-version {
		font-size: var(--text-xs);
		color: var(--text-muted);
		margin-left: auto;
		min-width: 0;
		overflow-wrap: anywhere;
	}
	.app-version .update-hint { color: #f59e0b; font-weight: 600; text-decoration: none; }
	.app-version .update-hint:hover { text-decoration: underline; }
</style>
