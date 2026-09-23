<!--
  Die Betriebsstofflage eines Fahrzeugs in der Fahrzeugzeile — Fahrer-Link und
  Tracking-Ansicht zeigen dieselbe. Kurz, weil die Zeile schon Name, Stärke und
  Status trägt; die ganze Meldung steht im Titel.

  Ohne Meldung steht hier nichts: Anders als bei der Stärke ist „nicht
  gemeldet" der Normalfall — die Meldung kommt nur aus der Companion-App —,
  und ein Platzhalter in jeder Zeile wäre Rauschen.
-->
<script lang="ts">
	import {
		betriebsstoffKurz,
		betriebsstoffTitel,
		istKnapp,
		type Betriebsstoff,
	} from '$lib/tracking/betriebsstoff';

	let { fahrzeugId, lage }: { fahrzeugId: string; lage: Betriebsstoff | null } = $props();
</script>

{#if lage}
	<span
		class="betriebsstoff"
		class:knapp={istKnapp(lage)}
		data-testid="betriebsstoff-{fahrzeugId}"
		title={betriebsstoffTitel(lage)}
		aria-label={betriebsstoffTitel(lage)}
	>
		<span aria-hidden="true">⛽</span>
		{betriebsstoffKurz(lage)}
	</span>
{/if}

<style>
	.betriebsstoff {
		display: inline-flex;
		align-items: baseline;
		gap: .2rem;
		font-variant-numeric: tabular-nums;
		white-space: nowrap;
		font-size: .8em;
		color: var(--text-muted, #95a5a6);
	}
	.knapp { color: #f1c40f; font-weight: 600; }
</style>
