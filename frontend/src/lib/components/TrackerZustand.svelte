<!--
  Empfangsbalken und Batterie eines Trackers, wie man sie vom Telefon kennt.
  Gemeinsam für Org-Admin (Tracker-Liste) und Konvoi-Ansicht, damit „schwach"
  an beiden Stellen gleich aussieht. Die Regeln stehen in
  `$lib/tracking/trackerzustand`, ob der Akku warnt, sagt das Backend.
-->
<script lang="ts">
	import { akkuTitel, balken, empfangTitel, veraltet, type TrackerAnzeige } from '$lib/tracking/trackerzustand';

	let { zustand, prozent = true, jetzt = Date.now() }: { zustand: TrackerAnzeige; prozent?: boolean; jetzt?: number } = $props();

	const alt = $derived(veraltet(zustand.zuletzt_gesehen, jetzt));
	const stufe = $derived(alt ? 0 : balken(zustand.signal_dbm));
	const fuellung = $derived(Math.max(0, Math.min(100, zustand.akku_prozent ?? 0)));
	const empfang = $derived(empfangTitel(zustand, jetzt));
	const akku = $derived(akkuTitel(zustand, jetzt));
</script>

<span class="tracker-zustand" data-testid="tracker-zustand">
	<span class="empfang" class:alt role="img" aria-label={empfang} title={empfang} data-balken={stufe}>
		<svg viewBox="0 0 16 12" width="16" height="12" aria-hidden="true">
			{#each [1, 2, 3, 4] as b (b)}
				<rect x={(b - 1) * 4} y={12 - b * 3} width="3" height={b * 3} rx="0.5" class:an={b <= stufe} />
			{/each}
		</svg>
	</span>
	{#if zustand.akku_prozent !== null}
		<span class="akku" class:niedrig={zustand.akku_niedrig} role="img" aria-label={akku} title={akku}>
			<svg viewBox="0 0 24 12" width="24" height="12" aria-hidden="true">
				<rect class="huelle" x="0.5" y="0.5" width="20" height="11" rx="2" />
				<rect class="pol" x="21" y="3.5" width="2.5" height="5" rx="1" />
				<rect class="fuellung" x="2" y="2" width={(17 * fuellung) / 100} height="8" rx="1" />
				{#if zustand.extern}
					<path class="blitz" d="M11.5 1.5 L7.5 6.5 H10 L8.5 10.5 L12.5 5.5 H10 Z" />
				{/if}
			</svg>
			{#if prozent}<span class="prozent">{zustand.akku_prozent} %</span>{/if}
		</span>
	{/if}
</span>

<style>
	.tracker-zustand { display: inline-flex; align-items: center; gap: .45rem; vertical-align: middle; white-space: nowrap; }
	.empfang, .akku { display: inline-flex; align-items: center; gap: .2rem; color: var(--text-1, #2c3e50); }
	.empfang rect { fill: currentColor; opacity: .22; }
	.empfang rect.an { opacity: 1; }
	.empfang.alt { color: var(--text-muted, #95a5a6); }
	.akku .huelle { fill: none; stroke: currentColor; stroke-width: 1; }
	.akku .pol { fill: currentColor; }
	.akku .fuellung { fill: currentColor; }
	.akku .blitz { fill: #f1c40f; stroke: var(--surface-1, #fff); stroke-width: .6; }
	.akku.niedrig { color: #e74c3c; }
	.prozent { font-size: var(--text-xs, .72rem); font-variant-numeric: tabular-nums; }
</style>
