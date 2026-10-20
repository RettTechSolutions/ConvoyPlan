<script lang="ts">
	/**
	 * Fehlerseite für alles, was SvelteKit nicht ausliefern kann (falscher Link,
	 * abgeschaltete Infoseite, Fehler beim Laden).
	 *
	 * Ohne sie stand die Vorgabe von SvelteKit da: schwarze Schrift auf dem dunklen
	 * Hintergrund aus `app.html`, ohne Rand — am Telefon wie am Schreibtisch kaum
	 * lesbar, und kein Weg zurück. Aufmachung wie die Anmeldekarten.
	 */
	import { page } from '$app/state';
	import AppLogo from '$lib/components/AppLogo.svelte';

	const titel = $derived(
		page.status === 404 ? 'Seite nicht gefunden'
		: page.status >= 500 ? 'Fehler auf dem Server'
		: 'Seite nicht verfügbar',
	);
	const text = $derived(
		page.status === 404
			? 'Diese Adresse gibt es auf dieser Instanz nicht. Vielleicht ist der Link veraltet oder unvollständig.'
			: (page.error?.message ?? 'Die Seite konnte nicht geladen werden.'),
	);
</script>

<svelte:head><title>{titel} – ConvoyPlan</title></svelte:head>

<main class="fehler-seite">
	<div class="karte">
		<div class="logo"><AppLogo width={160} /></div>
		<p class="code">Fehler {page.status}</p>
		<h1>{titel}</h1>
		<p class="text">{text}</p>
		<a class="weiter" href="/">Zur Startseite →</a>
	</div>
</main>

<style>
	.fehler-seite {
		display: flex;
		align-items: center;
		justify-content: center;
		min-height: 100vh;
		min-height: 100dvh;
		box-sizing: border-box;
		padding: max(1rem, env(safe-area-inset-top)) max(1rem, env(safe-area-inset-right))
			max(1rem, env(safe-area-inset-bottom)) max(1rem, env(safe-area-inset-left));
		background: var(--bg);
		color: var(--text-1);
		font-family: system-ui, sans-serif;
	}
	.karte {
		background: var(--surface-1);
		border: 1px solid var(--border);
		border-radius: 8px;
		padding: 2.5rem;
		width: 100%;
		max-width: 380px;
		box-sizing: border-box;
		box-shadow: var(--shadow);
		text-align: center;
	}
	.logo { display: flex; justify-content: center; margin-bottom: 1.25rem; }
	.code { margin: 0; font-size: var(--text-xs); text-transform: uppercase; letter-spacing: .08em; color: var(--text-muted); }
	h1 { margin: .35rem 0 .75rem; font-size: 1.25rem; }
	.text { margin: 0 0 1.5rem; font-size: var(--text-sm); color: var(--text-2); line-height: 1.5; }
	.weiter { color: var(--color-primary); font-weight: 600; text-decoration: none; }
	.weiter:hover { text-decoration: underline; }
	@media (max-width: 420px) { .karte { padding: 1.75rem 1.25rem; } }
</style>
