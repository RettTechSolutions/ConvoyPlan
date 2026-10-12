<script lang="ts">
	/**
	 * Marke „+ TH" an einem Wegpunkt, in dem ein fälliger Halt aufgeht (Regeln
	 * in `$lib/route/halte.ts`). Der volle Text steht im Tooltip und für
	 * Screenreader — die Marke allein soll die Zeile nicht sprengen.
	 */
	import type { ZusammengelegterHalt } from '$lib/api';
	import { vermerkKurz, vermerkText } from '$lib/route/halte';

	let { eintraege, haltMin }: { eintraege: ZusammengelegterHalt[] | undefined; haltMin: number } = $props();
	const text = $derived(vermerkText(eintraege ?? [], haltMin));
</script>

{#if eintraege && eintraege.length > 0}
	<span class="vermerk" title={text} aria-label={text} role="note">{eintraege.map(vermerkKurz).join(' ')}</span>
{/if}

<style>
	.vermerk { display: inline-block; padding: .05rem .35rem; border-radius: 4px; font-size: .7rem; font-weight: 600; background: rgba(52,152,219,.25); color: #7fbde8; white-space: nowrap; }
</style>
