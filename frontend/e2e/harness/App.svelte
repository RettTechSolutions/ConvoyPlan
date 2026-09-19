<script lang="ts">
	/**
	 * Was die Hülle zeigt, steht in `?k=` — ohne Angabe der Teilen-Dialog.
	 *
	 * Ein Schalter statt einer zweiten Hülle: die beiden Testgegenstände
	 * brauchen denselben Stub und dieselbe lange Seite darunter, und eine
	 * zweite `index.html` hieße einen dritten Server in `playwright.config.ts`.
	 */
	import ShareLinkModal from '$lib/components/ShareLinkModal.svelte';
	import FeedbackModal from '$lib/components/FeedbackModal.svelte';
	import { feedbackStore } from '$lib/stores/feedback';

	const welche = new URLSearchParams(location.search).get('k') ?? 'share';
	if (welche === 'feedback') feedbackStore.open('bug');
</script>

{#if welche === 'feedback'}
	<FeedbackModal />
{:else}
	<ShareLinkModal convoyId="demo" convoyName="THW OV Musterstadt – Verlegung Nord" onClose={() => {}} />
{/if}
