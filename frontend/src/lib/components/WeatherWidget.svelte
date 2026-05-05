<script lang="ts">
	import { onMount } from 'svelte';
	import { weatherApi, type WeatherResponse } from '$lib/api';

	interface Props {
		lat: number;
		lon: number;
	}

	let { lat, lon }: Props = $props();

	let weather = $state<WeatherResponse | null>(null);
	let expanded = $state(false);
	let loading = $state(true);

	const WMO_ICONS: Record<string, string> = {
		Klar: '☀️', 'Überwiegend klar': '🌤️', 'Teils bewölkt': '⛅',
		Bewölkt: '☁️', Nebel: '🌫️', Raureif: '🌫️',
		'Leichter Nieselregen': '🌦️', Nieselregen: '🌧️', 'Starker Nieselregen': '🌧️',
		'Leichter Regen': '🌧️', Regen: '🌧️', 'Starker Regen': '⛈️',
		'Leichter Schnee': '🌨️', Schnee: '❄️', 'Starker Schnee': '❄️',
		'Leichte Schauer': '🌦️', Schauer: '🌧️', 'Starke Schauer': '⛈️',
		Gewitter: '⛈️', 'Gewitter mit Hagel': '⛈️', 'Schweres Gewitter mit Hagel': '⛈️',
	};

	function icon(condition: string) {
		return WMO_ICONS[condition] ?? '🌡️';
	}

	onMount(async () => {
		try {
			weather = await weatherApi.get(lat, lon);
		} finally {
			loading = false;
		}
	});
</script>

<div class="weather-widget" class:expanded>
	{#if loading}
		<span class="loading">⏳</span>
	{:else if weather}
		<button class="summary" onclick={() => (expanded = !expanded)}>
			<span class="ico">{icon(weather.current.condition)}</span>
			<span class="temp">{weather.current.temp_c?.toFixed(0)}°C</span>
			<span class="wind">💨 {weather.current.windspeed_kmh?.toFixed(0)} km/h</span>
			<span class="chevron">{expanded ? '▲' : '▼'}</span>
		</button>
		{#if expanded}
			<div class="condition">{weather.current.condition}</div>
			<div class="forecast">
				{#each weather.hourly_forecast.slice(0, 8) as hour}
					<div class="hour">
						<div class="htime">{hour.time.slice(11, 16)}</div>
						<div class="hico">{icon(hour.condition)}</div>
						<div class="htemp">{hour.temp_c?.toFixed(0)}°</div>
						<div class="hprecip">{hour.precip_pct ?? 0}%</div>
					</div>
				{/each}
			</div>
		{/if}
	{:else}
		<span class="na">Wetter N/V</span>
	{/if}
</div>

<style>
	.weather-widget {
		position: absolute;
		top: 1rem;
		right: 1rem;
		z-index: 10;
		background: rgba(26, 39, 68, 0.92);
		color: white;
		border-radius: 8px;
		padding: .5rem .75rem;
		backdrop-filter: blur(4px);
		min-width: 170px;
		font-size: .82rem;
	}
	.summary {
		display: flex;
		align-items: center;
		gap: .4rem;
		background: none;
		border: none;
		color: white;
		cursor: pointer;
		width: 100%;
		padding: 0;
	}
	.ico { font-size: 1.3rem; }
	.temp { font-weight: 700; font-size: 1rem; }
	.wind { color: rgba(255,255,255,.7); font-size: .78rem; }
	.chevron { margin-left: auto; font-size: .7rem; }
	.condition { color: rgba(255,255,255,.8); margin-top: .25rem; font-size: .78rem; }
	.forecast {
		display: flex;
		gap: .3rem;
		margin-top: .5rem;
		overflow-x: auto;
		padding-bottom: .25rem;
	}
	.hour {
		display: flex;
		flex-direction: column;
		align-items: center;
		min-width: 34px;
		font-size: .72rem;
		color: rgba(255,255,255,.8);
		gap: .1rem;
	}
	.htime { color: rgba(255,255,255,.6); }
	.hico { font-size: 1rem; }
	.hprecip { color: #74b9ff; }
	.loading, .na { font-size: .8rem; color: rgba(255,255,255,.6); }
</style>
