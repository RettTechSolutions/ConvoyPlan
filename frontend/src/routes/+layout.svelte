<script lang="ts">
	import { onMount } from 'svelte';
	import { goto } from '$app/navigation';
	import { page } from '$app/stores';
	import { auth } from '$lib/stores/auth';
	import { brandingStore, applyBranding, type Branding } from '$lib/stores/branding';
	import { themeStore } from '$lib/stores/theme';

	let { children } = $props();

	const PUBLIC_ROUTES = ['/login', '/share', '/setup'];
	let setupChecked = $state(false);
	let demoMode = $state(false);

	onMount(async () => {
		auth.init();
		themeStore.init();

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
		const isPublic = PUBLIC_ROUTES.some((r) => $page.url.pathname.startsWith(r));
		if (!isPublic && !$auth.token) {
			goto('/login');
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

<footer class="powered-by">Powered by ConvoyPlan</footer>

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
