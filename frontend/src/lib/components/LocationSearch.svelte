<!-- frontend/src/lib/components/LocationSearch.svelte -->
<script lang="ts">
	interface NominatimResult {
		lat: string;
		lon: string;
		display_name: string;
	}

	interface Props {
		placeholder?: string;
		onSelect: (lat: number, lon: number, label: string) => void;
	}

	let { placeholder = 'Adresse suchen…', onSelect }: Props = $props();

	let query = $state('');
	let results = $state<NominatimResult[]>([]);
	let timer: ReturnType<typeof setTimeout>;

	function onInput() {
		clearTimeout(timer);
		if (!query.trim()) { results = []; return; }
		timer = setTimeout(async () => {
			try {
				const url = `https://nominatim.openstreetmap.org/search?q=${encodeURIComponent(query)}&format=json&limit=5&addressdetails=0`;
				const res = await fetch(url, { headers: { 'User-Agent': 'ConvoyPlan/1.0' } });
				results = await res.json();
			} catch { results = []; }
		}, 300);
	}

	function select(r: NominatimResult) {
		onSelect(parseFloat(r.lat), parseFloat(r.lon), r.display_name);
		query = r.display_name;
		results = [];
	}

	function onKeydown(e: KeyboardEvent) {
		if (e.key === 'Escape') { results = []; query = ''; }
	}
</script>

<div class="search-wrap">
	<input
		bind:value={query}
		oninput={onInput}
		onkeydown={onKeydown}
		{placeholder}
		autocomplete="off"
		type="search"
	/>
	{#if results.length}
		<ul class="results">
			{#each results as r}
				<li onclick={() => select(r)}>{r.display_name}</li>
			{/each}
		</ul>
	{/if}
</div>

<style>
	.search-wrap { position: relative; margin-bottom: .5rem; }
	input {
		width: 100%; padding: .45rem .6rem; border-radius: 4px;
		border: 1px solid rgba(255,255,255,.25); background: rgba(255,255,255,.1);
		color: white; font-size: .85rem; box-sizing: border-box;
	}
	input::placeholder { color: rgba(255,255,255,.45); }
	input:focus { outline: none; border-color: rgba(255,255,255,.5); }
	.results {
		position: absolute; z-index: 200; width: 100%;
		background: #1e3160; border: 1px solid rgba(255,255,255,.2);
		border-radius: 4px; margin: 2px 0 0; padding: 0; list-style: none;
		max-height: 200px; overflow-y: auto;
	}
	li {
		padding: .4rem .6rem; font-size: .78rem; cursor: pointer;
		border-bottom: 1px solid rgba(255,255,255,.08); color: rgba(255,255,255,.9);
		line-height: 1.3;
	}
	li:hover { background: rgba(255,255,255,.1); }
	li:last-child { border-bottom: none; }
</style>
