<script lang="ts">
	import { tick } from 'svelte';
	import QRCode from 'qrcode';

	/**
	 * QR-Code zu einer Adresse, dazu Download und Ausdruck.
	 *
	 * Der Code entsteht im Browser aus `url` — nichts wird gespeichert, nichts
	 * nachgeladen. Wer das Bild bekommt, bekommt genau das, was auch in der
	 * Adresszeile steht: ein Passwort gehört deshalb weder in `url` noch auf das
	 * Blatt, sondern wird getrennt mitgeteilt.
	 */
	let {
		url,
		filename,
		printTitle,
		printSubtitle = '',
		printNote = '',
		size = 200,
		dark = false,
	}: {
		url: string;
		/** Dateiname des Downloads, ohne Endung. */
		filename: string;
		printTitle: string;
		printSubtitle?: string;
		printNote?: string;
		/** Kantenlänge der Anzeige in Pixeln; der Code selbst ist immer 600 px groß. */
		size?: number;
		/** Knöpfe für eine dunkle Fläche einfärben. */
		dark?: boolean;
	} = $props();

	let dataUrl = $state('');
	let error = $state('');
	let printing = $state(false);

	$effect(() => {
		const target = url;
		let gültig = true;
		QRCode.toDataURL(target, { width: 600, margin: 1 })
			.then((d) => { if (gültig) { dataUrl = d; error = ''; } })
			.catch((e: Error) => { if (gültig) error = e.message; });
		return () => { gültig = false; };
	});

	function download() {
		if (!dataUrl) return;
		const a = document.createElement('a');
		a.href = dataUrl;
		a.download = `${filename}.png`;
		a.click();
	}

	async function print() {
		if (!dataUrl) return;
		printing = true;
		await tick();
		window.print();
	}

	// Das Blatt wird an <body> gehängt, damit der Druckstil den Rest der Seite
	// per `display: none` wegnehmen kann: bliebe sie nur unsichtbar, stünde ihr
	// Layout weiter im Dokument und hinge als leere Folgeseiten hinter dem
	// Ausdruck. Ein zweites Fenster wäre die Alternative — das fängt je nach
	// Browser ein Popup-Blocker ab.
	function portal(node: HTMLElement) {
		document.body.appendChild(node);
		return { destroy: () => node.remove() };
	}
</script>

<svelte:window onafterprint={() => (printing = false)} />

<div class="qs">
	<div class="qs-code" style="--qs-size: {size}px">
		{#if dataUrl}
			<img src={dataUrl} alt="QR-Code für {url}" />
		{:else if error}
			<p class="qs-error">{error}</p>
		{:else}
			<p class="qs-wait">Zeichne…</p>
		{/if}
	</div>
	<div class="qs-actions">
		<button class="qs-btn" class:dark onclick={download} disabled={!dataUrl}>PNG herunterladen</button>
		<button class="qs-btn" class:dark onclick={print} disabled={!dataUrl}>Drucken</button>
	</div>
</div>

{#if printing}
	<div class="qs-print cp-print-sheet" use:portal>
		<h1>{printTitle}</h1>
		{#if printSubtitle}<p class="qs-print-role">{printSubtitle}</p>{/if}
		<img src={dataUrl} alt="" />
		<p class="qs-print-url">{url}</p>
		{#if printNote}<p class="qs-print-note">{printNote}</p>{/if}
	</div>
{/if}

<style>
	.qs { display: flex; flex-direction: column; align-items: center; gap: .6rem; }
	.qs-code {
		background: white; padding: .5rem; border-radius: 6px; border: 1px solid #ddd;
		width: calc(var(--qs-size) + 1rem + 2px); height: calc(var(--qs-size) + 1rem + 2px);
		box-sizing: border-box; display: flex; align-items: center; justify-content: center;
	}
	.qs-code img { display: block; width: var(--qs-size); height: var(--qs-size); }
	.qs-wait, .qs-error { margin: 0; font-size: .85rem; color: #777; text-align: center; }
	.qs-error { color: #b91c1c; }

	.qs-actions { display: flex; gap: .5rem; flex-wrap: wrap; justify-content: center; }
	.qs-btn {
		padding: .5rem .9rem; border-radius: 5px; border: 1.5px solid #ccc;
		background: white; color: #333; cursor: pointer; font-size: .85rem;
		font-family: inherit; white-space: nowrap;
	}
	.qs-btn:hover:not(:disabled) { background: #f0f0f0; }
	.qs-btn:disabled { opacity: .5; cursor: not-allowed; }
	.qs-btn.dark { background: rgba(255, 255, 255, .08); border-color: rgba(255, 255, 255, .25); color: #e8edf2; }
	.qs-btn.dark:hover:not(:disabled) { background: rgba(255, 255, 255, .16); }

	/* Auf dem Schirm gibt es das Blatt nicht; im Druck ist es das Einzige. */
	.qs-print { display: none; }
	@media print {
		:global(body > *:not(.cp-print-sheet)) { display: none !important; }
		/* Auch `html`: das dunkle Design der Tracking-Ansicht sitzt dort und
		   stünde sonst als schwarze Fläche unter dem Blatt, sobald jemand
		   Hintergrundgrafiken mitdruckt. */
		:global(html), :global(body) { background: #fff !important; color-scheme: light; }
		.qs-print {
			display: block; width: 100%; padding: 1.5cm 1cm; box-sizing: border-box;
			text-align: center; color: #000; font-family: inherit;
		}
		.qs-print h1 { font-size: 20pt; margin: 0 0 .3cm; }
		.qs-print-role { font-size: 12pt; margin: 0 0 .8cm; }
		.qs-print img { width: 9cm; height: 9cm; }
		.qs-print-url { font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 13pt; margin: .6cm 0 0; word-break: break-all; }
		.qs-print-note { font-size: 10pt; margin: .8cm auto 0; max-width: 12cm; }
	}
</style>
