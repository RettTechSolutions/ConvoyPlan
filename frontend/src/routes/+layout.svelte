<script lang="ts">
	import { onMount } from 'svelte';
	import { goto } from '$app/navigation';
	import { page } from '$app/stores';
	import { auth } from '$lib/stores/auth';

	let { children } = $props();

	const PUBLIC_ROUTES = ['/login', '/share', '/setup'];

	onMount(async () => {
		auth.init();

		// Check if first-run setup is required
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
	});

	$effect(() => {
		const isPublic = PUBLIC_ROUTES.some((r) => $page.url.pathname.startsWith(r));
		if (!isPublic && !$auth.token && typeof window !== 'undefined') {
			goto('/login');
		}
	});
</script>

<svelte:head>
	<title>ConvoyPlan</title>
	<link rel="icon" type="image/svg+xml" href="/favicon.svg" />
</svelte:head>

{@render children()}
