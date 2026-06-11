<script lang="ts">
	import { tutorialStore } from '$lib/stores/tutorial';

	type PlanTab = 'convoy' | 'fahrzeuge' | 'wegpunkte' | 'zeitplan' | 'export' | 'konto';

	let {
		slug,
		orgName = '',
		isDemo = false,
		isAdmin = false,
		onNavigate = (_tab: PlanTab) => {},
	}: {
		slug: string;
		orgName?: string;
		isDemo?: boolean;
		isAdmin?: boolean;
		onNavigate?: (tab: PlanTab) => void;
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
				? 'Du bist in einer unverbindlichen Demo-Umgebung. ConvoyPlan plant Marschverbände vollständig: Route, Zeitplan, Fahrzeuge, Marschbefehl und Live-Tracking. Diese kurze Tour zeigt dir in wenigen Schritten alle Bereiche.'
				: `Schön, dass du da bist${orgName ? `, ${orgName}` : ''}! ConvoyPlan plant Marschverbände vollständig: Route, Zeitplan, Fahrzeuge, Marschbefehl und Live-Tracking. Diese kurze Tour zeigt dir alle Bereiche.`,
			bullets: [
				{ text: 'Mit „Weiter“ gehst du Schritt für Schritt durch die App.' },
				{ text: 'Du kannst die Tour jederzeit über „Überspringen“ beenden und später über das „?“ unten in der Seitenleiste erneut starten.' },
			],
		},
		{
			icon: '🚛',
			title: 'Marschverband anlegen & auswählen',
			tab: 'convoy',
			lead: 'Ein Marschverband (Konvoi) ist die zentrale Einheit deiner Planung. Oben in der Seitenleiste wählst du den aktiven Verband aus oder legst einen neuen an.',
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
			lead: 'Im Tab „Plan“ siehst du alle Eckdaten des Verbands. Über „✎ Bearbeiten“ passt du sie an – sie fließen direkt in Routen- und Zeitberechnung ein.',
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
			lead: 'Die Route definierst du direkt auf der Karte. Aktiviere den passenden Modus und klicke dann auf die Karte – alternativ nutzt du die Ortssuche.',
			bullets: [
				{ label: '📍 Start', text: 'Startpunkt des Verbands setzen.' },
				{ label: '🏁 Ziel', text: 'Zielpunkt setzen.' },
				{ label: '➕ Wegpunkt', text: 'Zwischenstationen hinzufügen – mit Name, Typ und Haltezeit.' },
				{ text: 'Auf dem Handy findest du dieselben Schaltflächen oben in der Leiste.' },
			],
		},
		{
			icon: '🧭',
			title: 'Route berechnen & Reichweite prüfen',
			tab: 'convoy',
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
			lead: 'Im Tab „Fahrzeuge“ verwaltest du, welche Fahrzeuge im Konvoi mitfahren.',
			bullets: [
				{ label: 'Anlegen', text: 'Fahrzeuge mit Funktion im Konvoi erfassen.' },
				{ label: 'Reihenfolge', text: 'Position 1 = Spitzenführer, letztes Fahrzeug = Schließender.' },
				{ label: 'Verbrauch', text: 'Verbrauchs- und Tankdaten ermöglichen die Reichweitenanalyse.' },
			],
		},
		{
			icon: '📤',
			title: 'Export & Marschbefehl',
			tab: 'export',
			lead: 'Im Tab „Export“ gibst du die fertige Planung weiter.',
			bullets: [
				{ label: 'GPX / JSON', text: 'Route für Navigationsgeräte oder andere Systeme herunterladen.' },
				{ label: 'PDF-Marschbefehl', text: 'formatierter Marschbefehl mit allen Eckdaten zum Ausdrucken.' },
				{ label: 'Import', text: 'bestehende Wegpunkte/Routen aus Dateien einlesen (hinzufügen oder ersetzen).' },
			],
		},
		{
			icon: '🔴',
			title: 'Live-Tracking & Teilen',
			tab: 'export',
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
			lead: 'Diese Sitzung ist eine zeitlich begrenzte Demo. Das Banner oben in der Seitenleiste zeigt die verbleibende Laufzeit.',
			bullets: [
				{ text: 'Alle Daten sind temporär und werden nach Ablauf entfernt.' },
				{ text: 'Über „Vollversion anfragen“ kommst du zur unverbindlichen Anfrage für eine eigene Organisation.' },
			],
		},
		{
			icon: '✅',
			title: 'Geschafft – los geht’s!',
			lead: 'Das waren alle Bereiche. Ein paar Helfer findest du noch unten in der Seitenleiste:',
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

	// Beim Wechsel des Schritts ggf. den passenden Tab im Hintergrund öffnen,
	// damit der erklärte Bereich sichtbar ist, sobald die Tour endet.
	$effect(() => {
		if (current?.tab) onNavigate(current.tab);
	});

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

<div class="ot-backdrop" role="presentation">
	<div
		class="ot-card"
		role="dialog"
		aria-modal="true"
		aria-labelledby="ot-title"
	>
		<button class="ot-skip" onclick={skip} title="Tour beenden">Überspringen ✕</button>

		<div class="ot-icon" aria-hidden="true">{current.icon}</div>
		<h2 class="ot-title" id="ot-title">{current.title}</h2>

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
</div>

<style>
	.ot-backdrop {
		position: fixed;
		inset: 0;
		background: rgba(0, 0, 0, 0.55);
		backdrop-filter: blur(2px);
		z-index: 2000;
		display: flex;
		align-items: center;
		justify-content: center;
		padding: 1rem;
	}
	.ot-card {
		position: relative;
		width: 100%;
		max-width: 460px;
		max-height: calc(100vh - 2rem);
		overflow-y: auto;
		background: var(--surface-1);
		color: var(--text-1);
		border: 1px solid var(--border);
		border-radius: 12px;
		box-shadow: 0 12px 40px rgba(0, 0, 0, 0.35);
		padding: 1.75rem 1.5rem 1.25rem;
		text-align: center;
		animation: ot-pop 0.18s ease-out;
	}
	@keyframes ot-pop {
		from { opacity: 0; transform: translateY(8px) scale(0.98); }
		to   { opacity: 1; transform: translateY(0) scale(1); }
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
	.ot-icon {
		font-size: 2.6rem;
		line-height: 1;
		margin-bottom: 0.5rem;
	}
	.ot-title {
		margin: 0 0 0.6rem;
		font-size: var(--text-lg);
		color: var(--text-1);
	}
	.ot-lead {
		margin: 0 0 0.85rem;
		color: var(--text-2);
		font-size: var(--text-base);
		line-height: 1.5;
	}
	.ot-bullets {
		text-align: left;
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
		margin: 1rem 0 0.85rem;
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
