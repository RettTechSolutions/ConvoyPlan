<!--
  Der Füllstand von Tank bzw. Akku eines Fahrzeugs, wie Fahrer-Link und
  Tracking-Ansicht ihn beide zeigen. Gemeinsame Komponente wie
  `StaerkeBadge`, damit „gemeldet" und „laut Planung" an beiden Stellen gleich
  auseinandergehalten werden.

  Ohne Meldung und ohne eingetragenen Stand steht nichts da — eine leere
  Anzeige sähe nach einer Information aus, die es nicht gibt.
-->
<script lang="ts">
	import { fuellstandAnzeige, type FuellstandFelder } from '$lib/tracking/fuellstand';

	let { fahrzeugId, felder }: { fahrzeugId: string; felder: FuellstandFelder } = $props();

	const anzeige = $derived(fuellstandAnzeige(felder));
</script>

{#if anzeige}
	<span
		class="fuellstand"
		class:warnung={anzeige.warnung}
		class:geplant={!anzeige.gemeldet}
		data-testid="fuellstand-{fahrzeugId}"
		title={anzeige.titel}
	>
		<span aria-hidden="true">{felder.propulsion === 'electric' ? '🔋' : '⛽'}</span>
		<span class="text">{anzeige.text}</span>
		<!-- Nicht allein die Farbe: auch auf einem Schirm in der Sonne erkennbar. -->
		{#if anzeige.warnung}<span class="warnzeichen" aria-hidden="true">⚠</span>{/if}
	</span>
{/if}

<style>
	.fuellstand {
		display: inline-flex;
		align-items: baseline;
		gap: .3rem;
		max-width: 100%;
		font-size: var(--text-xs);
		font-variant-numeric: tabular-nums;
	}
	.text { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
	.fuellstand:not(.geplant) .text { font-weight: 600; }
	.geplant .text { color: var(--text-muted, #95a5a6); }
	/* Die Farbe unterstreicht nur, was der Titel ausspricht. */
	.warnung .text, .warnzeichen { color: #f1c40f; font-weight: 700; }
</style>
