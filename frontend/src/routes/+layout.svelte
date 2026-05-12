<script lang="ts">
	import { onMount } from 'svelte';
	import { goto } from '$app/navigation';
	import { page } from '$app/stores';
	import { auth } from '$lib/stores/auth';
	import { brandingStore, applyBranding } from '$lib/stores/branding';

	let { children } = $props();

	const PUBLIC_ROUTES = ['/login', '/share', '/setup'];
	let setupChecked = $state(false);

	onMount(async () => {
		auth.init();

		try {
			const resp = await fetch('/api/branding');
			if (resp.ok) {
				const data = await resp.json();
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
		if (!isPublic && !$auth.token && typeof window !== 'undefined') {
			goto('/login');
		}
	});
</script>

<svelte:head>
	<title>{$brandingStore.app_name}</title>
	<link rel="icon" type="image/svg+xml" href="/favicon.svg" />
</svelte:head>

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
</style>
