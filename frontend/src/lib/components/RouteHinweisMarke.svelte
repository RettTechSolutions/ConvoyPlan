<script lang="ts">
	/**
	 * Zählmarke am Reiter „Route" (Regeln in `$lib/route/hinweise.ts`). Ohne
	 * Hinweis steht nichts da — eine „0" wäre nur ein weiteres Zeichen in einer
	 * Leiste, die gerade leerer werden soll.
	 */
	import type { RouteHinweise } from '$lib/route/hinweise';

	let { hinweise }: { hinweise: RouteHinweise } = $props();
	const text = $derived(hinweise.anzahl === 1 ? '1 Hinweis zur Route' : `${hinweise.anzahl} Hinweise zur Route`);
</script>

{#if hinweise.anzahl > 0}
	<span class="marke" class:kritisch={hinweise.kritisch} role="status" aria-label={text} title={text}>{hinweise.anzahl}</span>
{/if}

<style>
	.marke { display: inline-block; min-width: 1.1rem; margin-left: .3rem; padding: 0 .3rem; border-radius: 9px; font-size: .68rem; font-weight: 700; line-height: 1.1rem; text-align: center; background: rgba(241,196,15,.25); color: #e0b928; }
	.marke.kritisch { background: rgba(226,61,40,.85); color: #fff; }
</style>
