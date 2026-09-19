<script lang="ts">
	/**
	 * Was die Hülle zeigt, steht in `?k=` — ohne Angabe der Teilen-Dialog.
	 *
	 * Ein Schalter statt einer zweiten Hülle: die Testgegenstände brauchen
	 * denselben Stub und dieselbe lange Seite darunter, und eine zweite
	 * `index.html` hieße einen dritten Server in `playwright.config.ts`.
	 */
	import ShareLinkModal from '$lib/components/ShareLinkModal.svelte';
	import FeedbackModal from '$lib/components/FeedbackModal.svelte';
	import ConvoyFormModal from '$lib/components/ConvoyFormModal.svelte';
	import { feedbackStore } from '$lib/stores/feedback';

	const welche = new URLSearchParams(location.search).get('k') ?? 'share';
	if (welche === 'feedback') feedbackStore.open('bug');

	/** Ein Verband, wie ihn die Planungsseite zum Bearbeiten hineinreicht. */
	const konvoi = $state({
		name: 'Marschverband Peißenberg – Nürnberg',
		organization: 'Johanniter Peißenberg',
		organization_id: 'o1',
		start_time: '',
		speed_urban_kmh: 40,
		speed_rural_kmh: 65,
		road_preference: 'standard' as const,
		spacing_urban_m: 15,
		spacing_rural_m: 50,
		spacing_motorway_m: 100,
	});
	let konvoiOffen = $state(true);
</script>

{#if welche === 'feedback'}
	<FeedbackModal />
{:else if welche === 'konvoi'}
	{#if konvoiOffen}
		<ConvoyFormModal
			modus="bearbeiten"
			form={konvoi}
			organizations={[{ id: 'o1', name: 'Johanniter Peißenberg', description: null, member_count: 3, my_role: 'admin' }]}
			onSubmit={() => {}}
			onClose={() => (konvoiOffen = false)}
			onDelete={() => {}}
		/>
	{/if}
{:else}
	<ShareLinkModal convoyId="demo" convoyName="THW OV Musterstadt – Verlegung Nord" onClose={() => {}} />
{/if}
