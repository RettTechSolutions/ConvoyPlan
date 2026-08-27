<!-- frontend/src/lib/components/LocationSearch.svelte -->
<script lang="ts">
	// Geocoding über den Backend-Proxy /api/geocode/search: nutzt HERE Geocoding
	// & Search, wenn ein API-Key hinterlegt ist (der Key bleibt serverseitig),
	// sonst automatisch Photon (komoot). Beide sind auf Tipp-während-Suchen
	// (Autocomplete) ausgelegt und liefern für Teil-Adressen aus dem abgedeckten
	// Gebiet (DACH) gute Treffer — der Bias dorthin sitzt im Backend.
	import { getBaseUrl, getToken } from '$lib/api/client';
	import type { GeocodeResponse } from '$lib/api';

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

	// Kostendeckelung der HERE-Anfragen beginnt schon hier im Client: Erst ab 3
	// Zeichen und nach einer etwas längeren Tipp-Pause (400 ms) wird überhaupt
	// eine Anfrage abgesetzt, und identische Eingaben werden aus einem kleinen
	// Cache bedient statt erneut abgefragt. Das senkt die Anfragezahl deutlich,
	// ohne die Bedienung spürbar zu verlangsamen.
	const MIN_LEN = 3;
	const DEBOUNCE_MS = 400;

	let query = $state('');
	let results = $state<Suggestion[]>([]);
	let activeIndex = $state(-1);
	let loading = $state(false);
	let error = $state(false);
	let searched = $state(false);
	let open = $state(false);

	let timer: ReturnType<typeof setTimeout>;
	let controller: AbortController | null = null;
	// Cache identischer Suchbegriffe (z. B. beim Löschen und Neutippen), damit
	// derselbe String nicht mehrfach eine (kostenpflichtige) HERE-Anfrage auslöst.
	const cache = new Map<string, Suggestion[]>();

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
		const cached = cache.get(q);
		if (cached) {
			results = cached;
			loading = false;
			error = false;
			searched = true;
			return;
		}
		loading = true;
		error = false;
		timer = setTimeout(() => void run(q), DEBOUNCE_MS);
	}

	async function run(q: string) {
		controller = new AbortController();
		try {
			const token = getToken();
			const url = `${getBaseUrl()}/api/geocode/search?q=${encodeURIComponent(q)}&limit=6`;
			const res = await fetch(url, {
				signal: controller.signal,
				headers: token ? { Authorization: `Bearer ${token}` } : {}
			});
			if (!res.ok) throw new Error(`HTTP ${res.status}`);
			const data: GeocodeResponse = await res.json();
			results = (data.results ?? []).map((r) => ({
				lat: r.lat,
				lon: r.lon,
				primary: r.primary,
				secondary: r.secondary
			}));
			cache.set(q, results);
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
