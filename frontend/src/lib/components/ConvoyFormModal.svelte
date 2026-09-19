<script lang="ts">
	/**
	 * Anlegen und Bearbeiten eines Marschverbands — ein Dialog für beides.
	 *
	 * Der Dialog ist ein **Gerüst aus drei Teilen**: Kopf, scrollender Rumpf,
	 * feststehender Fuß. Das ist kein Schmuck, sondern die Antwort auf zwei
	 * Fehler, die derselbe Aufbau erzeugt hatte, als das Formular noch ein
	 * einziger scrollender Kasten war:
	 *
	 * - Auf dem Telefon endete die Maske unterhalb des sichtbaren Bereichs;
	 *   *Speichern* und *Abbrechen* standen hinter der Adressleiste, und mit
	 *   ihnen der einzige Weg aus dem Dialog heraus.
	 * - Auf dem Schreibtisch mit niedrigem Fenster dasselbe: neun Felder
	 *   scrollen, bevor überhaupt ein Knopf auftaucht.
	 *
	 * Deshalb begrenzt `100dvh` (nicht `vh` — das misst auf iOS die *große*
	 * Anzeigefläche mit eingefahrener Adressleiste) die Höhe des Hintergrunds,
	 * und nur die Felder scrollen. Die Knöpfe sind immer da, wo man sie sucht.
	 */
	import type { Organization, RoadPreference } from '$lib/api';

	/** Die Felder, die beide Masken teilen. `organization*` nutzt nur „bearbeiten". */
	export interface ConvoyFormValues {
		name: string;
		organization: string;
		organization_id: string;
		start_time: string;
		speed_urban_kmh: number;
		speed_rural_kmh: number;
		road_preference: RoadPreference;
		spacing_urban_m: number;
		spacing_rural_m: number;
		spacing_motorway_m: number;
	}

	interface Props {
		modus: 'neu' | 'bearbeiten';
		/** Wird direkt gebunden — der Aufrufer hält den Zustand. */
		form: ConvoyFormValues;
		organizations?: Organization[];
		onSubmit: () => void;
		onClose: () => void;
		onDelete?: () => void;
	}

	let { modus, form, organizations = [], onSubmit, onClose, onDelete }: Props = $props();

	const titel = modus === 'neu' ? 'Neuer Marschverband' : 'Marschverband bearbeiten';
	const absenden = modus === 'neu' ? 'Erstellen & Punkte setzen →' : 'Speichern';

	function beiTaste(e: KeyboardEvent) {
		if (e.key === 'Escape') onClose();
	}
</script>

<svelte:window onkeydown={beiTaste} />

<!-- svelte-ignore a11y_click_events_have_key_events, a11y_no_static_element_interactions -->
<div class="modal-backdrop" onclick={onClose}>
	<!-- svelte-ignore a11y_click_events_have_key_events, a11y_no_static_element_interactions -->
	<div class="modal" role="dialog" aria-modal="true" aria-label={titel} onclick={(e) => e.stopPropagation()}>
		<header class="modal-head">
			<h2>{titel}</h2>
			<button type="button" class="modal-close" aria-label="Schließen" onclick={onClose}>✕</button>
		</header>

		<form onsubmit={(e) => { e.preventDefault(); onSubmit(); }}>
			<div class="modal-body">
				<label>Name *<input bind:value={form.name} required placeholder="z.B. KatS-Verband Bayern 1" /></label>

				{#if modus === 'bearbeiten'}
					<label>Organisation
						<select bind:value={form.organization_id} onchange={() => {
							const org = organizations.find((o) => o.id === form.organization_id);
							form.organization = org?.name ?? '';
						}}>
							<option value="">– keine –</option>
							{#each organizations as org}
								<option value={org.id}>{org.name}</option>
							{/each}
						</select>
					</label>
				{/if}

				<label>Startzeit (optional)<input type="datetime-local" bind:value={form.start_time} /></label>
				<label>Geschw. innerorts (km/h)<input type="number" bind:value={form.speed_urban_kmh} min="10" max="60" /></label>
				<label>Geschw. außerorts (km/h)<input type="number" bind:value={form.speed_rural_kmh} min="30" max="100" /></label>
				<label>Straßenpräferenz
					<select bind:value={form.road_preference}>
						<option value="standard">Standard (meidet Ortschaften, gut ausgebaute Straßen)</option>
						<option value="schnell">Schnellste Route</option>
						<option value="kuerzeste">Kürzeste Route</option>
						{#if form.road_preference === 'bundesstrasse' || form.road_preference === 'landstrasse'}
							<option value={form.road_preference}>Veraltet — bitte neu wählen</option>
						{/if}
					</select>
				</label>
				<label>Fahrzeugabstand Innerorts (m)<input type="number" bind:value={form.spacing_urban_m} min="5" max="200" /></label>
				<label>Fahrzeugabstand Außerorts (m)<input type="number" bind:value={form.spacing_rural_m} min="10" max="500" /></label>
				<label>Fahrzeugabstand Autobahn (m)<input type="number" bind:value={form.spacing_motorway_m} min="10" max="500" /></label>

				{#if modus === 'neu'}
					<p class="hint">Weitere Felder (Lage, Auftrag, Funkgruppe…) kannst du nach dem Erstellen im Plan-Tab ergänzen.</p>
				{/if}
			</div>

			<div class="modal-actions">
				{#if modus === 'bearbeiten' && onDelete}
					<button type="button" class="btn-danger" onclick={onDelete}>Löschen</button>
				{/if}
				<button type="button" onclick={onClose}>Abbrechen</button>
				<button type="submit" class="btn-primary">{absenden}</button>
			</div>
		</form>
	</div>
</div>

<style>
	/* `100dvh` statt `vh`: iOS Safari rechnet `vh` gegen die Anzeigefläche mit
	   eingefahrener Adressleiste — ein Dialog über die volle `vh`-Höhe endet
	   also hinter der Leiste. `vh` bleibt als Rückfall für Browser ohne `dvh`. */
	.modal-backdrop {
		position: fixed;
		inset: 0;
		/* Ausdrücklich, nicht aus der globalen Regel geliehen: mit `content-box`
		   käme das Polster zur Höhe hinzu und der Dialog ragte genau darum
		   wieder hinaus. */
		box-sizing: border-box;
		height: 100vh;
		height: 100dvh;
		background: rgba(0, 0, 0, .5);
		display: flex;
		align-items: center;
		justify-content: center;
		padding: 1rem;
		padding-bottom: calc(1rem + env(safe-area-inset-bottom));
		z-index: 100;
	}

	.modal {
		background: white;
		color: #333;
		border-radius: 8px;
		width: 100%;
		max-width: 420px;
		/* Nie höher als der Hintergrund, der seinerseits die sichtbare Fläche ist. */
		max-height: 100%;
		display: flex;
		flex-direction: column;
		overflow: hidden;
		box-shadow: 0 12px 48px rgba(0, 0, 0, .45);
	}

	.modal-head {
		display: flex;
		align-items: center;
		gap: .75rem;
		padding: 1rem 1.5rem;
		border-bottom: 1px solid #e5e5e5;
		flex-shrink: 0;
	}
	.modal-head h2 { margin: 0; font-size: 1.15rem; flex: 1; }
	.modal-close {
		background: none;
		border: none;
		color: #888;
		cursor: pointer;
		font-size: 1.1rem;
		line-height: 1;
		padding: .25rem;
		min-width: 44px;
		min-height: 44px;
	}
	.modal-close:hover { color: #333; }

	/* Der Rumpf ist das einzige, was scrollt. `min-height: 0` muss sein, sonst
	   wächst das Formular im Flex-Container über seine Grenze hinaus. */
	form { display: flex; flex-direction: column; min-height: 0; flex: 1; }
	.modal-body {
		flex: 1;
		min-height: 0;
		overflow-y: auto;
		/* Kein Weiterreichen des Scrollens an die Seite darunter — sonst
		   verschiebt sich auf dem Telefon die Karte hinter dem Dialog. */
		overscroll-behavior: contain;
		-webkit-overflow-scrolling: touch;
		padding: 1.25rem 1.5rem;
	}

	label {
		display: flex;
		flex-direction: column;
		gap: .25rem;
		margin-bottom: .75rem;
		font-size: .85rem;
		font-weight: 600;
	}
	input, select {
		padding: .5rem;
		border: 1px solid #ccc;
		border-radius: 4px;
		font-size: 1rem;
		font-family: inherit;
		background: white;
		color: #111;
		width: 100%;
	}
	input:focus, select:focus { outline: none; border-color: var(--color-primary); box-shadow: 0 0 0 3px rgba(226, 61, 40, .12); }
	.hint { margin: .25rem 0 0; font-size: .8rem; color: #666; }

	.modal-actions {
		display: flex;
		justify-content: flex-end;
		align-items: center;
		gap: .5rem;
		flex-wrap: wrap;
		flex-shrink: 0;
		padding: .85rem 1.5rem;
		border-top: 1px solid #e5e5e5;
		background: #f8f9fa;
	}
	.modal-actions button {
		padding: .5rem 1rem;
		border-radius: 4px;
		cursor: pointer;
		border: 1px solid #ccc;
		background: white;
		color: #333;
		font-size: .88rem;
		min-height: 44px;
	}
	.modal-actions .btn-danger { background: #b91c1c; color: white; border-color: #b91c1c; margin-right: auto; }
	.modal-actions .btn-danger:hover { background: #991b1b; }
	.modal-actions .btn-primary { background: #0F1B24; color: white; border-color: #0F1B24; font-weight: 600; }
	.modal-actions .btn-primary:hover { background: #1a2f42; }

	@media (max-width: 560px) {
		.modal-backdrop { padding: .5rem; padding-bottom: calc(.5rem + env(safe-area-inset-bottom)); }
		.modal-head { padding: .85rem 1rem; }
		.modal-body { padding: 1rem; }
		.modal-actions { padding: .75rem 1rem; }
		/* Genug Platz für drei Knöpfe ist auf 360px nicht da: nebeneinander
		   würden sie umbrechen und der Fuß wüchse in den Rumpf hinein. */
		.modal-actions button { flex: 1 1 auto; }
		.modal-actions .btn-danger { flex: 0 0 auto; }
	}
</style>
