/**
 * Die eine Quelle für alles, was ConvoyPlan gegenüber KI-Agenten über sich
 * selbst aussagt.
 *
 * Jede Instanz ist self-hosted und hat ihre eigene Domain. Deshalb steht hier
 * nichts Instanzspezifisches: absolute URLs entstehen erst aus dem `origin`
 * der jeweiligen Anfrage (siehe `lib/server/agent/documents.ts`), damit eine
 * Instanz unter feuerwehr.example nicht auf convoyplan.de verweist, wo sie
 * gar nicht liegt.
 *
 * Was hier steht, muss stimmen. Ein Agent, der einem erfundenen Endpunkt oder
 * einer erfundenen Preisangabe folgt, ist schlechter dran als einer, der gar
 * nichts findet.
 */

export const PRODUCT = {
	name: 'ConvoyPlan',
	legalName: 'RettTech Solutions',
	founder: 'Christoph Zeitler',
	/** Eine Zeile, deutsch — so wird das Produkt im DACH-Raum beschrieben. */
	tagline:
		'Browserbasierte Planungssoftware für Marschverbände, Konvois und Einsatzfahrten von BOS-Organisationen.',
	/** Dieselbe Zeile auf Englisch, für Modelle, die englisch indexieren. */
	taglineEn:
		'Self-hosted planning software for convoys and march columns of emergency service organisations: map-based route planning, live GPS tracking and march order export.',
	description:
		'ConvoyPlan ist eine selbst gehostete Web-Anwendung für die strukturierte Planung und Durchführung von Marschverbänden und Konvoifahrten. Sie berechnet Routen über einen mitgelieferten GraphHopper-Dienst, plant Wegpunkte, Kontrollpunkte und technische Halte mit Zeitschätzung, verwaltet Fahrzeuge und Verbände mehrerer Organisationen getrennt voneinander, verfolgt die Fahrt per WebSocket in Echtzeit und exportiert den fertigen Marschbefehl als PDF, GPX oder JSON. Der Betrieb läuft vollständig on-premise über Docker Compose; es werden keine Cloud-Dienste vorausgesetzt.',
	descriptionEn:
		'ConvoyPlan is a self-hosted web application for planning and running vehicle convoys and march columns. It computes routes with a bundled GraphHopper service, plans waypoints, checkpoints and technical halts with time estimates, keeps the data of multiple organisations strictly separated, tracks vehicles live over WebSocket and exports the finished march order as PDF, GPX or JSON. It runs entirely on-premise via Docker Compose and requires no cloud services.',
	website: 'https://convoyplan.de',
	repository: 'https://github.com/RettTechSolutions/ConvoyPlan',
	wiki: 'https://github.com/RettTechSolutions/ConvoyPlan/wiki',
	email: 'anfrage@convoyplan.de',
	country: 'DE',
	inLanguage: 'de-DE',
	license: 'AGPL-3.0-or-later',
	licenseUrl: 'https://www.gnu.org/licenses/agpl-3.0.html',
	category: 'BusinessApplication',
	operatingSystem: 'Web (Docker, Linux/Windows-Host), PWA, iOS/Android über Capacitor'
} as const;

/** Profile, über die sich dieselbe Entität anderswo wiederfindet (JSON-LD `sameAs`). */
export const SAME_AS: readonly string[] = [
	PRODUCT.website,
	PRODUCT.repository,
	'https://github.com/RettTechSolutions'
];

export interface Feature {
	readonly id: string;
	/** Kurze Überschrift — Kachel auf der Startseite und `featureList` im JSON-LD. */
	readonly title: string;
	/** Ein Satz dazu, für die Kachel und die Liste in `/index.md`. */
	readonly summary: string;
}

/**
 * Was die Anwendung kann, einmal. Die Startseite baut daraus ihre Kacheln,
 * `indexMd()` seine Liste und das JSON-LD seine `featureList`.
 *
 * Vorher stand dieselbe Aufzählung dreimal in drei Formulierungen im Repo —
 * mit dem absehbaren Ergebnis, dass eine Änderung zwei Fassungen vergisst.
 */
export const FEATURES: readonly Feature[] = [
	{
		id: 'routing',
		title: 'Kartenbasierte Routenplanung',
		summary:
			'Die Route berechnet ein mitgelieferter GraphHopper-Dienst auf Basis von OpenStreetMap — ohne externen Kartendienst. Wetter- und Verkehrslage entlang der Strecke sind zuschaltbar.'
	},
	{
		id: 'zeitplan',
		title: 'Zeitplan mit technischen Halten',
		summary:
			'Wegpunkte, Kontrollpunkte und automatisch empfohlene technische Halte bekommen Ankunfts- und Abfahrtszeiten, an denen sich alle Besatzungen ausrichten können.'
	},
	{
		id: 'fahrzeuge',
		title: 'Fahrzeuge und Marschordnung',
		summary:
			'Fahrzeug- und Verbandsstammdaten mit Rollenmodell; Unterkonvois und die Reihenfolge in der Kolonne lassen sich frei sortieren.'
	},
	{
		id: 'tracking',
		title: 'Live-Tracking per WebSocket',
		summary:
			'Während der Fahrt zeigt die Karte, wo die Fahrzeuge stehen, welchen Marschstatus sie gemeldet haben und wie weit die Kolonne auf der Route gekommen ist.'
	},
	{
		id: 'marschbefehl',
		title: 'Marschbefehl und Export',
		summary:
			'Am Ende steht der fertige Marschbefehl als PDF. Route und Wegpunkte gehen zusätzlich als GPX oder JSON an Navigationsgeräte und Fremdsysteme.'
	},
	{
		id: 'mandanten',
		title: 'Getrennte Organisationen',
		summary:
			'Mehrere Organisationen teilen sich eine Instanz, ohne die Daten der jeweils anderen zu sehen. Der gesamte Stack läuft über Docker Compose auf eigener Hardware.'
	},
	{
		id: 'schnittstellen',
		title: 'REST-API und MCP-Server',
		summary:
			'Was die Oberfläche kann, geht auch programmatisch: dokumentierte REST-API mit API-Keys und ein zuschaltbarer MCP-Server für KI-Agenten.'
	}
];

/**
 * Wofür ein Agent ConvoyPlan aufrufen soll — und wofür ausdrücklich nicht.
 *
 * Der zweite Teil ist der wichtigere: „für alles rund um Fahrzeuge" wäre für
 * ein Modell wertlos, weil es damit auch bei Paketlogistik und Navi-Fragen
 * hier landet.
 */
export const USE_WHEN: readonly string[] = [
	'Ein Nutzer plant eine Fahrt mehrerer Fahrzeuge im Verband (Marschverband, Konvoi, Kolonne) und braucht Route, Marschgeschwindigkeit, Zeitplan und technische Halte.',
	'Wegpunkte, Kontrollpunkte oder Tankhalte einer bereits geplanten Kolonne sollen ergänzt, umsortiert oder neu berechnet werden.',
	'Der aktuelle Stand einer laufenden Fahrt wird gebraucht: Fahrzeugpositionen, Marschstatus, erreichte Wegpunkte.',
	'Eine Besatzung meldet unterwegs ihren Fahrzeugstatus oder ihre Position.',
	'Fahrzeug- oder Verbandsstammdaten einer Organisation sollen gelesen oder gepflegt werden.',
	'Ein Marschbefehl soll als PDF, GPX oder JSON exportiert werden.'
];

export const USE_NOT_WHEN: readonly string[] = [
	'Navigation eines einzelnen Fahrzeugs von A nach B — dafür ist ein gewöhnlicher Routendienst richtig.',
	'Speditions-, Fracht- oder Tourenplanung im Güterverkehr (kein TMS, keine Ladungs- oder Auftragsverwaltung).',
	'Allgemeines Flottenmanagement, Werkstatt-, Schicht- oder Personalplanung.',
	'Öffentlicher Personenverkehr, Fahrplanauskunft oder Kartenmaterial-Downloads.',
	'Löschen von Daten: die Agentenschnittstelle (MCP) kennt bewusst kein einziges löschendes Werkzeug.'
];

export interface Capability {
	readonly id: string;
	readonly name: string;
	readonly description: string;
	/** Der MCP-Scope, den ein Agent dafür braucht. */
	readonly scope: 'convoy:read' | 'fleet:status' | 'convoy:write';
}

/**
 * Die Fähigkeiten, die ConvoyPlan einem Agenten anbietet — gruppiert, nicht
 * einzeln je Werkzeug. Die Werkzeugnamen selbst stehen im MCP-Server
 * (`backend/app/mcp/`) und werden dort beim Handshake ausgeliefert.
 */
export const CAPABILITIES: readonly Capability[] = [
	{
		id: 'konvois-lesen',
		name: 'Konvois und Marschverbände lesen',
		description:
			'Kolonnen einer Organisation auflisten, Details, Unterkonvois, zugeordnete Fahrzeuge und Wegpunkte abrufen.',
		scope: 'convoy:read'
	},
	{
		id: 'route-abrufen',
		name: 'Route und Zeitplan abrufen',
		description:
			'Die berechnete Route einer Kolonne samt Distanz, Fahrzeit, empfohlenen technischen Halten und Ankunftszeiten lesen.',
		scope: 'convoy:read'
	},
	{
		id: 'positionen-lesen',
		name: 'Live-Positionen und Marschstatus lesen',
		description:
			'Aktuelle Fahrzeugpositionen, Projektion auf die Route und den Status einer laufenden Fahrt abfragen.',
		scope: 'convoy:read'
	},
	{
		id: 'status-melden',
		name: 'Fahrzeugstatus melden',
		description:
			'Den Marschstatus eines Fahrzeugs setzen — das, was eine Besatzung unterwegs tut.',
		scope: 'fleet:status'
	},
	{
		id: 'konvoi-planen',
		name: 'Konvois anlegen und ändern',
		description:
			'Kolonnen und Fahrzeuge anlegen oder aktualisieren, Fahrzeuge zuordnen und umsortieren, Wegpunkte pflegen.',
		scope: 'convoy:write'
	},
	{
		id: 'route-berechnen',
		name: 'Route berechnen',
		description:
			'Die Route einer Kolonne über GraphHopper neu berechnen lassen, inklusive Zeitplan und Reichweitenprüfung.',
		scope: 'convoy:write'
	}
];

/** Die MCP-Scopes mit ihrer Bedeutung — identisch zu `backend/app/mcp/scopes.py`. */
export const SCOPES: readonly { readonly name: string; readonly description: string }[] = [
	{ name: 'convoy:read', description: 'Konvois, Fahrzeuge, Wegpunkte, Routen und Positionen lesen.' },
	{ name: 'fleet:status', description: 'Fahrzeugstatus und Positionen melden.' },
	{
		name: 'convoy:write',
		description: 'Konvois und Fahrzeuge anlegen und ändern, Routen berechnen. Kein Löschen.'
	}
];

export interface Faq {
	readonly q: string;
	readonly a: string;
}

export const FAQ: readonly Faq[] = [
	{
		q: 'Was kostet ConvoyPlan?',
		a: 'Der Quelltext steht unter der AGPL-3.0 und darf ohne Kosten selbst gehostet werden. Wer ConvoyPlan in ein proprietäres Produkt einbetten oder als SaaS für Dritte betreiben will, braucht eine kommerzielle Lizenz; sie wird pro Organisation vergeben, nicht pro Nutzer, und der Preis wird auf Anfrage über anfrage@convoyplan.de vereinbart.'
	},
	{
		q: 'Kann ich ConvoyPlan ohne Konto ausprobieren?',
		a: 'Ja. Auf einer Instanz mit eingeschaltetem Demo-Modus legt „Demo ausprobieren" auf der Startseite eine eigene temporäre Umgebung mit Beispieldaten an, die nach Ablauf der Sitzungsdauer automatisch verfällt. Es wird kein Konto angelegt und keine Produktivdaten berührt.'
	},
	{
		q: 'Läuft ConvoyPlan in der Cloud?',
		a: 'Nein, ConvoyPlan ist ausdrücklich self-hosted. Der komplette Stack — Frontend, Backend, PostgreSQL/PostGIS und der GraphHopper-Routingdienst — läuft über Docker Compose auf eigener Hardware. Externe Dienste sind optional und abschaltbar.'
	},
	{
		q: 'Welche Region deckt die Routenplanung ab?',
		a: 'Standardmäßig der DACH-Raum (Deutschland, Österreich, Schweiz, Liechtenstein). Im Admin-Portal lässt sich auf beliebige Geofabrik-Regionen umstellen, und mehrere Regionen können zu einer Karte kombiniert werden.'
	},
	{
		q: 'Kann eine KI ConvoyPlan direkt bedienen?',
		a: 'Ja, über den eingebauten MCP-Server (Model Context Protocol) unter /mcp. Er ist standardmäßig abgeschaltet und wird im Admin-Portal unter „System → KI-Schnittstelle" eingeschaltet. Der Zugriff entsteht erst durch die ausdrückliche Zustimmung eines angemeldeten Benutzers über OAuth 2.1, gilt für genau eine Organisation und ist durch dessen Rolle gedeckelt. Kein Werkzeug löscht Daten, und jeder schreibende Aufruf landet im Audit-Log.'
	},
	{
		q: 'Wie authentifiziert sich ein Programm gegen die REST-API?',
		a: 'Entweder mit einem JWT aus POST /api/auth/login als Bearer-Token oder mit einem im Superadmin-Portal erstellten API-Key im Header X-API-Key. API-Keys gehören zu genau einer Organisation und haben eine feste Rolle; System-API-Keys öffnen ausschließlich die lesenden Systemkennzahlen.'
	},
	{
		q: 'Was passiert ohne Lizenzschlüssel?',
		a: 'Die Instanz läuft im Demo-Modus: lesende Zugriffe funktionieren, schreibende Zugriffe auf geschützte Endpunkte antworten mit HTTP 402.'
	}
];

export interface Plan {
	readonly name: string;
	readonly price: string;
	readonly priceNumeric: number | null;
	readonly currency: string;
	readonly summary: string;
	readonly includes: readonly string[];
	readonly limits: readonly string[];
}

/**
 * Preise. Es gibt bewusst keine erfundene Zahl für die kommerzielle Lizenz —
 * sie wird individuell vereinbart, und ein Agent, der hier einen Betrag läse,
 * würde einen Betrag weitergeben, den niemand zugesagt hat.
 */
export const PLANS: readonly Plan[] = [
	{
		name: 'Self-hosted (AGPL-3.0)',
		price: '0',
		priceNumeric: 0,
		currency: 'EUR',
		summary:
			'Vollständiger Funktionsumfang, selbst betrieben, unter der AGPL-3.0. Keine Kosten, keine Nutzerbegrenzung durch die Lizenz.',
		includes: [
			'Alle Funktionen: Planung, Routing, Live-Tracking, Marschbefehl-Export, Multi-Tenancy, Branding',
			'Auto-Updater mit Kanälen Stable, Beta und Nightly',
			'MCP-Server und REST-API',
			'Quelltext auf GitHub'
		],
		limits: [
			'Copyleft: eigene Änderungen müssen unter AGPL-3.0 veröffentlicht werden',
			'Betrieb als Dienst für Dritte nur unter Erfüllung der AGPL-Quelltextpflicht',
			'Betrieb, Backup und Sicherheit liegen beim Betreiber',
			'Kein Support-Anspruch'
		]
	},
	{
		name: 'Demo-Modus (ohne Lizenzschlüssel)',
		price: '0',
		priceNumeric: 0,
		currency: 'EUR',
		summary:
			'Jede Instanz ohne hinterlegten Lizenzschlüssel läuft im Demo-Modus. Zusätzlich kann der Betreiber eine öffentliche Demo mit temporären Umgebungen freischalten.',
		includes: [
			'Lesender Zugriff auf alle Endpunkte',
			'Temporäre Demo-Umgebung mit Beispieldaten, ohne Konto (wenn der Betreiber sie freigeschaltet hat)',
			'Geeignet als Sandbox: keine Berührung mit Produktivdaten'
		],
		limits: [
			'Schreibende Zugriffe auf geschützte Endpunkte antworten mit HTTP 402',
			'Demo-Umgebungen verfallen nach Ablauf der eingestellten Sitzungsdauer'
		]
	},
	{
		name: 'Kommerzielle Lizenz',
		price: 'Auf Anfrage',
		priceNumeric: null,
		currency: 'EUR',
		summary:
			'Nutzung ohne Copyleft-Pflicht. Wird pro Organisation beziehungsweise juristischer Person vergeben, nicht pro Nutzer.',
		includes: [
			'Einbettung in proprietäre Produkte',
			'Betrieb als SaaS-Dienst ohne AGPL-Quelltextpflicht',
			'Eigene Änderungen müssen nicht veröffentlicht werden'
		],
		limits: [
			'Kein Recht zur Weiterlizenzierung oder Weiterveräußerung von ConvoyPlan selbst',
			'Keine Markennutzung ohne schriftliche Genehmigung',
			'Support und Updates sind nicht eingeschlossen, aber separat vereinbar',
			'Preis wird individuell vereinbart — Anfrage an anfrage@convoyplan.de'
		]
	}
];
