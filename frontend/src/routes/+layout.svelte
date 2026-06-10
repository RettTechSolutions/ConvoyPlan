<script lang="ts">
	import { onMount } from 'svelte';
	import { goto } from '$app/navigation';
	import { page } from '$app/stores';
	import { auth } from '$lib/stores/auth';
	import { brandingStore, applyBranding, type Branding } from '$lib/stores/branding';
	import { themeStore } from '$lib/stores/theme';
	import { versionStore } from '$lib/stores/version.svelte';
	import { printConsoleBanner } from '$lib/console-banner';
	import InstallPrompt from '$lib/components/InstallPrompt.svelte';

	let { children } = $props();

	// /o/ hat eigenes Guard-Layout; /share/ und /track/ sind öffentlich (Token-/Slug-basiert)
	// Wurzelpfad '/' ist die Org-Code-Eingabe — ebenfalls öffentlich
	// /admin ist self-gated (zeigt selbst die Anmeldung) — daher öffentlich erreichbar.
	const PUBLIC_ROUTES = ['/share', '/track', '/setup', '/o/', '/admin'];
	const isPublicPath = (path: string) =>
		path === '/' || PUBLIC_ROUTES.some((r) => path.startsWith(r));
	let setupChecked = $state(false);
	let demoMode = $state(false);

	// Auth synchron initialisieren — muss vor jedem onMount der Kind-Komponenten
	// verfügbar sein, da Svelte onMount von innen nach außen aufruft.
	if (typeof localStorage !== 'undefined') {
		auth.init();
		themeStore.init();
	}

	onMount(async () => {
		printConsoleBanner();

		// Load build version info (public, non-blocking)
		versionStore.load();

		// Raw fetch (not brandingApi) — GET /api/branding is public and needs no auth token
		try {
			const resp = await fetch('/api/branding');
			if (resp.ok) {
				const data = await resp.json() as Branding;
				brandingStore.set(data);
				applyBranding(data);
			}
		} catch {
			// Keep defaults
		}

		try {
			const resp = await fetch('/api/setup/status');
			if (resp.ok) {
				const data = await resp.json();
				if (data.setup_required && !$page.url.pathname.startsWith('/setup')) {
					goto('/setup');
					return;
				}
			}
		} catch {
			// Backend not reachable yet — don't block the UI
		}

		setupChecked = true;
	});

	$effect(() => {
		if (!setupChecked) return;
		const isPublic = isPublicPath($page.url.pathname);
		if (!isPublic && !$auth.token) {
			goto('/admin');
			return;
		}
		if ($auth.token && !isPublic) {
			fetch('/api/license/mode')
				.then(r => r.ok ? r.json() : null)
				.then(data => { if (data) demoMode = data.demo_mode === true; })
				.catch(() => {});
		} else {
			demoMode = false;
		}
	});
</script>

<svelte:head>
	<title>{$brandingStore.app_name}</title>
	<link rel="icon" type="image/png" href={$themeStore === 'light' ? '/logo/dark/Logo_Favicon.png' : '/logo/light/Logo_Favicon.png'} />
	<!--
		Haupt-App-Manifest (ConvoyPlan) — bindet eine eigenständige, installierbare PWA an,
		getrennt von der „Convoy Tracking"-App. Auf /track-Seiten wird stattdessen das
		Tracking-Manifest via TrackingPwaHead eingebunden, daher hier ausschließen, damit
		nicht zwei Manifeste gleichzeitig aktiv sind.
	-->
	{#if !$page.url.pathname.startsWith('/track')}
		<link rel="manifest" href="/app.webmanifest" />
		<meta name="apple-mobile-web-app-capable" content="yes" />
		<meta name="mobile-web-app-capable" content="yes" />
		<meta name="apple-mobile-web-app-title" content="ConvoyPlan" />
		<meta name="apple-mobile-web-app-status-bar-style" content="black-translucent" />
		<meta name="theme-color" content="#0f1419" />
		<link rel="apple-touch-icon" href="/icons/icon-192.png" />
	{/if}
</svelte:head>

{#if demoMode}
	<div class="demo-banner" role="alert">
		<span><span aria-hidden="true">⚠</span> Demo-Modus — keine gültige Lizenz. Schreiboperationen sind gesperrt.</span>
		{#if $auth.is_superadmin}
			<a href="/admin">Lizenz aktivieren →</a>
		{/if}
	</div>
{/if}

{@render children()}

<!-- Auf /track-Seiten greift die eigenständige Tracking-App-Installation
     (eigenes Manifest + eigene Install-CTA), daher hier kein generischer Banner. -->
{#if !$page.url.pathname.startsWith('/track')}
	<InstallPrompt />
{/if}

<footer class="powered-by">
	v{__APP_VERSION__}
	{#if versionStore.data.update_available}
		· <a
			class="update-hint"
			href="https://github.com/RettTechSolutions/ConvoyPlan/releases/latest"
			target="_blank"
			rel="noopener noreferrer"
			title="Neue Version {versionStore.data.latest} verfügbar"
		>Update verfügbar</a>
	{/if}
</footer>

<style>
	.powered-by {
		position: fixed;
		bottom: .25rem;
		right: .5rem;
		font-size: .65rem;
		color: var(--color-text-muted, #7f8c8d);
		opacity: 0.55;
		pointer-events: none;
		z-index: 1;
		user-select: none;
	}

	.powered-by .update-hint {
		pointer-events: auto;
		color: #f59e0b;
		font-weight: 600;
		text-decoration: none;
	}
	.powered-by .update-hint:hover {
		text-decoration: underline;
	}

	.demo-banner {
		position: sticky;
		top: 0;
		z-index: 1000;
		background: #f59e0b;
		color: #1c1917;
		padding: 0.5rem 1.25rem;
		display: flex;
		justify-content: center;
		align-items: center;
		gap: 1.25rem;
		font-size: 0.875rem;
		font-weight: 500;
		text-align: center;
	}

	.demo-banner a {
		color: #1c1917;
		text-decoration: underline;
		font-weight: 700;
		white-space: nowrap;
	}
</style>
