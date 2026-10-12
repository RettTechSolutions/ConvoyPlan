<script lang="ts">
	/**
	 * Das eine Kontextmenü der Anwendung — eingehängt im Wurzel-Layout, geöffnet
	 * über `$lib/kontextmenue/menue.ts`. Bedienung wie ein Menü des Systems:
	 * Pfeiltasten, Pos1/Ende, Anfangsbuchstabe, Enter, Esc; Klick daneben,
	 * Scrollen oder Fensterwechsel schließen es.
	 */
	import { tick } from 'svelte';
	import { menue, kurzmeldung, schliessen, istAktion, type Aktion } from './menue';

	let el = $state<HTMLDivElement | null>(null);
	let pos = $state({ left: 0, top: 0 });

	const RAND = 6;

	$effect(() => {
		const m = $menue;
		if (!m) return;
		pos = { left: m.x, top: m.y };
		tick().then(() => {
			if (!el) return;
			// In den Schirm schieben: rechts/unten zu knapp → zur anderen Seite klappen.
			const r = el.getBoundingClientRect();
			const vw = window.innerWidth;
			const vh = window.innerHeight;
			let left = m.x;
			let top = m.y;
			if (left + r.width > vw - RAND) left = Math.max(RAND, m.x - r.width);
			if (top + r.height > vh - RAND) top = Math.max(RAND, Math.min(m.y - r.height, vh - RAND - r.height));
			pos = { left, top };
			// Den Fokus braucht das Menü immer — sonst gingen die Pfeiltasten an die
			// Seite. Auf den ersten Eintrag nur per Tastatur (siehe `perTastatur`).
			if (m.perTastatur) knoepfe()[0]?.focus({ preventScroll: true });
			else el.focus({ preventScroll: true });
		});
	});

	function knoepfe(): HTMLButtonElement[] {
		return el ? [...el.querySelectorAll<HTMLButtonElement>('button[role^="menuitem"]:not([disabled])')] : [];
	}

	function zu(fokusZurueck: boolean) {
		const ausloeser = $menue?.ausloeser;
		schliessen();
		if (fokusZurueck && ausloeser?.isConnected) ausloeser.focus({ preventScroll: true });
	}

	async function ausfuehren(a: Aktion) {
		if (a.aus) return;
		zu(false);
		try {
			await a.aktion();
		} catch (err) {
			// Die Seiten melden ihre Fehler selbst; hier nur nicht verschlucken.
			console.error('Kontextmenü:', err);
		}
	}

	function onKeydown(e: KeyboardEvent) {
		const liste = knoepfe();
		const i = liste.indexOf(document.activeElement as HTMLButtonElement);
		const fokus = (n: number) => liste[(n + liste.length) % liste.length]?.focus();
		switch (e.key) {
			case 'ArrowDown': fokus(i + 1); break;
			case 'ArrowUp': fokus(i < 0 ? -1 : i - 1); break;
			case 'Home': fokus(0); break;
			case 'End': fokus(-1); break;
			case 'Escape': zu(true); break;
			case 'Tab': zu(true); break;
			default:
				if (e.key.length === 1 && /\S/.test(e.key)) {
					const b = e.key.toLowerCase();
					const treffer = liste.findIndex((k, n) => n > i && k.dataset.label?.toLowerCase().startsWith(b));
					const rund = treffer >= 0 ? treffer : liste.findIndex((k) => k.dataset.label?.toLowerCase().startsWith(b));
					if (rund >= 0) fokus(rund);
					else return;
				} else return;
		}
		e.preventDefault();
		e.stopPropagation();
	}

	function draussen(e: Event) {
		if (!$menue) return;
		if (el && e.target instanceof Node && el.contains(e.target)) return;
		zu(false);
	}
</script>

<svelte:window
	onpointerdown={draussen}
	onwheel={draussen}
	onscrollcapture={draussen}
	onresize={() => $menue && zu(false)}
	onblur={() => $menue && zu(false)}
/>

{#if $menue}
	<div
		bind:this={el}
		class="kontextmenue"
		role="menu"
		tabindex="-1"
		aria-orientation="vertical"
		style="left:{pos.left}px;top:{pos.top}px"
		onkeydown={onKeydown}
		oncontextmenu={(e) => e.preventDefault()}
	>
		{#each $menue.eintraege as e, n (n)}
			{#if 'trenner' in e}
				<div class="trenner" role="separator"></div>
			{:else if 'titel' in e}
				<div class="titel" role="presentation">{e.titel}</div>
			{:else if istAktion(e)}
				<button
					type="button"
					role={e.art === 'schalter' ? 'menuitemcheckbox' : e.art === 'auswahl' ? 'menuitemradio' : 'menuitem'}
					aria-checked={e.art ? !!e.an : undefined}
					class:gefahr={e.gefahr}
					disabled={!!e.aus}
					title={typeof e.aus === 'string' ? e.aus : undefined}
					data-label={e.label}
					onclick={() => ausfuehren(e)}
				>
					<span class="icon" aria-hidden="true">{#if e.art}{e.an ? (e.art === 'auswahl' ? '●' : '✓') : ''}{:else}{e.icon ?? ''}{/if}</span>
					<span class="text">{e.label}</span>
				</button>
			{/if}
		{/each}
	</div>
{/if}

{#if $kurzmeldung}
	<div class="kurzmeldung" role="status">{$kurzmeldung}</div>
{/if}

<style>
	.kontextmenue {
		position: fixed;
		z-index: 10000;
		min-width: 12rem;
		max-width: min(22rem, calc(100vw - 12px));
		max-height: calc(100vh - 12px);
		overflow-y: auto;
		padding: .3rem 0;
		background: var(--surface-1, #fff);
		color: var(--text-1, #1a2332);
		border: 1px solid var(--border, #dde1e7);
		border-radius: 8px;
		box-shadow: 0 8px 28px rgba(0, 0, 0, .35);
		font-family: system-ui, sans-serif;
		font-size: var(--text-sm, .82rem);
		outline: none;
		user-select: none;
	}
	button {
		display: flex;
		align-items: center;
		gap: .55rem;
		width: 100%;
		padding: .42rem .9rem .42rem .6rem;
		border: 0;
		background: none;
		color: inherit;
		font: inherit;
		text-align: left;
		cursor: pointer;
		white-space: nowrap;
	}
	button:hover:not([disabled]),
	button:focus-visible {
		background: var(--surface-2, #f0f2f5);
		outline: none;
	}
	button[disabled] {
		opacity: .45;
		cursor: default;
	}
	button.gefahr {
		color: #e74c3c;
	}
	.icon {
		width: 1.2rem;
		text-align: center;
		flex: none;
	}
	.text {
		overflow: hidden;
		text-overflow: ellipsis;
	}
	.trenner {
		height: 1px;
		margin: .3rem 0;
		background: var(--border, #dde1e7);
	}
	.titel {
		padding: .3rem .9rem .35rem;
		color: var(--text-2, #4a5568);
		font-size: var(--text-xs, .72rem);
		font-weight: 600;
		white-space: nowrap;
		overflow: hidden;
		text-overflow: ellipsis;
	}
	.kurzmeldung {
		position: fixed;
		left: 50%;
		bottom: 1.5rem;
		transform: translateX(-50%);
		z-index: 10001;
		padding: .5rem .9rem;
		border-radius: 6px;
		background: rgba(20, 28, 40, .92);
		color: #fff;
		font: var(--text-sm, .82rem) system-ui, sans-serif;
		pointer-events: none;
	}
</style>
