/**
 * Der Seitenkatalog: welche öffentlichen Seiten es gibt, wie sie heißen und
 * welches Markdown-Zwilling zu welcher HTML-Seite gehört.
 *
 * Eine Liste statt mehrerer: Sitemap, llms.txt, die Markdown-Aushandlung in
 * `hooks.server.ts` und die Navigationshinweise im Agentenmodus lesen alle
 * hier. Kommt eine Seite dazu, taucht sie überall auf, oder nirgends.
 */

export interface PageEntry {
	/** Pfad der HTML-Seite, immer mit führendem Schrägstrich. */
	readonly path: string;
	readonly title: string;
	readonly summary: string;
	/** Pfad des Markdown-Zwillings. */
	readonly markdown: string;
	/** Gewicht in der Sitemap. */
	readonly priority: string;
	/** Schlagworte für die Suche unter /ask. */
	readonly keywords: readonly string[];
}

export const PAGES: readonly PageEntry[] = [
	{
		path: '/',
		title: 'ConvoyPlan — Marschplanung für Einsatzorganisationen',
		summary:
			'Einstieg in die Instanz: Anmeldung über den Organisations-Code, Demo-Zugang und Überblick über ConvoyPlan.',
		markdown: '/index.md',
		priority: '1.0',
		keywords: ['start', 'anmeldung', 'login', 'organisation', 'demo', 'übersicht', 'convoyplan']
	},
	{
		path: '/about',
		title: 'Über ConvoyPlan',
		summary:
			'Was ConvoyPlan ist, für wen es gebaut wurde, wer dahintersteht und wie die Software betrieben wird.',
		markdown: '/about.md',
		priority: '0.8',
		keywords: ['über', 'about', 'hersteller', 'anbieter', 'unternehmen', 'wer', 'impressum', 'zweck']
	},
	{
		path: '/pricing',
		title: 'Preise und Lizenzen',
		summary:
			'AGPL-3.0 zum Selbsthosten, Demo-Modus und kommerzielle Lizenz — mit Leistungen und Grenzen je Modell.',
		markdown: '/pricing.md',
		priority: '0.8',
		keywords: ['preis', 'preise', 'kosten', 'lizenz', 'pricing', 'agpl', 'kommerziell', 'abo']
	},
	{
		path: '/developers',
		title: 'Entwickler und Agenten',
		summary:
			'REST-API, API-Keys, OpenAPI-Beschreibung, MCP-Server, Scopes, Sandbox und der Weg zum ersten Aufruf.',
		markdown: '/developers.md',
		priority: '0.9',
		keywords: [
			'entwickler',
			'developer',
			'api',
			'rest',
			'openapi',
			'mcp',
			'agent',
			'integration',
			'sdk',
			'sandbox',
			'token'
		]
	},
	{
		path: '/docs',
		title: 'Dokumentation',
		summary:
			'Wegweiser in die Dokumentation: Benutzerhandbuch, Installation, API-Beschreibung, MCP-Server und Betrieb.',
		markdown: '/docs.md',
		priority: '0.8',
		keywords: ['doku', 'dokumentation', 'docs', 'handbuch', 'anleitung', 'wiki', 'hilfe']
	},
	{
		path: '/contact',
		title: 'Kontakt',
		summary:
			'Wie man den Hersteller erreicht: Lizenzanfragen, Sicherheitsmeldungen, Fehlerberichte und Mitwirkung.',
		markdown: '/contact.md',
		priority: '0.7',
		keywords: ['kontakt', 'contact', 'e-mail', 'email', 'support', 'anfrage', 'melden']
	},
	{
		path: '/privacy',
		title: 'Datenschutz',
		summary:
			'Welche Daten ConvoyPlan verarbeitet, wer dafür verantwortlich ist und welche DSGVO-Werkzeuge eingebaut sind.',
		markdown: '/privacy.md',
		priority: '0.7',
		keywords: ['datenschutz', 'privacy', 'dsgvo', 'gdpr', 'daten', 'löschen', 'auskunft']
	},
	{
		path: '/terms',
		title: 'Nutzungsbedingungen',
		summary:
			'Unter welchen Bedingungen ConvoyPlan genutzt werden darf: AGPL, kommerzielle Lizenz, Gewährleistung und die KI-Schnittstelle.',
		markdown: '/terms.md',
		priority: '0.7',
		keywords: [
			'nutzungsbedingungen',
			'terms',
			'agb',
			'lizenz',
			'license',
			'agpl',
			'gewährleistung',
			'haftung'
		]
	},
	{
		path: '/status',
		title: 'Systemstatus',
		summary: 'Öffentliche Statusseite dieser Instanz: Erreichbarkeit der Dienste und Komponenten.',
		markdown: '/status.md',
		priority: '0.5',
		keywords: ['status', 'verfügbarkeit', 'störung', 'uptime', 'health']
	}
];

/** Die Seite zu einem Pfad, ohne abschließenden Schrägstrich-Wirrwarr. */
export function pageFor(pathname: string): PageEntry | undefined {
	const clean = pathname !== '/' && pathname.endsWith('/') ? pathname.slice(0, -1) : pathname;
	return PAGES.find((p) => p.path === clean);
}

/** Die Seiten, die nur mit eingeschalteter Agenten-Auskunft existieren. */
export const DISCOVERY_ONLY_PAGES: readonly string[] = [
	'/about',
	'/pricing',
	'/developers',
	'/docs',
	'/contact',
	'/privacy',
	'/terms'
];
