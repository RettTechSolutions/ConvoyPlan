<script lang="ts">
	import { connectionLook, type ConnectionState } from '$lib/tracking/connection';

	interface Props {
		state: ConnectionState;
		/** Nur der Punkt, ohne Text — für die schmale Leiste auf dem Telefon. */
		dotOnly?: boolean;
	}
	let { state, dotOnly = false }: Props = $props();

	const look = $derived(connectionLook(state));
</script>

{#if dotOnly}
	<span class="ws-dot {look.tone}" title={look.title} aria-label={look.label}></span>
{:else}
	<div class="ws-indicator" title={look.title}>
		<span class="ws-dot {look.tone}"></span>
		<span class="ws-label">{look.label}</span>
	</div>
{/if}

<style>
	.ws-indicator { display: flex; align-items: center; gap: .35rem; font-size: var(--text-xs); color: var(--text-muted); flex-shrink: 0; }
	.ws-dot { width: 8px; height: 8px; border-radius: 50%; background: #e74c3c; flex-shrink: 0; display: inline-block; }
	.ws-dot.live { background: #27ae60; animation: pulse 2s infinite; }
	.ws-dot.pending { background: #f1c40f; animation: pulse 1.2s infinite; }
	.ws-dot.down { background: #e74c3c; }
	.ws-label { white-space: nowrap; }

	@keyframes pulse {
		0%, 100% { opacity: 1; }
		50% { opacity: .4; }
	}
</style>
