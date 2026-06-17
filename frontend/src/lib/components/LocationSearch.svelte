<!-- frontend/src/lib/components/LocationSearch.svelte -->
<script lang="ts">
	// Geocoding via Photon (https://photon.komoot.io) — im Gegensatz zu Nominatims
	// Volltext-Suche ist Photon explizit für Tipp-während-Suchen (Autocomplete)
	// gebaut und liefert für deutsche Teil-Adressen deutlich bessere Treffer.
	interface PhotonProps {
		name?: string;
		street?: string;
		housenumber?: string;
		postcode?: string;
		city?: string;
		town?: string;
		village?: string;
		district?: string;
		county?: string;
		state?: string;
		country?: string;
	}
	interface PhotonFeature {
		geometry: { coordinates: [number, number] };
		properties: PhotonProps;
	}
	interface Suggestion {
		lat: number;
		lon: number;
		primary: string;
		secondary: string;
	}

	interface Props {
		placeholder?: string;
		onSelect: (lat: number, lon: number, label: string) => void;
	}

	let { placeholder = 'Adresse suchen…', onSelect }: Props = $props();

	const MIN_LEN = 2;
	// Soft-Bias auf die Mitte Deutschlands, damit deutsche Treffer vorne stehen
	// (kein harter Filter — grenznahe Adressen bleiben auffindbar).
	const BIAS_LAT = 51.1657;
	const BIAS_LON = 10.4515;

	let query = $state('');
	let results = $state<Suggestion[]>([]);
	let activeIndex = $state(-1);
	let loading = $state(false);
	let error = $state(false);
	let searched = $state(false);
	let open = $state(false);

	let timer: ReturnType<typeof setTimeout>;
	let controller: AbortController | null = null;

	function format(p: PhotonProps): { primary: string; secondary: string } {
		const place = p.city || p.town || p.village || p.county || '';
		const streetLine = p.street
			? `${p.street}${p.housenumber ? ' ' + p.housenumber : ''}`
			: '';
		const primary = streetLine || p.name || place || 'Unbenannter Ort';
		const cityLine = [p.postcode, place].filter(Boolean).join(' ');
		const secondary = [cityLine, p.state, p.country]
			.filter((part) => part && part !== primary)
			.join(', ');
		return { primary, secondary };
	}

	function onInput() {
		clearTimeout(timer);
		controller?.abort();
		activeIndex = -1;
		const q = query.trim();
		if (q.length < MIN_LEN) {
			results = [];
			loading = false;
			error = false;
			searched = false;
			open = false;
			return;
		}
		open = true;
		loading = true;
		error = false;
		timer = setTimeout(() => void run(q), 250);
	}

	async function run(q: string) {
		controller = new AbortController();
		try {
			const url =
				`https://photon.komoot.io/api/?q=${encodeURIComponent(q)}` +
				`&lang=de&limit=6&lat=${BIAS_LAT}&lon=${BIAS_LON}`;
			const res = await fetch(url, { signal: controller.signal });
			if (!res.ok) throw new Error(`HTTP ${res.status}`);
			const data: { features?: PhotonFeature[] } = await res.json();
			results = (data.features ?? []).map((f) => {
				const { primary, secondary } = format(f.properties);
				return {
					lon: f.geometry.coordinates[0],
					lat: f.geometry.coordinates[1],
					primary,
					secondary
				};
			});
			error = false;
		} catch (e) {
			// Abgebrochene Requests (neuer Tastendruck) sind kein Fehler.
			if (e instanceof DOMException && e.name === 'AbortError') return;
			results = [];
			error = true;
		} finally {
			if (!controller?.signal.aborted) {
				loading = false;
				searched = true;
			}
		}
	}

	function select(r: Suggestion) {
		onSelect(r.lat, r.lon, [r.primary, r.secondary].filter(Boolean).join(', '));
		query = r.primary;
		results = [];
		open = false;
		searched = false;
		activeIndex = -1;
	}

	function onKeydown(e: KeyboardEvent) {
		if (e.key === 'Escape') {
			results = [];
			open = false;
			searched = false;
			activeIndex = -1;
			return;
		}
		if (!open || !results.length) return;
		if (e.key === 'ArrowDown') {
			e.preventDefault();
			activeIndex = (activeIndex + 1) % results.length;
		} else if (e.key === 'ArrowUp') {
			e.preventDefault();
			activeIndex = activeIndex <= 0 ? results.length - 1 : activeIndex - 1;
		} else if (e.key === 'Enter') {
			if (activeIndex >= 0 && activeIndex < results.length) {
				e.preventDefault();
				select(results[activeIndex]);
			}
		}
	}

	function onBlur() {
		// Verzögern, damit ein Klick auf einen Treffer noch durchkommt.
		setTimeout(() => {
			open = false;
		}, 150);
	}
</script>

<div class="search-wrap">
	<input
		bind:value={query}
		oninput={onInput}
		onkeydown={onKeydown}
		onfocus={() => {
			if (results.length || searched) open = true;
		}}
		onblur={onBlur}
		{placeholder}
		autocomplete="off"
		type="search"
		role="combobox"
		aria-expanded={open}
		aria-controls="location-results"
		aria-autocomplete="list"
	/>
	{#if loading}
		<span class="spinner" aria-label="Sucht…"></span>
	{/if}

	{#if open}
		{#if results.length}
			<ul class="results" id="location-results" role="listbox">
				{#each results as r, i}
					<li
						role="option"
						aria-selected={i === activeIndex}
						class:active={i === activeIndex}
						onmousedown={(e) => {
							e.preventDefault();
							select(r);
						}}
						onmouseenter={() => (activeIndex = i)}
					>
						<span class="primary">{r.primary}</span>
						{#if r.secondary}<span class="secondary">{r.secondary}</span>{/if}
					</li>
				{/each}
			</ul>
		{:else if error}
			<div class="status error">Suche nicht erreichbar – später erneut versuchen.</div>
		{:else if searched && !loading}
			<div class="status">Keine Treffer für „{query.trim()}".</div>
		{/if}
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
	.spinner {
		position: absolute; top: 50%; right: .6rem; width: 14px; height: 14px;
		margin-top: -7px; border-radius: 50%;
		border: 2px solid rgba(255,255,255,.25); border-top-color: rgba(255,255,255,.85);
		animation: spin .7s linear infinite; pointer-events: none;
	}
	@keyframes spin { to { transform: rotate(360deg); } }
	.results {
		position: absolute; z-index: 200; width: 100%;
		background: #1e3160; border: 1px solid rgba(255,255,255,.2);
		border-radius: 4px; margin: 2px 0 0; padding: 0; list-style: none;
		max-height: 240px; overflow-y: auto;
	}
	li {
		display: flex; flex-direction: column; gap: 1px;
		padding: .4rem .6rem; font-size: .78rem; cursor: pointer;
		border-bottom: 1px solid rgba(255,255,255,.08); line-height: 1.3;
	}
	li:last-child { border-bottom: none; }
	li.active { background: rgba(255,255,255,.14); }
	.primary { color: rgba(255,255,255,.95); }
	.secondary { color: rgba(255,255,255,.55); font-size: .72rem; }
	.status {
		position: absolute; z-index: 200; width: 100%;
		background: #1e3160; border: 1px solid rgba(255,255,255,.2);
		border-radius: 4px; margin: 2px 0 0; padding: .5rem .6rem;
		font-size: .76rem; color: rgba(255,255,255,.6); box-sizing: border-box;
	}
	.status.error { color: #ffb4b4; }
	@media (prefers-reduced-motion: reduce) {
		.spinner { animation-duration: 2s; }
	}
</style>
