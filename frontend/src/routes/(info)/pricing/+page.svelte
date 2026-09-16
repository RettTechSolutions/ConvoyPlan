<script lang="ts">
	import InfoPage from '$lib/components/InfoPage.svelte';
	import type { PageData } from './$types';

	let { data }: { data: PageData } = $props();
</script>

<InfoPage {data} />
