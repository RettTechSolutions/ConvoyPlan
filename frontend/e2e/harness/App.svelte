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
	import SidebarFooter from '$lib/components/SidebarFooter.svelte';
	import AktionsseitenVerwaltung from '$lib/components/AktionsseitenVerwaltung.svelte';
	import TrackerVerwaltung from '$lib/components/TrackerVerwaltung.svelte';
	import PasskeyVerwaltung from '$lib/components/PasskeyVerwaltung.svelte';
	import DurchfahrtsHoehen from '$lib/components/DurchfahrtsHoehen.svelte';
	import type { BrueckenPruefung, DurchfahrtshoeheEntry } from '$lib/api';
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

	/** Durchfahrtshöhen: `?k=hoehen&fall=…`, die Fälle stehen im Test. */
	const fall = new URLSearchParams(location.search).get('fall') ?? 'gemischt';
	const stelle = (km: number, hoehe_m: number, spielraum_m: number | null, stufe: DurchfahrtshoeheEntry['stufe']) =>
		({ km, lat: 47.8, lon: 11.1, laenge_m: 40, hoehe_m, spielraum_m, stufe });
	const bruecke = (km: number, art: string, name: string | null, osm: number, schnellstrasse = false) =>
		({ km, m: km * 1000, lat: 47.8, lon: 11.1, art, name, osm_ids: [osm], schnellstrasse });
	const GESUCHT: BrueckenPruefung = {
		geprueft_at: '2026-10-09T10:00:00Z',
		eintraege: [
			bruecke(5.2, 'Eisenbahnbrücke', 'Ammertalbahn', 101),
			bruecke(20.4, 'Straßenbrücke', null, 102, true),
			bruecke(22.0, 'Fuß-/Radwegbrücke', 'Steg', 103, true),
		],
	};
	let suche = $state<'idle' | 'laeuft' | 'fehler'>(fall === 'suche_fehler' ? 'fehler' : fall === 'suche_laeuft' ? 'laeuft' : 'idle');
	let gesucht = $state<BrueckenPruefung | null>(
		fall === 'gemischt' ? GESUCHT : fall === 'leer' ? { geprueft_at: '2026-10-09T10:00:00Z', eintraege: [] } : null,
	);
	let suchenGeklickt = $state(0);
	const HOEHEN: Record<string, { eintraege: DurchfahrtshoeheEntry[] | null; hoehe: number | null; ohne: number }> = {
		gemischt: {
			eintraege: [stelle(12.4, 3.7, 0.05, 'eng'), stelle(30.1, 4.5, 0.85, 'frei'), stelle(48.9, 3.9, 0.25, 'knapp'), stelle(60, 4.2, 0.55, 'frei')],
			hoehe: 3.65, ohne: 1,
		},
		alle_frei: { eintraege: [stelle(30.1, 4.5, 0.85, 'frei')], hoehe: 3.65, ohne: 0 },
		ohne_hoehe: { eintraege: [stelle(12.4, 3.5, null, 'unbekannt')], hoehe: null, ohne: 3 },
		leer: { eintraege: [], hoehe: 3.2, ohne: 0 },
		alt: { eintraege: null, hoehe: 3.2, ohne: 0 },
		suche_fehler: { eintraege: [], hoehe: 3.2, ohne: 0 },
		suche_laeuft: { eintraege: [], hoehe: 3.2, ohne: 0 },
		ungesucht: { eintraege: [], hoehe: 3.2, ohne: 0 },
		ohne_knopf: { eintraege: [], hoehe: 3.2, ohne: 0 },
	};
	const hoehen = HOEHEN[fall];
</script>

{#if welche === 'fuss'}
	<!-- Die Seitenleiste der Planung, nur so viel davon wie die Fußzeile sieht:
	     feste Breite und `overflow: hidden` — daran schnitt der überlaufende
	     Versionstext vorher ab. -->
	<div class="leiste" data-theme="dark">
		<div class="leiste-inhalt">Inhalt der Planung (steht für Listen und Formulare)</div>
		<SidebarFooter />
	</div>
{:else if welche === 'hoehen'}
	<!-- Breite der Seitenleiste der Planung, in der der Block steht. -->
	<div class="leiste" data-theme="dark">
		<div class="leiste-inhalt">
			<p>Route berechnet.</p>
			<DurchfahrtsHoehen
				eintraege={hoehen.eintraege}
				fahrzeughoeheM={hoehen.hoehe}
				ohneHoehe={hoehen.ohne}
				bruecken={gesucht}
				{suche}
				onSuchen={fall === 'ohne_knopf' ? undefined : () => { suchenGeklickt++; suche = 'laeuft'; }}
			/>
			<p class="geklickt">Suchen geklickt: {suchenGeklickt}</p>
		</div>
	</div>
{:else if welche === 'aktion'}
	<div class="admin-flaeche"><AktionsseitenVerwaltung /></div>
{:else if welche === 'tracker'}
	<div class="admin-flaeche"><TrackerVerwaltung /></div>
{:else if welche === 'passkey'}
	<div class="admin-flaeche"><PasskeyVerwaltung /></div>
{:else if welche === 'feedback'}
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

<style>
	/* Maße aus `plan/+page.svelte`: .sidebar */
	.leiste {
		width: 340px;
		height: 420px;
		background: var(--sidebar-bg);
		color: var(--text-1);
		display: flex;
		flex-direction: column;
		overflow: hidden;
	}
	/* Breite des Org-Admins (`--admin-width`). */
	.admin-flaeche { max-width: var(--admin-width); margin: 1rem auto; padding: 0 1rem; color: var(--text-1); }
	.leiste-inhalt { flex: 1; padding: 1rem; font-size: .85rem; color: var(--text-2); }
</style>
