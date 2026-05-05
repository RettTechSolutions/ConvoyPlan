<script lang="ts">
	import { lageApi, type LageLayer } from '$lib/api';
	import { lageLayers } from '$lib/stores/lage';

	interface Props {
		convoyId: string;
		onLayersChange?: (layers: LageLayer[]) => void;
	}

	let { convoyId, onLayersChange }: Props = $props();

	let showAddForm = $state(false);
	let newName = $state('');
	let newColor = $state('#e74c3c');
	let newGeoJson = $state('');
	let parseError = $state('');

	async function load() {
		const layers = await lageApi.list(convoyId);
		lageLayers.set(layers);
		onLayersChange?.(layers);
	}

	async function addLayer() {
		parseError = '';
		let geojsonData: Record<string, unknown>;
		try {
			geojsonData = JSON.parse(newGeoJson);
		} catch {
			parseError = 'Ungültiges GeoJSON';
			return;
		}
		await lageApi.create(convoyId, {
			name: newName,
			geojson_data: geojsonData,
			color: newColor,
			visible: true,
		});
		newName = '';
		newGeoJson = '';
		newColor = '#e74c3c';
		showAddForm = false;
		await load();
	}

	async function toggleVisible(layer: LageLayer) {
		await lageApi.update(convoyId, layer.id, { visible: !layer.visible });
		await load();
	}

	async function deleteLayer(layerId: string) {
		await lageApi.delete(convoyId, layerId);
		await load();
	}

	$effect(() => {
		if (convoyId) load();
	});
</script>

<div class="lage-panel">
	<div class="panel-header">
		<strong>Lagedaten</strong>
		<button class="btn-add" onclick={() => (showAddForm = !showAddForm)}>
			{showAddForm ? '✕' : '+ Layer'}
		</button>
	</div>

	{#if showAddForm}
		<div class="add-form">
			<input placeholder="Layername" bind:value={newName} />
			<div class="color-row">
				<label>Farbe</label>
				<input type="color" bind:value={newColor} />
			</div>
			<textarea
				placeholder='GeoJSON einfügen (FeatureCollection oder Feature)…'
				bind:value={newGeoJson}
				rows={5}
			></textarea>
			{#if parseError}<p class="err">{parseError}</p>{/if}
			<button class="btn-save" onclick={addLayer} disabled={!newName || !newGeoJson}>
				Layer hinzufügen
			</button>
		</div>
	{/if}

	<ul class="layer-list">
		{#each $lageLayers as layer}
			<li class="layer-item" class:hidden={!layer.visible}>
				<span class="color-dot" style="background:{layer.color}"></span>
				<span class="layer-name">{layer.name}</span>
				<div class="layer-actions">
					<button onclick={() => toggleVisible(layer)} title={layer.visible ? 'Verstecken' : 'Anzeigen'}>
						{layer.visible ? '👁' : '👁‍🗨'}
					</button>
					<button onclick={() => deleteLayer(layer.id)} title="Löschen">✕</button>
				</div>
			</li>
		{/each}
		{#if $lageLayers.length === 0 && !showAddForm}
			<li class="empty">Noch keine Lagedaten</li>
		{/if}
	</ul>
</div>

<style>
	.lage-panel {
		background: rgba(26, 39, 68, 0.92);
		color: white;
		border-radius: 8px;
		padding: .75rem;
		backdrop-filter: blur(4px);
		min-width: 220px;
	}
	.panel-header {
		display: flex;
		justify-content: space-between;
		align-items: center;
		margin-bottom: .5rem;
	}
	.panel-header strong { font-size: .88rem; }
	.btn-add {
		padding: .2rem .5rem;
		background: rgba(255,255,255,.15);
		border: 1px solid rgba(255,255,255,.25);
		color: white;
		border-radius: 4px;
		font-size: .78rem;
		cursor: pointer;
	}
	.add-form { display: flex; flex-direction: column; gap: .4rem; margin-bottom: .5rem; }
	.add-form input, .add-form textarea {
		padding: .35rem;
		border: none;
		border-radius: 4px;
		background: rgba(255,255,255,.12);
		color: white;
		font-size: .82rem;
		resize: vertical;
	}
	.add-form input::placeholder, .add-form textarea::placeholder { color: rgba(255,255,255,.4); }
	.color-row { display: flex; align-items: center; gap: .5rem; font-size: .82rem; }
	.color-row input[type="color"] { width: 36px; height: 28px; border: none; border-radius: 4px; cursor: pointer; }
	.btn-save {
		padding: .35rem;
		background: #27ae60;
		color: white;
		border: none;
		border-radius: 4px;
		cursor: pointer;
		font-size: .82rem;
	}
	.btn-save:disabled { opacity: .5; cursor: not-allowed; }
	.err { color: #e74c3c; font-size: .78rem; margin: 0; }
	.layer-list { list-style: none; padding: 0; margin: 0; }
	.layer-item {
		display: flex;
		align-items: center;
		gap: .4rem;
		padding: .3rem 0;
		border-bottom: 1px solid rgba(255,255,255,.08);
		font-size: .82rem;
	}
	.layer-item.hidden { opacity: .5; }
	.color-dot { width: 12px; height: 12px; border-radius: 50%; flex-shrink: 0; }
	.layer-name { flex: 1; }
	.layer-actions { display: flex; gap: .25rem; }
	.layer-actions button {
		background: none;
		border: none;
		color: rgba(255,255,255,.7);
		cursor: pointer;
		font-size: .85rem;
		padding: 0 .15rem;
	}
	.empty { font-size: .8rem; color: rgba(255,255,255,.4); padding: .3rem 0; }
</style>
