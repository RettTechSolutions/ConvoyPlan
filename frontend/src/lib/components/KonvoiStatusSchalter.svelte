<script lang="ts">
	// Schaltet einen Konvoi aktiv bzw. schließt ihn ab. Was „aktiv" bewirkt,
	// steht in `$lib/konvoi/status`.
	import { convoysApi, type Convoy } from '$lib/api';
	import { istAktiv, statusLabel, type KonvoiStatus } from '$lib/konvoi/status';

	let {
		convoy,
		darf = true,
		onchange,
	}: {
		convoy: Convoy;
		/** Nur Planer und Admins dürfen den Status setzen (Backend: `require="write"`). */
		darf?: boolean;
		onchange?: (c: Convoy) => void;
	} = $props();

	let busy = $state(false);
	let fehler = $state('');

	const aktiv = $derived(istAktiv(convoy.status));

	async function setzen(status: KonvoiStatus) {
		if (status === 'completed' && !confirm(`„${convoy.name}" abschließen? Tracker in diesem Konvoi hören dann auf zu senden.`)) return;
		busy = true;
		fehler = '';
		try {
			onchange?.(await convoysApi.update(convoy.id, { status }));
		} catch (e) {
			fehler = e instanceof Error ? e.message : 'Status konnte nicht gesetzt werden';
		} finally {
			busy = false;
		}
	}
</script>

<div class="konvoi-status" data-testid="konvoi-status">
	<div class="zeile">
		<span class="label">Konvoi</span>
		<span class="pill" class:aktiv class:fertig={convoy.status === 'completed'} data-status={convoy.status}>
			{statusLabel(convoy.status)}
		</span>
	</div>
	{#if darf}
		{#if aktiv}
			<button class="btn btn-stop" onclick={() => setzen('completed')} disabled={busy}>⏹ Konvoi abschließen</button>
		{:else}
			<button class="btn btn-go" onclick={() => setzen('active')} disabled={busy}>
				▶ {convoy.status === 'completed' ? 'Konvoi wieder aktivieren' : 'Konvoi aktivieren'}
			</button>
			<p class="hint">Fest eingebaute Tracker senden erst, wenn der Konvoi aktiv ist.</p>
		{/if}
	{/if}
	{#if fehler}<p class="fehler" role="alert">{fehler}</p>{/if}
</div>

<style>
	.konvoi-status { display: flex; flex-direction: column; gap: .4rem; }
	.zeile { display: flex; align-items: center; justify-content: space-between; gap: .5rem; }
	.label { font-size: var(--text-xs); color: var(--text-muted); text-transform: uppercase; letter-spacing: .04em; }
	.pill { font-size: var(--text-xs); font-weight: 600; padding: .1rem .5rem; border-radius: 999px; background: var(--surface-2); border: 1px solid var(--border); color: var(--text-2); }
	.pill.aktiv { background: rgba(46, 204, 113, .18); border-color: #2ecc71; color: var(--text-1); }
	.pill.fertig { opacity: .75; }
	.btn { width: 100%; padding: .5rem 1rem; border-radius: 6px; font-weight: 600; cursor: pointer; font-size: var(--text-sm); }
	.btn:disabled { opacity: .5; cursor: not-allowed; }
	.btn-go { background: #27ae60; color: white; border: none; }
	.btn-go:hover:not(:disabled) { background: #219150; }
	.btn-stop { background: rgba(226, 61, 40, .3); border: 1px solid var(--color-primary); color: var(--text-1); }
	.hint { font-size: var(--text-xs); color: var(--text-muted); margin: 0; line-height: 1.4; }
	.fehler { font-size: var(--text-xs); color: var(--color-primary); margin: 0; }
</style>
