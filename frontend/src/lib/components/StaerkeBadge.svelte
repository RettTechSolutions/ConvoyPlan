<!--
  Die Mannschaftsstärke eines Fahrzeugs, wie Fahrer-Link und Tracking-Ansicht
  sie beide zeigen. Gemeinsame Komponente, damit „nicht gemeldet" an beiden
  Stellen gleich aussieht — der Unterschied zu „0/0/0//0" ist der ganze Punkt.
-->
<script lang="ts">
	import {
		formatStaerke,
		istAus,
		sollAus,
		staerkeTitel,
		weichtAb,
		type StaerkeFelder,
	} from '$lib/tracking/staerke';

	let { fahrzeugId, felder }: { fahrzeugId: string; felder: StaerkeFelder } = $props();

	const soll = $derived(sollAus(felder));
	const ist = $derived(istAus(felder));
	const abweichung = $derived(weichtAb(soll, ist));
</script>

<span
	class="staerke"
	class:abweichung
	class:offen={!ist}
	data-testid="staerke-{fahrzeugId}"
	title={staerkeTitel(soll, ist)}
>
	<span class="ist">{formatStaerke(ist)}</span>
	{#if soll}<span class="soll">Soll {formatStaerke(soll)}</span>{/if}
</span>

<style>
	.staerke {
		display: inline-flex;
		align-items: baseline;
		gap: .3rem;
		font-variant-numeric: tabular-nums;
		white-space: nowrap;
	}
	.ist { font-weight: 600; }
	.offen .ist { color: var(--text-muted, #95a5a6); font-weight: 500; }
	.abweichung .ist { color: #f1c40f; }
	.soll { font-size: .75em; color: var(--text-muted, #95a5a6); }
</style>
