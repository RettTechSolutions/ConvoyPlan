<script lang="ts">
	import { untrack } from 'svelte';
	import { tutorialStore } from '$lib/stores/tutorial';

	type PlanTab = 'convoy' | 'fahrzeuge' | 'wegpunkte' | 'zeitplan' | 'export' | 'konto';

	let {
		slug,
		orgName = '',
		isDemo = false,
		isAdmin = false,
		onNavigate = (_tab: PlanTab) => {},
		onSidebar = (_open: boolean) => {},
	}: {
		slug: string;
		orgName?: string;
		isDemo?: boolean;
		isAdmin?: boolean;
		onNavigate?: (tab: PlanTab) => void;
		/** Öffnet/schließt die Seitenleiste (relevant auf Mobilgeräten). */
		onSidebar?: (open: boolean) => void;
	} = $props();

	interface Step {
		icon: string;
		title: string;
		/** Absätze (normaler Fließtext). */
		lead?: string;
		/** Aufzählungspunkte mit optionalem Fettteil vorne. */
		bullets?: { label?: string; text: string }[];
		/** Beim Anzeigen dieses Schritts automatisch in diesen Tab wechseln. */
		tab?: PlanTab;
		/**
		 * CSS-Selektor des UI-Elements, das per Spotlight hervorgehoben wird.
		 * Bei mehreren Treffern gewinnt der erste sichtbare (z. B. Desktop- vs.
		 * Mobil-Variante desselben Bedienelements). Ohne Selektor – oder wenn
		 * das Element nicht existiert – erscheint die Karte zentriert.
		 */
		target?: string;
		/** Seitenleiste für diesen Schritt öffnen (Mobil). */
		sidebar?: boolean;
		/** Nur in der Demo zeigen. */
		demoOnly?: boolean;
		/** Nur für Admins zeigen. */
		adminOnly?: boolean;
	}

	// Alle Schritte – Reihenfolge folgt dem natürlichen Planungs-Workflow.
	// Als $derived, damit demo-/orgname-abhängige Texte korrekt aktualisieren.
	const allSteps = $derived<Step[]>([
		{
			icon: '👋',
			title: 'Willkommen bei ConvoyPlan',
			lead: isDemo
				? 'Du bist in einer unverbindlichen Demo-Umgebung. ConvoyPlan plant Marschverbände vollständig: Route, Zeitplan, Fahrzeuge, Marschbefehl und Live-Tracking. Diese kurze Tour führt dich direkt durch die App.'
				: `Schön, dass du da bist${orgName ? `, ${orgName}` : ''}! ConvoyPlan plant Marschverbände vollständig: Route, Zeitplan, Fahrzeuge, Marschbefehl und Live-Tracking. Diese kurze Tour führt dich direkt durch die App.`,
			bullets: [
				{ text: 'Mit „Weiter“ hebt die Tour Schritt für Schritt das jeweilige Bedienelement in der App hervor.' },
				{ text: 'Du kannst die Tour jederzeit über „Überspringen“ beenden und später über das „?“ unten in der Seitenleiste erneut starten.' },
			],
		},
		{
			icon: '🚛',
			title: 'Marschverband anlegen & auswählen',
			tab: 'convoy',
			target: '[data-tour="convoy-selector"]',
			sidebar: true,
			lead: 'Ein Marschverband (Konvoi) ist die zentrale Einheit deiner Planung. Hier oben wählst du den aktiven Verband aus oder legst einen neuen an.',
			bullets: [
				{ label: '+ Neu', text: 'legt einen neuen Marschverband mit Name, Organisation und Startzeit an.' },
				{ label: 'Auswahl', text: 'über das Dropdown wechselst du zwischen mehreren Verbänden.' },
				{ label: 'Teilverbände', text: 'große Konvois lassen sich in untergeordnete Teilverbände (↳) gliedern.' },
			],
		},
		{
			icon: '⚙️',
			title: 'Plan-Bereich: Parameter des Verbands',
			tab: 'convoy',
			target: '[data-tour="plan-params"]',
			sidebar: true,
			lead: 'Der hervorgehobene Bereich zeigt alle Eckdaten des Verbands. Über „✎ Bearbeiten“ passt du sie an – sie fließen direkt in Routen- und Zeitberechnung ein.',
			bullets: [
				{ label: 'Tempo & Routenwahl', text: 'Geschwindigkeit innerorts/außerorts und Routenpräferenz.' },
				{ label: 'Abstände', text: 'Fahrzeugabstände innerorts / außerorts / Autobahn.' },
				{ label: 'Marschform', text: 'geschlossener Verband, Einzelgruppen oder individuelle Anreise.' },
				{ label: 'Führung & Funk', text: 'Ablaufpunkt, Ablaufführer und Funkgruppe.' },
				{ label: 'Lage & Auftrag', text: 'Freitextfelder für den Einsatzkontext.' },
			],
		},
		{
			icon: '🗺️',
			title: 'Karte: Start, Ziel & Wegpunkte setzen',
			tab: 'convoy',
			target: '[data-tour="map-actions"], [data-tour="map-actions-mobile"]',
			sidebar: false,
			lead: 'Die Route definierst du direkt auf der Karte. Aktiviere mit diesen Schaltflächen den passenden Modus und klicke dann auf die Karte – alternativ nutzt du die Ortssuche.',
			bullets: [
				{ label: '📍 Start', text: 'Startpunkt des Verbands setzen.' },
				{ label: '🏁 Ziel', text: 'Zielpunkt setzen.' },
				{ label: '➕ Wegpunkt', text: 'Zwischenstationen hinzufügen – mit Name, Typ und Haltezeit.' },
			],
		},
		{
			icon: '🧭',
			title: 'Route berechnen & Reichweite prüfen',
			tab: 'convoy',
			target: '[data-tour="route-actions"]',
			sidebar: true,
			lead: 'Mit „Route berechnen“ ermittelt ConvoyPlan Strecke, Fahrzeit und mehr für den gesamten Verband.',
			bullets: [
				{ label: 'Distanz & Dauer', text: 'werden nach der Berechnung angezeigt.' },
				{ label: 'Reichweiten-/Tankanalyse', text: 'erkennt nötige Tankstopps – Voraussetzung sind Fahrzeuge mit Verbrauchsdaten.' },
				{ label: 'Sperrungen', text: 'aktuelle Straßensperrungen lassen sich auf der Karte einblenden.' },
			],
		},
		{
			icon: '📑',
			title: 'Wegpunkte verwalten',
			tab: 'wegpunkte',
			target: '[data-tour="waypoints"]',
			sidebar: true,
			lead: 'Im Tab „Wegpunkte“ pflegst du alle Stationen der Route im Detail.',
			bullets: [
				{ label: 'Typen', text: 'Wegpunkt, Halt, Kontrollpunkt und technischer Halt (z. B. Tanken, Pause, Wartung).' },
				{ label: 'Haltezeiten', text: 'pro Station hinterlegbar – sie verschieben den Zeitplan automatisch.' },
				{ label: 'Reihenfolge', text: 'per Drag & Drop sortieren.' },
			],
		},
		{
			icon: '⏱️',
			title: 'Zeitplan & Kanalwechsel',
			tab: 'zeitplan',
			target: '[data-tour="schedule"]',
			sidebar: true,
			lead: 'Der Tab „Zeitplan“ zeigt nach der Routenberechnung Ankunfts- und Abfahrtszeiten für jeden Wegpunkt.',
			bullets: [
				{ label: 'Ankunft / Abfahrt', text: 'automatisch aus Tempo, Abständen und Haltezeiten berechnet.' },
				{ label: 'Kanalwechsel', text: 'geplante Funk-Kanalwechsel entlang der Strecke werden hier aufgelistet.' },
			],
		},
		{
			icon: '🚐',
			title: 'Fahrzeuge des Verbands',
			tab: 'fahrzeuge',
			target: '[data-tour="vehicles"]',
			sidebar: true,
			lead: 'Im Tab „Fahrzeuge“ verwaltest du, welche Fahrzeuge im Konvoi mitfahren.',
			bullets: [
				{ label: 'Anlegen', text: 'über „+ Neu“ Fahrzeuge mit Funktion im Konvoi erfassen.' },
				{ label: 'Reihenfolge', text: 'Position 1 = Spitzenführer, letztes Fahrzeug = Schließender.' },
				{ label: 'Verbrauch', text: 'Verbrauchs- und Tankdaten ermöglichen die Reichweitenanalyse.' },
			],
		},
		{
			icon: '📤',
			title: 'Export & Marschbefehl',
			tab: 'export',
			target: '[data-tour="export"]',
			sidebar: true,
			lead: 'Im Tab „Export“ gibst du die fertige Planung weiter.',
			bullets: [
				{ label: 'GPX / JSON', text: 'Route für Navigationsgeräte oder andere Systeme herunterladen.' },
				{ label: 'PDF-Marschbefehl', text: 'formatierter Marschbefehl mit allen Eckdaten zum Ausdrucken.' },
				{ label: 'Import', text: 'weiter unten: bestehende Wegpunkte/Routen aus Dateien einlesen (hinzufügen oder ersetzen).' },
			],
		},
		{
			icon: '🔴',
			title: 'Live-Tracking & Teilen',
			tab: 'export',
			target: '[data-tour="tracking"]',
			sidebar: true,
			lead: 'ConvoyPlan kann den Verband live auf einer Karte verfolgen und die Ansicht teilen.',
			bullets: [
				{ label: 'Tracking-Ansicht', text: 'zeigt die aktuelle Position des Verbands in Echtzeit.' },
				{ label: 'Freigabe-Links', text: 'teilbare Links – optional mit Passwort und QR-Code – für Externe.' },
			],
		},
		{
			icon: '🔐',
			title: 'Konto & Sicherheit',
			tab: 'konto',
			target: '[data-tour="konto"]',
			sidebar: true,
			lead: 'Im Tab „Konto“ verwaltest du deinen persönlichen Zugang.',
			bullets: [
				{ label: 'Passwort', text: 'jederzeit änderbar.' },
				{ label: 'MFA', text: 'Zwei-Faktor-Schutz per Authenticator-App (Authy, Google Authenticator …) aktivieren – dringend empfohlen.' },
			],
		},
		{
			icon: '🛠️',
			title: 'Admin-Bereich',
			adminOnly: true,
			target: '[data-tour="admin-link"]',
			sidebar: true,
			lead: 'Als Administrator erreichst du über „⚙ Admin“ oben in der Seitenleiste die Organisationsverwaltung.',
			bullets: [
				{ label: 'Mitglieder', text: 'Nutzer einladen und Rollen (Beobachter, Fahrer, Planer, Admin) vergeben.' },
				{ label: 'Leitstellen', text: 'Leitstellen und deren Zuständigkeitsbereiche pflegen.' },
				{ label: 'GPS-Freigaben', text: 'Standort-Freigaben für das Live-Tracking verwalten.' },
				{ label: 'Branding', text: 'eigenes Logo und Farben für die Organisation hinterlegen.' },
			],
		},
		{
			icon: '⏳',
			title: 'Deine Demo-Umgebung',
			demoOnly: true,
			target: '[data-tour="demo-banner"]',
			sidebar: true,
			lead: 'Diese Sitzung ist eine zeitlich begrenzte Demo. Das hervorgehobene Banner zeigt die verbleibende Laufzeit.',
			bullets: [
				{ text: 'Alle Daten sind temporär und werden nach Ablauf entfernt.' },
				{ text: 'Über „Vollversion anfragen“ kommst du zur unverbindlichen Anfrage für eine eigene Organisation.' },
			],
		},
		{
			icon: '✅',
			title: 'Geschafft – los geht’s!',
			target: '[data-tour="sidebar-footer"]',
			sidebar: true,
			lead: 'Das waren alle Bereiche. Ein paar Helfer findest du hier unten in der Seitenleiste:',
			bullets: [
				{ label: '☾ / ☀', text: 'zwischen hellem und dunklem Design wechseln.' },
				{ label: 'App installieren', text: 'ConvoyPlan als App (PWA) aufs Gerät holen.' },
				{ label: '? Hilfe', text: 'diese Tour jederzeit erneut starten.' },
				{ text: isDemo
					? 'Viel Spaß beim Ausprobieren der Demo!'
					: 'Du bist startklar – lege jetzt deinen ersten Marschverband an.' },
			],
		},
	]);

	const steps = $derived(
		allSteps.filter(
			(s) => (!s.demoOnly || isDemo) && (!s.adminOnly || isAdmin),
		),
	);

	let index = $state(0);
	const current = $derived(steps[Math.min(index, steps.length - 1)]);
	const isFirst = $derived(index === 0);
	const isLast = $derived(index >= steps.length - 1);

	// ── Spotlight: Zielelement suchen & vermessen ─────────────────────
	// Ein rAF-Loop verfolgt das Zielelement des aktuellen Schritts. So
	// folgt das Spotlight auch Tab-Wechseln, dem Einblenden der mobilen
	// Seitenleiste, Scrollen und Fenstergrößen-Änderungen.
	const PAD = 6; // Luft zwischen Element und Spotlight-Rahmen

	type Rect = { top: number; left: number; width: number; height: number };
	let targetRect = $state<Rect | null>(null);
	let cardEl = $state<HTMLElement | null>(null);
	let cardPos = $state<{ top: number; left: number } | null>(null);

	let currentEl: HTMLElement | null = null;
	// Frist, innerhalb derer das Ziel nach einem Schrittwechsel auftauchen
	// muss (Tab-Inhalt rendert, Sidebar fährt ein) – danach zentrierter Fallback.
	let searchUntil = 0;

	function isUsable(el: HTMLElement): boolean {
		if (!el.isConnected) return false;
		const r = el.getBoundingClientRect();
		// Breite/Höhe 0 = display:none; komplett links außerhalb = zugefahrene
		// mobile Seitenleiste (translateX(-100%)).
		return r.width > 0 && r.height > 0 && r.right > 0 && r.left < window.innerWidth;
	}

	function queryTarget(selector: string): HTMLElement | null {
		for (const el of document.querySelectorAll<HTMLElement>(selector)) {
			if (isUsable(el)) return el;
		}
		return null;
	}

	function frame() {
		const step = current;
		if (!step?.target) {
			currentEl = null;
			if (targetRect) targetRect = null;
			return;
		}
		if (!currentEl || !isUsable(currentEl)) {
			currentEl = queryTarget(step.target);
			currentEl?.scrollIntoView({ block: 'nearest' });
		}
		if (!currentEl) {
			if (performance.now() > searchUntil && targetRect) targetRect = null;
			return;
		}
		const r = currentEl.getBoundingClientRect();
		if (
			!targetRect ||
			Math.abs(targetRect.top - r.top) > 0.5 ||
			Math.abs(targetRect.left - r.left) > 0.5 ||
			Math.abs(targetRect.width - r.width) > 0.5 ||
			Math.abs(targetRect.height - r.height) > 0.5
		) {
			targetRect = { top: r.top, left: r.left, width: r.width, height: r.height };
		}
	}

	$effect(() => {
		let raf = requestAnimationFrame(function loop() {
			frame();
			raf = requestAnimationFrame(loop);
		});
		return () => cancelAnimationFrame(raf);
	});

	// Beim Schrittwechsel Tab/Seitenleiste vorbereiten und die Zielsuche
	// zurücksetzen.
	$effect(() => {
		const step = current;
		untrack(() => {
			currentEl = null;
			searchUntil = performance.now() + 800;
			if (step?.tab) onNavigate(step.tab);
			onSidebar(step?.sidebar ?? false);
		});
	});

	// Karte neben dem Spotlight platzieren: bevorzugt rechts, dann links,
	// darunter, darüber – sonst unten mittig. Immer in den Viewport geklemmt.
	$effect(() => {
		const rect = targetRect;
		const el = cardEl;
		void current; // Inhalt (und damit Kartengröße) hängt am Schritt
		if (!rect || !el) {
			cardPos = null;
			return;
		}
		const cw = el.offsetWidth;
		const ch = el.offsetHeight;
		const vw = window.innerWidth;
		const vh = window.innerHeight;
		const GAP = 12 + PAD;
		const M = 10;
		const clamp = (v: number, lo: number, hi: number) => Math.max(lo, Math.min(hi, v));
		let top: number;
		let left: number;
		if (rect.left + rect.width + GAP + cw <= vw - M) {
			left = rect.left + rect.width + GAP;
			top = clamp(rect.top - PAD, M, Math.max(M, vh - ch - M));
		} else if (rect.left - GAP - cw >= M) {
			left = rect.left - GAP - cw;
			top = clamp(rect.top - PAD, M, Math.max(M, vh - ch - M));
		} else if (rect.top + rect.height + GAP + ch <= vh - M) {
			top = rect.top + rect.height + GAP;
			left = clamp(rect.left, M, Math.max(M, vw - cw - M));
		} else if (rect.top - GAP - ch >= M) {
			top = rect.top - GAP - ch;
			left = clamp(rect.left, M, Math.max(M, vw - cw - M));
		} else {
			left = clamp((vw - cw) / 2, M, Math.max(M, vw - cw - M));
			top = Math.max(M, vh - ch - M);
		}
		cardPos = { top, left };
	});

	const anchored = $derived(!!(targetRect && cardPos));

	function next() {
		if (isLast) {
			finish();
		} else {
			index += 1;
		}
	}

	function prev() {
		if (!isFirst) index -= 1;
	}

	function skip() {
		finish();
	}

	function finish() {
		tutorialStore.finish(slug);
	}

	function onKeydown(e: KeyboardEvent) {
		if (e.key === 'Escape') {
			skip();
		} else if (e.key === 'ArrowRight') {
			next();
		} else if (e.key === 'ArrowLeft') {
			prev();
		}
	}
</script>

<svelte:window onkeydown={onKeydown} />

<!-- Blockiert Klicks in die App, solange die Tour läuft. Dimmt nur im
     zentrierten Fallback – beim Spotlight übernimmt dessen Schatten. -->
<div class="ot-blocker" class:dim={!anchored} role="presentation"></div>

{#if targetRect}
	<div
		class="ot-spotlight"
		style="top:{targetRect.top - PAD}px; left:{targetRect.left - PAD}px; width:{targetRect.width + PAD * 2}px; height:{targetRect.height + PAD * 2}px"
	></div>
{/if}

<div
	class="ot-card"
	class:anchored
	bind:this={cardEl}
	style={anchored && cardPos ? `top:${cardPos.top}px; left:${cardPos.left}px` : ''}
	role="dialog"
	aria-modal="true"
	aria-labelledby="ot-title"
>
	<button class="ot-skip" onclick={skip} title="Tour beenden">Überspringen ✕</button>

	<div class="ot-head">
		<span class="ot-icon" aria-hidden="true">{current.icon}</span>
		<h2 class="ot-title" id="ot-title">{current.title}</h2>
	</div>

	{#if current.lead}
		<p class="ot-lead">{current.lead}</p>
	{/if}

	{#if current.bullets?.length}
		<ul class="ot-bullets">
			{#each current.bullets as b}
				<li>
					{#if b.label}<strong>{b.label}</strong> — {/if}{b.text}
				</li>
			{/each}
		</ul>
	{/if}

	<div class="ot-progress" aria-hidden="true">
		{#each steps as _, i}
			<span class="ot-dot" class:active={i === index} class:done={i < index}></span>
		{/each}
	</div>

	<div class="ot-footer">
		<span class="ot-count">Schritt {index + 1} von {steps.length}</span>
		<div class="ot-nav">
			<button class="ot-btn ot-btn-secondary" onclick={prev} disabled={isFirst}>Zurück</button>
			<button class="ot-btn ot-btn-primary" onclick={next}>
				{isLast ? 'Fertig' : 'Weiter'}
			</button>
		</div>
	</div>
</div>

<style>
	/* Über allem – auch über dem PWA-Install-Banner (z-index 9000/9001). */
	.ot-blocker {
		position: fixed;
		inset: 0;
		z-index: 9998;
	}
	.ot-blocker.dim {
		background: rgba(0, 0, 0, 0.55);
		backdrop-filter: blur(2px);
	}
	.ot-spotlight {
		position: fixed;
		z-index: 9999;
		border-radius: 10px;
		/* Riesiger Schatten dimmt alles außerhalb des Ausschnitts. */
		box-shadow: 0 0 0 200vmax rgba(0, 0, 0, 0.55);
		outline: 2px solid var(--color-primary);
		outline-offset: 2px;
		pointer-events: none;
		transition: top 0.18s ease, left 0.18s ease, width 0.18s ease, height 0.18s ease;
	}
	.ot-card {
		position: fixed;
		z-index: 10000;
		width: min(360px, calc(100vw - 1.5rem));
		max-height: calc(100vh - 2rem);
		overflow-y: auto;
		background: var(--surface-1);
		color: var(--text-1);
		border: 1px solid var(--border);
		border-radius: 12px;
		box-shadow: 0 12px 40px rgba(0, 0, 0, 0.35);
		padding: 1.25rem 1.25rem 1rem;
		text-align: left;
		animation: ot-pop 0.18s ease-out;
	}
	/* Zentrierter Fallback (Willkommensschritt oder Ziel nicht vorhanden). */
	.ot-card:not(.anchored) {
		top: 50%;
		left: 50%;
		transform: translate(-50%, -50%);
	}
	@keyframes ot-pop {
		from { opacity: 0; }
		to   { opacity: 1; }
	}
	.ot-skip {
		position: absolute;
		top: 0.6rem;
		right: 0.6rem;
		background: none;
		border: none;
		color: var(--text-2);
		font-size: var(--text-sm);
		cursor: pointer;
		padding: 0.25rem 0.4rem;
		border-radius: 5px;
	}
	.ot-skip:hover { color: var(--text-1); background: var(--surface-2); }
	.ot-head {
		display: flex;
		align-items: center;
		gap: 0.6rem;
		margin: 0 0 0.6rem;
		padding-right: 6rem; /* Platz für den Überspringen-Button */
	}
	.ot-icon {
		font-size: 1.6rem;
		line-height: 1;
		flex-shrink: 0;
	}
	.ot-title {
		margin: 0;
		font-size: var(--text-lg);
		color: var(--text-1);
		line-height: 1.25;
	}
	.ot-lead {
		margin: 0 0 0.75rem;
		color: var(--text-2);
		font-size: var(--text-base);
		line-height: 1.5;
	}
	.ot-bullets {
		margin: 0 0 0.5rem;
		padding-left: 1.1rem;
		display: flex;
		flex-direction: column;
		gap: 0.4rem;
	}
	.ot-bullets li {
		color: var(--text-2);
		font-size: var(--text-base);
		line-height: 1.45;
	}
	.ot-bullets strong { color: var(--text-1); }
	.ot-progress {
		display: flex;
		justify-content: center;
		gap: 0.35rem;
		margin: 0.85rem 0 0.75rem;
		flex-wrap: wrap;
	}
	.ot-dot {
		width: 7px;
		height: 7px;
		border-radius: 50%;
		background: var(--border);
		transition: background 0.15s, transform 0.15s;
	}
	.ot-dot.done { background: var(--text-2); }
	.ot-dot.active { background: var(--color-primary); transform: scale(1.35); }
	.ot-footer {
		display: flex;
		align-items: center;
		justify-content: space-between;
		gap: 0.75rem;
		margin-top: 0.25rem;
	}
	.ot-count {
		color: var(--text-2);
		font-size: var(--text-sm);
	}
	.ot-nav { display: flex; gap: 0.5rem; }
	.ot-btn {
		padding: 0.5rem 1.05rem;
		border-radius: 6px;
		font-size: var(--text-base);
		font-weight: 600;
		cursor: pointer;
		border: 1px solid transparent;
	}
	.ot-btn-secondary {
		background: var(--surface-2);
		color: var(--text-1);
		border-color: var(--border);
	}
	.ot-btn-secondary:hover:not(:disabled) { background: var(--surface-1); }
	.ot-btn-secondary:disabled { opacity: 0.4; cursor: not-allowed; }
	.ot-btn-primary {
		background: var(--color-primary);
		color: #fff;
	}
	.ot-btn-primary:hover { background: var(--color-primary-hover); }
</style>
