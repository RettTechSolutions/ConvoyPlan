/**
 * Die Texte und Dokumente, die ConvoyPlan für Maschinen ausliefert.
 *
 * Jede Funktion bekommt einen `AgentContext` und baut daraus ein fertiges
 * Dokument. Der Kontext trägt die tatsächliche Lage der Instanz — welche
 * Domain, ob der MCP-Server läuft, ob eine Demo freigeschaltet ist —, damit
 * hier nichts angekündigt wird, was es auf dieser Instanz nicht gibt. Ein
 * Agent, der einem toten Endpunkt folgt, ist schlechter dran als einer, der
 * gar keinen findet.
 */
import {
	PRODUCT,
	USE_WHEN,
	USE_NOT_WHEN,
	CAPABILITIES,
	SCOPES,
	FAQ,
	PLANS,
	FEATURES
} from '$lib/agent/facts';
import { PAGES, pageFor } from '$lib/agent/pages';

export interface AgentContext {
	/** Origin dieser Instanz, ohne abschließenden Schrägstrich. */
	readonly base: string;
	/** Ob der MCP-Server auf dieser Instanz gerade montiert ist. */
	readonly mcpEnabled: boolean;
	/** Ob der Betreiber den Demo-Zugang freigeschaltet hat. */
	readonly demoEnabled: boolean;
	/** Version dieser Instanz, falls das Backend sie verraten hat. */
	readonly version: string;
}

const line = (s: string) => s.replace(/\s+/g, ' ').trim();

/** Ein Abschnitt, der nur erscheint, wenn die Instanz ihn auch einlöst. */
const when = (cond: boolean, text: string) => (cond ? text : '');

// ── llms.txt ────────────────────────────────────────────────────────────

export function llmsTxt(ctx: AgentContext): string {
	const { base } = ctx;
	return `# ${PRODUCT.name}

> ${line(PRODUCT.tagline)}
> ${line(PRODUCT.taglineEn)}

${line(PRODUCT.description)}

Diese Instanz läuft unter ${base}. ${PRODUCT.name} ist self-hosted: jede Organisation
betreibt ihre eigene Instanz unter ihrer eigenen Domain. Alle Pfade in dieser Datei sind
deshalb relativ zu ${base} zu lesen und gelten nicht für andere Instanzen.

## Wann ein Agent ConvoyPlan aufrufen soll

${USE_WHEN.map((u) => `- ${line(u)}`).join('\n')}

## Wann nicht

${USE_NOT_WHEN.map((u) => `- ${line(u)}`).join('\n')}

## Wie ein Agent ConvoyPlan aufruft

1. **Bevorzugt: MCP.** Der Model-Context-Protocol-Server unter \`${base}/mcp\`
   (Streamable HTTP) liefert Konvois, Fahrzeuge, Wegpunkte, Routen und Status als Werkzeuge.
   Zugang entsteht über OAuth 2.1 mit der Zustimmung eines angemeldeten Benutzers und gilt
   für genau eine Organisation. Kein Werkzeug löscht Daten.
   Status auf dieser Instanz: **${ctx.mcpEnabled ? 'eingeschaltet' : 'abgeschaltet'}**${when(!ctx.mcpEnabled, ' — der Betreiber schaltet ihn im Admin-Portal unter „System → KI-Schnittstelle" ein')}.
2. **REST-API.** \`${base}/api/…\` mit \`Authorization: Bearer <JWT>\` aus
   \`POST /api/auth/login\` oder mit \`X-API-Key: <key>\`. Maschinenlesbare Beschreibung
   der öffentlichen Endpunkte: \`${base}/openapi.json\`.
3. **Ohne Zugangsdaten** sind nur die öffentlichen Endpunkte erreichbar
   (Status, Version, Branding, Freigabe-Links und Tracking-Slugs).

Details zum Anmelden: [auth.md](${base}/auth.md).

## Seiten

${PAGES.map((p) => `- [${p.title}](${base}${p.path}): ${line(p.summary)} — Markdown: ${base}${p.markdown}`).join('\n')}

## Für Agenten

- [agents.md](${base}/agents.md): Kurzanleitung, wann und wie ConvoyPlan aufzurufen ist
- [auth.md](${base}/auth.md): Zugangsdaten beschaffen, Fehlerbilder, Widerruf
- [api.md](${base}/api.md): REST-Oberfläche, Fehlercodes, Grenzen
- [pricing.md](${base}/pricing.md): Lizenzmodelle als Markdown
- [openapi.json](${base}/openapi.json): OpenAPI 3.1 der öffentlichen Endpunkte
- [Agent Card](${base}/.well-known/agent-card.json) · [Agent Skills](${base}/.well-known/agent-skills/index.json) · [ARD-Katalog](${base}/.well-known/ard.json) · [MCP Server Card](${base}/.well-known/mcp/server-card.json) · [API-Katalog](${base}/.well-known/api-catalog)
- Abschnittsweise: [${base}/api/llms.txt](${base}/api/llms.txt) · [${base}/docs/llms.txt](${base}/docs/llms.txt) · [${base}/developers/llms.txt](${base}/developers/llms.txt)
- Langfassung: [llms-full.txt](${base}/llms-full.txt)

## Sandbox

${
	ctx.demoEnabled
		? `Diese Instanz hat den Demo-Zugang freigeschaltet: \`${base}/demo\` legt eine eigene
temporäre Umgebung mit Beispieldaten an — ohne Konto, ohne Berührung mit Produktivdaten,
sie verfällt nach Ablauf der eingestellten Sitzungsdauer. Das ist die richtige Umgebung, um
schreibende Aufrufe auszuprobieren.`
		: `Auf dieser Instanz ist der öffentliche Demo-Zugang nicht freigeschaltet. Eine Sandbox
entsteht sonst durch eine zweite, lokal gestartete Instanz (\`docker compose up\`) ohne
Lizenzschlüssel; sie läuft im Demo-Modus und beantwortet schreibende Zugriffe mit HTTP 402.`
}

## Hersteller

${PRODUCT.legalName} (${PRODUCT.founder}), ${PRODUCT.country}. Kontakt: ${PRODUCT.email}.
Produktseite: ${PRODUCT.website} · Quelltext: ${PRODUCT.repository} · Wiki: ${PRODUCT.wiki}
Lizenz: ${PRODUCT.license} oder kommerzielle Lizenz.

## Grenzen

- Die Oberfläche und alle Inhalte sind deutschsprachig (${PRODUCT.inLanguage}).
- Routing deckt standardmäßig den DACH-Raum ab; der Betreiber kann weitere Regionen laden.
- Ohne Lizenzschlüssel läuft die Instanz im Demo-Modus: lesen ja, schreiben HTTP 402.
- Es gibt keine löschenden Agentenwerkzeuge, und keinen Zugriff auf Instanz-Administration.
`;
}

export function llmsFullTxt(ctx: AgentContext): string {
	return [
		llmsTxt(ctx),
		'\n---\n',
		agentsMd(ctx),
		'\n---\n',
		authMd(ctx),
		'\n---\n',
		apiMd(ctx),
		'\n---\n',
		pricingMd(ctx),
		'\n---\n',
		aboutMd(ctx),
		'\n---\n',
		privacyMd(ctx)
	].join('\n');
}

/** Abschnittsweise llms.txt, damit ein Agent nicht das ganze Handbuch ziehen muss. */
export function sectionLlmsTxt(section: 'api' | 'docs' | 'developers', ctx: AgentContext): string {
	const { base } = ctx;
	if (section === 'api') {
		return `# ${PRODUCT.name} — API

> REST-Oberfläche dieser Instanz (${base}).

- [OpenAPI 3.1 der öffentlichen Endpunkte](${base}/openapi.json)
- [api.md](${base}/api.md): Endpunkte, Authentifizierung, Fehlercodes, Grenzen
- [auth.md](${base}/auth.md): Token beschaffen und widerrufen
- [API-Katalog (RFC 9727)](${base}/.well-known/api-catalog)

Basis-URL: \`${base}/api\`. Authentifizierung: \`Authorization: Bearer <JWT>\` oder
\`X-API-Key: <key>\`. Ein Aufruf ohne Zugangsdaten auf einen geschützten Endpunkt
antwortet mit 401 und einem \`WWW-Authenticate\`-Header, der auf die
Resource-Metadaten zeigt.
`;
	}
	if (section === 'docs') {
		return `# ${PRODUCT.name} — Dokumentation

> Wegweiser in die Anwenderdokumentation.

- [Dokumentationsübersicht](${base}/docs) — Markdown: ${base}/docs.md
- [Benutzerhandbuch](${PRODUCT.wiki}/Benutzerhandbuch)
- [Erste Schritte](${PRODUCT.wiki}/Erste-Schritte)
- [Konvoi-Planung](${PRODUCT.wiki}/Konvoi-Planung)
- [Live-Tracking](${PRODUCT.wiki}/Live-Tracking)
- [Marschbefehl-Export](${PRODUCT.wiki}/Marschbefehl-Export)
- [Rollen und Berechtigungen](${PRODUCT.wiki}/Rollen)
- [Installation und Setup](${PRODUCT.wiki}/Installation-und-Setup)
- [MCP-Server](${PRODUCT.wiki}/MCP-Server)
- [Sicherheit und Datenschutz](${PRODUCT.wiki}/Sicherheit-und-Datenschutz)
`;
	}
	return `# ${PRODUCT.name} — Entwickler

> Alles, was für eine Integration gebraucht wird.

- [Entwicklerportal](${base}/developers) — Markdown: ${base}/developers.md
- [OpenAPI 3.1](${base}/openapi.json)
- [auth.md](${base}/auth.md) · [api.md](${base}/api.md) · [agents.md](${base}/agents.md)
- [MCP Server Card](${base}/.well-known/mcp/server-card.json) — MCP-Endpunkt: \`${base}/mcp\`
  (${ctx.mcpEnabled ? 'auf dieser Instanz eingeschaltet' : 'auf dieser Instanz abgeschaltet'})
- [Agent Skills](${base}/.well-known/agent-skills/index.json) · [Agent Card](${base}/.well-known/agent-card.json)
- Quelltext und Issues: ${PRODUCT.repository}

Scopes der Agentenschnittstelle:

${SCOPES.map((s) => `- \`${s.name}\` — ${s.description}`).join('\n')}
`;
}

// ── Markdown-Zwillinge ──────────────────────────────────────────────────

export function indexMd(ctx: AgentContext): string {
	const { base } = ctx;
	return `# ${pageFor('/')?.title ?? PRODUCT.name}

${line(PRODUCT.tagline)}

${line(PRODUCT.description)}

## Auf dieser Instanz anmelden

Der Einstieg läuft über den **Organisations-Code** der eigenen Organisation. Wer ihn
eingibt, landet auf der Anmeldemaske dieser Organisation (\`${base}/o/<code>/login\`).
Ein Code wird von der Organisation vergeben und steht nicht öffentlich zur Verfügung.
${when(ctx.demoEnabled, `\nOhne Konto führt \`${base}/demo\` in eine eigene temporäre Demo-Umgebung mit Beispieldaten.`)}

## Was ConvoyPlan kann

${FEATURES.map((f) => `- **${f.title}** — ${line(f.summary)}`).join('\n')}

## Weiter

${PAGES.filter((p) => p.path !== '/')
	.map((p) => `- [${p.title}](${base}${p.path}) — ${line(p.summary)}`)
	.join('\n')}
- [llms.txt](${base}/llms.txt) — Einstieg für KI-Agenten
- [openapi.json](${base}/openapi.json) — OpenAPI der öffentlichen Endpunkte

## Hersteller

${PRODUCT.legalName} (${PRODUCT.founder}) · ${PRODUCT.email} · ${PRODUCT.website}
Lizenz: ${PRODUCT.license} oder kommerzielle Lizenz.
`;
}

export function aboutMd(ctx: AgentContext): string {
	const { base } = ctx;
	return `# Über ${PRODUCT.name}

${line(PRODUCT.description)}

## Für wen

ConvoyPlan ist für Organisationen gebaut, die regelmäßig mehrere Fahrzeuge im Verband
bewegen: Feuerwehren, Hilfsorganisationen, Katastrophenschutz, THW-Ortsverbände,
Rettungsdienste und vergleichbare BOS-Stellen im deutschsprachigen Raum. Der Unterschied
zu einem gewöhnlichen Routendienst liegt im Verband: eine Kolonne fährt langsamer als ein
einzelnes Fahrzeug, braucht Kontrollpunkte, technische Halte und einen Zeitplan, an dem
sich alle Besatzungen ausrichten, und sie muss während der Fahrt nachvollziehbar bleiben.

## Wie es betrieben wird

ConvoyPlan ist ausdrücklich **self-hosted**. Der komplette Stack läuft über Docker Compose
auf eigener Hardware: das SvelteKit-Frontend, das FastAPI-Backend, PostgreSQL mit PostGIS,
ein eigener GraphHopper-Routingdienst und Caddy als Reverse Proxy mit automatischem
TLS-Zertifikat. Es wird kein Cloud-Dienst vorausgesetzt; Kartendaten kommen aus
OpenStreetMap-Extrakten, die auf der eigenen Maschine liegen. Externe Datenquellen für
Wetter und Verkehr sind optional und lassen sich abschalten. Ein Auto-Updater rollt neue
Images in den Kanälen Stable, Beta und Nightly aus.

Diese Instanz erreichst du unter ${base}. Betreiber dieser Instanz ist die Organisation,
die sie installiert hat — nicht der Hersteller.

## Wer dahintersteht

Entwickelt und herausgegeben von **${PRODUCT.legalName}** (${PRODUCT.founder}) in
Deutschland. Der Quelltext liegt offen unter der ${PRODUCT.license} auf GitHub; wer
ConvoyPlan in ein proprietäres Produkt einbetten oder als SaaS betreiben will, braucht
zusätzlich eine kommerzielle Lizenz.

- Produktseite: ${PRODUCT.website}
- Quelltext: ${PRODUCT.repository}
- Dokumentation: ${PRODUCT.wiki}
- Kontakt: ${PRODUCT.email}

## Weiter

- [Preise und Lizenzen](${base}/pricing)
- [Entwickler und Agenten](${base}/developers)
- [Kontakt](${base}/contact)
- [Datenschutz](${base}/privacy)
- [Nutzungsbedingungen](${base}/terms)
`;
}

export function contactMd(ctx: AgentContext): string {
	const { base } = ctx;
	return `# Kontakt

${PRODUCT.name} wird von **${PRODUCT.legalName}** (${PRODUCT.founder}) in Deutschland
entwickelt und herausgegeben. Alle Anliegen laufen über eine Adresse; sie wird werktags
gelesen und in der Regel innerhalb weniger Werktage beantwortet.

**E-Mail: ${PRODUCT.email}**

## Welches Anliegen wohin

| Anliegen | Weg | Hinweis |
| --- | --- | --- |
| Kommerzielle Lizenz, Preisanfrage | ${PRODUCT.email}, Betreff „ConvoyPlan Commercial License" | Bitte Anwendungsfall, Organisation und ungefähre Nutzerzahl angeben |
| Sicherheitslücke melden | ${PRODUCT.email} | Verantwortungsvoll und nicht öffentlich; bitte Version/Commit und eine Reproduktion angeben. Coordinated Disclosure, Details bitte erst nach Abstimmung veröffentlichen |
| Fehlerbericht, Funktionswunsch | ${PRODUCT.repository}/issues | Öffentlich; bitte keine personenbezogenen Daten aus Produktivsystemen hineinschreiben |
| Frage zur Bedienung | ${PRODUCT.wiki} | Benutzerhandbuch und FAQ beantworten die meisten Fragen |
| Probleme mit **dieser** Instanz | Betreiber dieser Instanz | ${base} wird nicht vom Hersteller betrieben, sondern von der Organisation, die sie installiert hat. Kontoanlage, Zugangsdaten und Datenbestand liegen dort |
| Betroffenenrechte nach DSGVO | Betreiber dieser Instanz | Der Betreiber ist Verantwortlicher im Sinne der DSGVO, nicht der Hersteller |

## Kanäle

- Produktseite: ${PRODUCT.website}
- Quelltext und Issue-Tracker: ${PRODUCT.repository}
- Sicherheitsrichtlinie: ${PRODUCT.repository}/blob/main/SECURITY.md
- Statusseite dieser Instanz: ${base}/status

Es gibt bewusst kein Kontaktformular und keine Telefon-Hotline: eine E-Mail ist für beide
Seiten nachvollziehbar, und ein Agent kann sie ohne Formularfelder verfassen.
`;
}

export function privacyMd(ctx: AgentContext): string {
	const { base } = ctx;
	return `# Datenschutz

ConvoyPlan ist self-hosted. Das ist für den Datenschutz die wichtigste Eigenschaft der
Software: **Verantwortlicher im Sinne der DSGVO ist die Organisation, die diese Instanz
betreibt** — nicht ${PRODUCT.legalName} als Hersteller. Wer für ${base} eine Auskunft,
Berichtigung oder Löschung verlangen will, wendet sich an den Betreiber dieser Instanz.
Der Hersteller hat auf den Datenbestand dieser Instanz keinen Zugriff.

## Welche Daten die Software verarbeitet

- **Benutzerkonten**: Name, E-Mail-Adresse, Rolle in der Organisation, Passwort-Hash und —
  falls eingerichtet — ein verschlüsseltes MFA-Geheimnis.
- **Organisationsdaten**: Organisations-Code, Branding, Leitstellen, Fahrzeugstammdaten.
- **Planungsdaten**: Konvois, Wegpunkte, Kontrollpunkte, Routen und Zeitpläne.
- **Standortdaten**: Während einer Fahrt gemeldete Fahrzeugpositionen mit Zeitstempel und
  Marschstatus. Das sind die datenschutzrechtlich empfindlichsten Daten der Anwendung.
- **Protokolle**: Ein Audit-Log über sicherheitsrelevante und schreibende Vorgänge,
  inklusive der Aufrufe über die Agentenschnittstelle (Quelle \`mcp\`).

## Wohin Daten fließen

Der Kern läuft vollständig on-premise: Frontend, Backend, Datenbank und Routing liegen auf
der Maschine des Betreibers. Kartenkacheln und optionale Datenquellen für Geocoding,
Wetter und Verkehrslage werden von externen Anbietern abgerufen, wenn der Betreiber sie
eingeschaltet hat; sie erhalten dabei Koordinaten, aber keine Benutzer- oder
Fahrzeugkennungen. Diese Quellen lassen sich abschalten.

## Eingebaute Werkzeuge

Die Software bringt mit, was der Betreiber für seine Pflichten braucht: Löschung und
Export von Benutzerdaten, konfigurierbare Aufbewahrungsfristen für Positionsdaten und
Protokolle, ein Audit-Log, Backup und Restore sowie Multi-Faktor-Authentisierung. Details
stehen unter [Sicherheit und Datenschutz](${PRODUCT.wiki}/Sicherheit-und-Datenschutz).

## Diese Seite

${base}/privacy beschreibt, **was die Software tut**. Die rechtlich verbindliche
Datenschutzerklärung für diese Instanz stellt ihr Betreiber bereit; die des Herstellers
für seine Produktseite liegt unter ${PRODUCT.website}/datenschutz.

## Weiter

- [Über ConvoyPlan](${base}/about) · [Kontakt](${base}/contact)
- Sicherheitsrichtlinie: ${PRODUCT.repository}/blob/main/SECURITY.md
`;
}

export function termsMd(ctx: AgentContext): string {
	const { base } = ctx;
	return `# Nutzungsbedingungen

Diese Seite fasst zusammen, unter welchen Bedingungen ConvoyPlan genutzt werden darf.
**Verbindlich sind die Lizenztexte im Quelltext**, nicht diese Zusammenfassung: die
[AGPL-3.0](${PRODUCT.licenseUrl}) und, wo sie nicht ausreicht, die
[kommerzielle Lizenz](${PRODUCT.repository}/blob/main/COMMERCIAL_LICENSE.md).

## Zwei Parteien, zwei Verantwortungen

ConvoyPlan ist self-hosted, und daraus folgt die wichtigste Unterscheidung dieser Seite:

- **${PRODUCT.legalName}** stellt die Software her und lizenziert sie. Auf die Daten
  dieser Instanz hat der Hersteller keinen Zugriff.
- **Der Betreiber dieser Instanz** verantwortet ihren Betrieb — Verfügbarkeit, Zugänge,
  Sicherung und den Umgang mit den Daten darin. Wer ${base} nutzt, tut das nach dessen
  Regeln.

Diese Seite betrifft die **Software**. Ein Dienstleistungsvertrag zwischen Betreiber und
seinen Nutzern ist etwas anderes und steht hier nicht.

## Wann die AGPL genügt

Ohne weitere Vereinbarung gilt die AGPL-3.0. Sie deckt insbesondere ab:

- **Self-Hosting für den eigenen Bedarf** — eine Organisation betreibt ConvoyPlan
  intern und veröffentlicht keine veränderte Fassung.
- **Entwicklung und Erprobung** — lokale Instanzen ohne Produktionsbetrieb.
- **Freie Projekte**, die vollständig unter einer AGPL-verträglichen Lizenz stehen.

Die AGPL verlangt im Gegenzug, eigene Änderungen unter derselben Lizenz zugänglich zu
machen — auch dann, wenn die geänderte Fassung nur als Dienst über das Netz angeboten
wird. Das ist der Unterschied zur GPL und der Grund, warum sie hier steht.

## Wann eine kommerzielle Lizenz nötig ist

- ConvoyPlan wird in ein **proprietäres Produkt** eingebettet.
- ConvoyPlan wird **als Dienst für Dritte** betrieben, ohne die Quelltextpflicht zu
  erfüllen.
- Änderungen sollen **nicht veröffentlicht** werden.
- Die AGPL ist aus internen oder rechtlichen Gründen nicht erfüllbar.

Eine kommerzielle Lizenz wird je juristischer Person vereinbart, nicht je Benutzer. Sie
erlaubt **nicht**, ConvoyPlan weiterzulizenzieren oder weiterzuverkaufen, und sie schließt
keine Nutzung des Namens „${PRODUCT.name}" oder der Logos für eigene Produkte ein.
Anfragen: ${PRODUCT.email}

## Gewährleistung

Die Software wird bereitgestellt **wie besehen, ohne Gewähr** — so steht es in der AGPL,
und so gilt es. Insbesondere gibt es ohne eine ausdrückliche, schriftliche Vereinbarung
keinen Anspruch auf Verfügbarkeit, Reaktionszeiten oder Fehlerbehebung.

Das ist bei einem Werkzeug für Einsatzorganisationen ausdrücklich zu lesen: **ConvoyPlan
plant Märsche, es führt sie nicht.** Die Verantwortung für eine Fahrt, für die Einhaltung
der Straßenverkehrsordnung und für jede Entscheidung unterwegs liegt bei den
Einsatzkräften und ihrer Führung — nicht bei einer Software und nicht bei einem
Sprachmodell, das sie über die Schnittstelle bedient.

## KI-Schnittstelle

Ist der MCP-Server dieser Instanz eingeschaltet, kann ein KI-Programm nach ausdrücklicher
Zustimmung eines angemeldeten Benutzers auf die Fachdaten **einer** Organisation
zugreifen. Dabei gilt:

- Der Zugriff ist durch die Rolle des zustimmenden Benutzers gedeckelt.
- **Was ein Modell liest, verlässt diese Instanz** und geht an den Anbieter des
  KI-Programms. Wer das nicht will, erteilt keine Zustimmung — oder der Betreiber
  schaltet die Schnittstelle ab.
- Kein Werkzeug der Schnittstelle löscht Daten.

Einzelheiten: [Agenten und Entwickler](${base}/developers) · [Datenschutz](${base}/privacy)

## Diese Seite

Sie beschreibt die Lizenzlage der Software. Rechtlich verbindliche Geschäftsbedingungen
für ein konkretes Vertragsverhältnis stellt ${PRODUCT.legalName} unter
${PRODUCT.website} bereit; für den Betrieb dieser Instanz ihr Betreiber.

## Weiter

- [Preise und Lizenzen](${base}/pricing) · [Datenschutz](${base}/privacy) · [Kontakt](${base}/contact)
- Lizenztexte: ${PRODUCT.repository}/blob/main/LICENSE · ${PRODUCT.repository}/blob/main/COMMERCIAL_LICENSE.md
`;
}

export function pricingMd(ctx: AgentContext): string {
	const { base } = ctx;
	return `# Preise und Lizenzen — ${PRODUCT.name}

ConvoyPlan wird nicht pro Sitzplatz verkauft. Der Quelltext steht unter der
${PRODUCT.license} und darf kostenlos selbst gehostet werden; bezahlt wird nur, wer die
Copyleft-Pflicht der AGPL nicht erfüllen kann oder will.

${PLANS.map(
	(plan) => `## ${plan.name}

**Preis: ${plan.price === '0' ? `0 ${plan.currency}` : plan.price}**

${line(plan.summary)}

Enthalten:

${plan.includes.map((i) => `- ${line(i)}`).join('\n')}

Grenzen:

${plan.limits.map((l) => `- ${line(l)}`).join('\n')}`
).join('\n\n')}

## Übersicht

| Modell | Preis | Abrechnung | Copyleft-Pflicht | Support |
| --- | --- | --- | --- | --- |
| Self-hosted (AGPL-3.0) | 0 EUR | entfällt | ja | kein Anspruch |
| Demo-Modus | 0 EUR | entfällt | ja | kein Anspruch |
| Kommerzielle Lizenz | auf Anfrage | pro Organisation / juristischer Person | nein | separat vereinbar |

## Wer braucht eine kommerzielle Lizenz?

Eine kommerzielle Lizenz ist erforderlich, wenn ConvoyPlan in ein proprietäres Produkt
eingebettet, als SaaS-Dienst für Dritte betrieben oder verändert wird, ohne die Änderungen
zu veröffentlichen. Keine Lizenz braucht, wer ConvoyPlan self-hosted für den eigenen
internen Gebrauch betreibt, lokal entwickelt und testet oder es in einem Projekt einsetzt,
das vollständig unter einer AGPL-kompatiblen Lizenz steht.

## Anfragen

Preise für die kommerzielle Lizenz werden individuell vereinbart. Anfrage an
**${PRODUCT.email}**, Betreff „ConvoyPlan Commercial License", mit Anwendungsfall,
Organisation und ungefährer Nutzerzahl. Es gibt keinen Selbstbedienungs-Checkout und
keine Kreditkartenzahlung; ein Agent kann diesen Schritt nicht selbst abschließen.

Volltext: ${PRODUCT.repository}/blob/main/COMMERCIAL_LICENSE.md ·
Als Seite: ${base}/pricing
`;
}

export function docsMd(ctx: AgentContext): string {
	const { base } = ctx;
	return `# Dokumentation — ${PRODUCT.name}

Die Anwenderdokumentation liegt im Wiki des Projekts, die maschinenlesbaren Beschreibungen
auf dieser Instanz.

## Für Anwender

- [Erste Schritte](${PRODUCT.wiki}/Erste-Schritte)
- [Benutzerhandbuch](${PRODUCT.wiki}/Benutzerhandbuch)
- [Konvoi-Planung](${PRODUCT.wiki}/Konvoi-Planung)
- [Fahrzeuge](${PRODUCT.wiki}/Fahrzeuge)
- [Live-Tracking](${PRODUCT.wiki}/Live-Tracking)
- [Marschbefehl-Export](${PRODUCT.wiki}/Marschbefehl-Export)
- [Teilen und Freigabe-Links](${PRODUCT.wiki}/Teilen)
- [Rollen und Berechtigungen](${PRODUCT.wiki}/Rollen)
- [FAQ](${PRODUCT.wiki}/FAQ)

## Für Betreiber

- [Installation und Setup](${PRODUCT.wiki}/Installation-und-Setup)
- [Multi-Tenancy](${PRODUCT.wiki}/Multi-Tenancy)
- [Auto-Updater](${PRODUCT.wiki}/Auto-Updater)
- [Systemübersicht](${PRODUCT.wiki}/Systemuebersicht)
- [Lizenz und Demo-Modus](${PRODUCT.wiki}/Lizenz-und-Demo-Modus)
- [Sicherheit und Datenschutz](${PRODUCT.wiki}/Sicherheit-und-Datenschutz)

## Für Entwickler und Agenten

- [Entwicklerportal dieser Instanz](${base}/developers)
- [API-Dokumentation](${PRODUCT.wiki}/API-Dokumentation) · [api.md](${base}/api.md)
- [OpenAPI 3.1](${base}/openapi.json)
- [auth.md](${base}/auth.md) — Zugangsdaten beschaffen
- [agents.md](${base}/agents.md) — Kurzanleitung für KI-Agenten
- [MCP-Server](${PRODUCT.wiki}/MCP-Server) — Endpunkt \`${base}/mcp\`
  (${ctx.mcpEnabled ? 'eingeschaltet' : 'abgeschaltet'})
- [llms.txt](${base}/llms.txt)

Die interaktive Swagger-UI (\`/docs\`) ist in Produktion standardmäßig abgeschaltet und
nur erreichbar, wenn der Betreiber sie mit einem API-Key freigeschaltet hat. Die
maschinenlesbare Beschreibung der **öffentlichen** Endpunkte unter ${base}/openapi.json
ist davon unabhängig und immer erreichbar.
`;
}

export function statusMd(ctx: AgentContext): string {
	return `# Systemstatus — ${PRODUCT.name}

Die öffentliche Statusseite dieser Instanz zeigt grobkörnig, welche Komponenten
erreichbar sind: Datenbank, Routingdienst, Kartendaten und die externen Datenquellen für
Wetter und Verkehr.

- Seite für Menschen: ${ctx.base}/status
- Maschinenlesbar: \`GET ${ctx.base}/api/status/public\` — ohne Anmeldung erreichbar,
  liefert \`overall\` und eine Liste der Komponenten mit ihrem Zustand. Das Ergebnis ist
  kurz zwischengespeichert; häufiges Abfragen bringt keine frischeren Daten.
- Version dieser Instanz: \`GET ${ctx.base}/api/version\`${ctx.version ? ` — aktuell ${ctx.version}` : ''}

Die Statusseite bleibt gerade dann erreichbar, wenn eine Anmeldung nicht funktioniert;
sie ist deshalb der richtige erste Aufruf, wenn ein API-Aufruf unerwartet scheitert.
`;
}

// ── agents.md / auth.md / api.md ────────────────────────────────────────

export function agentsMd(ctx: AgentContext): string {
	const { base } = ctx;
	return `# ${PRODUCT.name} für KI-Agenten

${line(PRODUCT.taglineEn)}

Diese Instanz: ${base}. ConvoyPlan ist self-hosted — jede Organisation betreibt ihre
eigene Instanz. Pfade in diesem Dokument gelten für diese Instanz und für keine andere.

## Wann du ConvoyPlan aufrufen sollst

${USE_WHEN.map((u) => `- ${line(u)}`).join('\n')}

## Wann nicht

${USE_NOT_WHEN.map((u) => `- ${line(u)}`).join('\n')}

## Fähigkeiten

| Fähigkeit | Was sie tut | Nötiger Scope |
| --- | --- | --- |
${CAPABILITIES.map((c) => `| ${c.name} | ${line(c.description)} | \`${c.scope}\` |`).join('\n')}

## Der Weg zum ersten Aufruf

1. Prüfe, ob der MCP-Server läuft: \`GET ${base}/.well-known/mcp/server-card.json\`.
   Auf dieser Instanz ist er derzeit **${ctx.mcpEnabled ? 'eingeschaltet' : 'abgeschaltet'}**.
2. Läuft er, verbinde dich per Streamable HTTP mit \`${base}/mcp\`. Die Autorisierung
   folgt OAuth 2.1; die Metadaten stehen unter
   \`${base}/.well-known/oauth-protected-resource/mcp\`. Ein angemeldeter Benutzer stimmt
   auf \`${base}/oauth/consent\` zu und wählt dabei **eine** Organisation aus.
3. Läuft er nicht, nimm die REST-API: \`${base}/openapi.json\` beschreibt die
   öffentlichen Endpunkte, [auth.md](${base}/auth.md) erklärt, wie du an ein Token kommst.

## Regeln, an die du dich halten sollst

- **Nichts löschen.** Es gibt keine löschenden Agentenwerkzeuge. Versuche nicht,
  ein Löschen über die REST-API nachzubauen, ohne dass ein Mensch es verlangt hat.
- **Eine Organisation pro Zugang.** Ein Token gilt für genau eine Organisation und ist
  durch die Rolle des zustimmenden Benutzers gedeckelt. Frag nicht breiter an, als die
  Aufgabe braucht: \`convoy:read\` reicht für jede reine Auskunft.
- **Schreiben ist nachvollziehbar.** Jeder schreibende Aufruf landet im Audit-Log der
  Organisation mit der Quelle \`mcp\`. Das ist beabsichtigt.
- **Zeitangaben sind sicherheitsrelevant.** Marschzeiten, Halte und Reichweiten stammen
  aus einer Berechnung, nicht aus einer Zusage. Gib sie als Schätzung weiter.
- **Im Demo-Modus** antworten schreibende Aufrufe mit HTTP 402. Das ist kein Fehler
  deinerseits, sondern eine fehlende Lizenz auf der Instanz.

## Weiterführend

- [llms.txt](${base}/llms.txt) · [auth.md](${base}/auth.md) · [api.md](${base}/api.md)
- [Agent Card](${base}/.well-known/agent-card.json) · [Agent Skills](${base}/.well-known/agent-skills/index.json)
- [MCP-Server im Wiki](${PRODUCT.wiki}/MCP-Server)
`;
}

export function authMd(ctx: AgentContext): string {
	const { base } = ctx;
	return `# Authentifizierung für Agenten — ${PRODUCT.name}

Wie ein Programm oder ein KI-Agent an Zugangsdaten für diese Instanz (${base}) kommt.
ConvoyPlan kennt drei Wege: OAuth 2.1 für den MCP-Server, einen API-Key für feste
Integrationen und ein JWT aus der Benutzeranmeldung. Es gibt **keine** anonyme
Identität und keine automatische Selbstregistrierung eines Agenten — am Anfang steht
immer ein Mensch.

## Discover

Beginne mit den Metadaten, nicht mit dem Raten:

- \`GET ${base}/.well-known/oauth-protected-resource/mcp\` — RFC 9728, Protected Resource
  Metadata des MCP-Servers: \`resource\`, \`authorization_servers\`, \`scopes_supported\`.
- \`GET ${base}/.well-known/oauth-authorization-server\` — RFC 8414, Authorization Server
  Metadata: \`authorization_endpoint\`, \`token_endpoint\`, \`registration_endpoint\`,
  \`revocation_endpoint\`, unterstützte Verfahren.
- \`GET ${base}/.well-known/mcp/server-card.json\` — Kurzbeschreibung des MCP-Servers.
- \`GET ${base}/openapi.json\` — die \`securitySchemes\` der REST-API.

Ein geschützter Endpunkt antwortet ohne gültiges Token mit **401** und einem
\`WWW-Authenticate: Bearer resource_metadata="…"\`-Header. Folge diesem Header, statt
Pfade zu erraten.

Auf dieser Instanz ist der MCP-Server derzeit
**${ctx.mcpEnabled ? 'eingeschaltet' : 'abgeschaltet'}**${when(!ctx.mcpEnabled, '; die OAuth-Dokumente existieren dann nicht, weil die Routen nicht montiert sind (404). Nimm in diesem Fall den API-Key- oder JWT-Weg')}.

## Pick a method

| Methode | Wofür | Wer richtet sie ein |
| --- | --- | --- |
| **OAuth 2.1 (MCP)** | KI-Agenten, die im Auftrag eines Menschen handeln | Der Benutzer selbst, durch Zustimmung |
| **API-Key** (\`X-API-Key\`) | Feste Integrationen und Fremdsysteme | Superadmin im Portal, je Organisation |
| **Bearer-JWT** | Skripte, die sich als Benutzer anmelden dürfen | Der Benutzer, mit seinen Zugangsdaten |

Es gibt bewusst keinen \`service_auth\`- und keinen \`identity_assertion\`-Fluss und
keinen \`identity_endpoint\`: eine Maschine kann sich hier nicht selbst eine Identität
ausstellen lassen. Wer ein \`id-jag\`-Token (\`urn:ietf:params:oauth:token-type:id-jag\`)
anbietet, findet hier keinen Annahmepunkt dafür.

## Register

Für OAuth registriert sich der Client dynamisch nach **RFC 7591** am
\`registration_endpoint\` (\`POST ${base}/register\`), sofern der Betreiber die
dynamische Client-Registrierung eingeschaltet hat. Alternativ akzeptiert die Instanz
Client-ID-Metadata-Documents, wenn sie freigeschaltet sind; beides steht in der
Authorization-Server-Metadata. Ist beides aus, trägt der Betreiber den Client von Hand
im Admin-Portal unter **MCP** ein.

Ein API-Key wird nicht registriert, sondern im Superadmin-Portal für genau eine
Organisation erzeugt und dort mit einer festen Rolle versehen.

## Claim

Der Zugriff entsteht durch die **Zustimmung eines angemeldeten Benutzers**. Der
Autorisierungsfluss ist Authorization Code mit PKCE (S256):

1. \`GET ${base}/authorize?response_type=code&client_id=…&redirect_uri=…&code_challenge=…&code_challenge_method=S256&scope=convoy%3Aread&state=…&resource=${base}/mcp\`
2. Der Benutzer meldet sich an und sieht auf \`${base}/oauth/consent\`, welche
   Organisation und welche Scopes er freigibt. Er wählt **eine** Organisation.
3. Die Umleitung liefert \`code\` und \`state\`; die Antwort trägt \`iss\` (RFC 9207),
   das du gegen den Aussteller prüfen sollst.

## Exchange

\`\`\`http
POST ${base}/token
Content-Type: application/x-www-form-urlencoded

grant_type=authorization_code&code=…&redirect_uri=…&client_id=…&code_verifier=…&resource=${base}/mcp
\`\`\`

Antwort: \`access_token\`, \`token_type: Bearer\`, \`expires_in\`, \`refresh_token\` und
die tatsächlich erteilten \`scope\`s. Erteilt wird der **Schnitt** aus angefragten Scopes
und dem, was die Rolle des Benutzers hergibt — wer zu viel verlangt, bekommt weniger
statt eines Fehlers. Ein abgelaufenes Token erneuerst du mit
\`grant_type=refresh_token\`.

Für die REST-API statt OAuth:

\`\`\`http
POST ${base}/api/auth/login
Content-Type: application/json

{"email": "…", "password": "…"}
\`\`\`

## Use the access_token

\`\`\`http
GET ${base}/api/convoys
Authorization: Bearer <access_token>
MCP-Protocol-Version: 2025-06-18
\`\`\`

Mit API-Key stattdessen \`X-API-Key: <key>\`. Beide Wege sind strikt getrennt: ein
Organisations-Key erreicht keine Systemkennzahlen, ein System-Key keine
Organisationsdaten.

Scopes und ihre Bedeutung:

${SCOPES.map((s) => `- \`${s.name}\` — ${s.description}`).join('\n')}

Ein breiterer Scope schließt den engeren ein: \`convoy:write\` deckt \`fleet:status\` und
\`convoy:read\` mit ab. Frag so wenig an wie möglich.

## Errors

| Status | Bedeutung | Was zu tun ist |
| --- | --- | --- |
| \`401\` mit \`WWW-Authenticate: Bearer resource_metadata="…"\` | Kein oder ungültiges Token | Metadaten laden, Fluss neu starten |
| \`401 invalid_token\` | Abgelaufen oder widerrufen | Mit \`refresh_token\` erneuern, sonst neue Zustimmung einholen |
| \`403 insufficient_scope\` (mit \`scope="…"\`) | Token reicht, Scope nicht | Step-up: neue Autorisierung mit dem genannten Scope |
| \`402\` | Instanz im Demo-Modus, kein Lizenzschlüssel | Lesen geht weiter; Schreiben erst nach Lizenzierung durch den Betreiber |
| \`404\` auf \`/mcp\` oder den OAuth-Dokumenten | MCP ist abgeschaltet | REST-API nutzen, oder den Betreiber bitten, die KI-Schnittstelle einzuschalten |
| \`429\` | Ratenbegrenzung | \`Retry-After\` beachten |

## Revocation

- \`POST ${base}/revoke\` (RFC 7009) widerruft ein Access- oder Refresh-Token.
- Der Benutzer kann seine Zustimmung im Admin-Portal unter **MCP** zurücknehmen; damit
  enden alle Verbindungen dieses Clients.
- Der Betreiber kann die KI-Schnittstelle vollständig abschalten. Bereits ausgestellte
  Tokens werden dadurch nicht ungültig, laufen aber ins Leere, weil der Endpunkt fehlt.
- API-Keys werden im Superadmin-Portal gelöscht und wirken sofort.

## Sandbox

${
	ctx.demoEnabled
		? `\`${base}/demo\` legt eine eigene temporäre Umgebung mit Beispieldaten an — ohne Konto,
ohne Berührung mit Produktivdaten. Probiere schreibende Aufrufe dort aus, nicht gegen
eine Produktivorganisation.`
		: `Auf dieser Instanz ist kein öffentlicher Demo-Zugang freigeschaltet. Eine Sandbox
entsteht durch eine zweite, lokal gestartete Instanz ohne Lizenzschlüssel; sie läuft im
Demo-Modus und beantwortet schreibende Zugriffe mit HTTP 402.`
}

Spezifikation, an der sich dieses Dokument orientiert: https://github.com/workos/auth.md
`;
}

export function apiMd(ctx: AgentContext): string {
	const { base } = ctx;
	return `# REST-API — ${PRODUCT.name}

Basis-URL dieser Instanz: \`${base}/api\`. Die maschinenlesbare Beschreibung der
öffentlichen Endpunkte liegt unter [${base}/openapi.json](${base}/openapi.json)
(OpenAPI 3.1, jede Operation mit \`operationId\`, Beschreibung und Antwortschema — direkt
als Function-Calling-Definition verwendbar).

## Authentifizierung

- \`Authorization: Bearer <JWT>\` aus \`POST /api/auth/login\`
- \`X-API-Key: <key>\` für feste Integrationen, je Organisation mit fester Rolle
- OAuth 2.1 für den MCP-Server — siehe [auth.md](${base}/auth.md)

Ein Aufruf ohne Zugangsdaten auf einen geschützten Endpunkt antwortet mit \`401\` und
einem \`WWW-Authenticate\`-Header, der auf die Resource-Metadaten zeigt.

## Ohne Anmeldung erreichbar

| Endpunkt | Zweck |
| --- | --- |
| \`GET /api/status/public\` | Grobkörniger Zustand der Instanz |
| \`GET /api/status/capabilities\` | Welche Schnittstellen diese Instanz anbietet |
| \`GET /api/version\` | Version und Build |
| \`GET /api/branding\` | Farben und Logo der Instanz |
| \`GET /api/setup/status\` | Ob die Ersteinrichtung noch aussteht |
| \`GET /api/auth/demo-status\` | Ob der Demo-Zugang freigeschaltet ist |
| \`POST /api/auth/login\` | Anmeldung, liefert das JWT |
| \`GET /api/track/{slug}\` | Live-Tracking über einen öffentlichen Slug |
| \`GET /api/share/{token}\` | Kolonne über einen Freigabe-Link |

## Mit Anmeldung

Konvois, Fahrzeuge, Wegpunkte, Routen, Positionen, Benutzer, Leitstellen, Branding,
Freigabe-Links und — für Superadmins — die Administration. Die vollständige Beschreibung
steht in der Swagger-UI unter \`/docs\`, die in Produktion aber standardmäßig abgeschaltet
ist und vom Betreiber mit einem API-Key freigeschaltet werden muss.

## Fehlercodes

| Status | Bedeutung |
| --- | --- |
| \`401\` | Kein oder ungültiges Token |
| \`402\` | Demo-Modus — schreibende Zugriffe gesperrt, lesende erlaubt |
| \`403\` | Rolle oder Scope reicht nicht |
| \`404\` | Nicht vorhanden, oder die Funktion ist auf dieser Instanz abgeschaltet |
| \`422\` | Eingabe entspricht nicht dem Schema |
| \`429\` | Ratenbegrenzung, \`Retry-After\` beachten |

## Grenzen

- Die API ist **organisationsbezogen**: ein Token sieht genau eine Organisation.
- Es gibt keine Massen-Exportendpunkte und keinen anonymen Schreibzugriff.
- Routenberechnungen laufen gegen den lokalen GraphHopper; nach einem Regionswechsel
  kann er einige Minuten mit dem Import beschäftigt sein und antwortet dann mit einem
  entsprechenden Status auf \`/api/status/public\`.
- Die Oberfläche und die Felder sind deutschsprachig.

## Echtzeit

Live-Positionen kommen per WebSocket unter \`${base}/api/ws/track/…\`. Über MCP gibt es
dafür Abonnements, die Änderungen als Ereignisse liefern.

## Werkzeuge für Agenten

Bevorzugt den MCP-Server unter \`${base}/mcp\` (auf dieser Instanz
${ctx.mcpEnabled ? 'eingeschaltet' : 'abgeschaltet'}) — er bildet dieselben Fähigkeiten
als benannte Werkzeuge mit Scopes ab. Siehe [agents.md](${base}/agents.md).
`;
}

export function developersMd(ctx: AgentContext): string {
	const { base } = ctx;
	return `# Entwicklerportal — ${PRODUCT.name}

Alles, was eine Integration mit dieser Instanz (${base}) braucht: Schnittstellen,
Zugangsdaten, maschinenlesbare Beschreibungen und eine Sandbox.

## In fünf Minuten zum ersten Aufruf

1. **Instanz prüfen** — \`curl ${base}/api/status/capabilities\` sagt, welche
   Schnittstellen diese Instanz anbietet.
2. **Zugang holen** — API-Key im Superadmin-Portal erzeugen lassen, oder
   \`POST ${base}/api/auth/login\` für ein JWT. Details: [auth.md](${base}/auth.md).
3. **Aufrufen** —
   \`curl -H "X-API-Key: \\$KEY" ${base}/api/convoys\`
4. **Beschreibung laden** — \`${base}/openapi.json\` als Grundlage für einen
   generierten Client oder für Function-Calling-Definitionen.

## Schnittstellen

| Schnittstelle | Endpunkt | Zustand |
| --- | --- | --- |
| REST-API | \`${base}/api\` | immer |
| OpenAPI 3.1 (öffentliche Endpunkte) | \`${base}/openapi.json\` | immer |
| WebSocket Live-Tracking | \`${base}/api/ws/track/…\` | immer |
| MCP (Streamable HTTP) | \`${base}/mcp\` | ${ctx.mcpEnabled ? 'eingeschaltet' : 'abgeschaltet — Betreiber schaltet im Admin-Portal ein'} |
| Swagger-UI / ReDoc | \`${base}/docs\`, \`${base}/redoc\` | nur wenn der Betreiber sie freigeschaltet hat |

## Authentifizierung

${SCOPES.map((s) => `- \`${s.name}\` — ${s.description}`).join('\n')}

Drei Wege: OAuth 2.1 (für Agenten, mit Zustimmung eines Benutzers), API-Key per
\`X-API-Key\` (feste Integrationen) und Bearer-JWT (Benutzeranmeldung). Vollständig
beschrieben in [auth.md](${base}/auth.md).

## Sandbox

${
	ctx.demoEnabled
		? `Diese Instanz hat den Demo-Zugang freigeschaltet: \`${base}/demo\` legt eine eigene
temporäre Umgebung mit Beispieldaten an, ohne Konto und ohne Berührung mit Produktivdaten.
Sie verfällt nach Ablauf der eingestellten Sitzungsdauer. Probiere schreibende Aufrufe
dort aus.`
		: `Der öffentliche Demo-Zugang ist auf dieser Instanz nicht freigeschaltet. Eine eigene
Sandbox startet man mit dem Installer oder \`docker compose up\` ohne Lizenzschlüssel: die
Instanz läuft dann im Demo-Modus, lesende Aufrufe funktionieren, schreibende antworten
mit HTTP 402.`
}

## SDKs

Es gibt keinen offiziell gepflegten Client für eine bestimmte Sprache. Der empfohlene Weg
ist ein aus \`${base}/openapi.json\` generierter Client (etwa mit \`openapi-generator\`)
oder — für KI-Agenten — der MCP-Server, der die Werkzeuge bereits typisiert ausliefert.

## Quelltext und Mitwirkung

- Repository: ${PRODUCT.repository}
- Issues und Funktionswünsche: ${PRODUCT.repository}/issues
- Sicherheitsmeldungen: ${PRODUCT.email} (nicht öffentlich)
- Lizenz: ${PRODUCT.license}, kommerzielle Lizenz auf Anfrage — ${base}/pricing

## Weiter

- [agents.md](${base}/agents.md) · [api.md](${base}/api.md) · [auth.md](${base}/auth.md)
- [llms.txt](${base}/llms.txt) · [developers/llms.txt](${base}/developers/llms.txt)
- [Agent Card](${base}/.well-known/agent-card.json) · [API-Katalog](${base}/.well-known/api-catalog)
`;
}

// ── robots.txt, Sitemap, Feeds ──────────────────────────────────────────

/**
 * Die KI-Crawler ausdrücklich benennen statt sie unter `User-agent: *` mitlaufen
 * zu lassen: manche Betreiber lesen nur ihren eigenen Abschnitt, und eine
 * ausdrückliche Erlaubnis ist auch für einen Menschen die klarere Aussage.
 */
const AI_CRAWLERS = [
	'GPTBot',
	'ChatGPT-User',
	'OAI-SearchBot',
	'ClaudeBot',
	'Claude-User',
	'Claude-SearchBot',
	'anthropic-ai',
	'Google-Extended',
	'PerplexityBot',
	'Perplexity-User',
	'Applebot-Extended',
	'DeepSeekBot',
	'ora-agent',
	'CCBot',
	'Bytespider',
	'meta-externalagent',
	'cohere-ai',
	'YouBot'
];

export function robotsTxt(ctx: AgentContext): string {
	const { base } = ctx;
	const crawlers = AI_CRAWLERS.map(
		(ua) => `User-agent: ${ua}\nAllow: /\nDisallow: /admin\nDisallow: /setup\nDisallow: /o/\n`
	).join('\n');
	return `# ${PRODUCT.name} — ${line(PRODUCT.tagline)}
# Einstieg für KI-Agenten: ${base}/llms.txt

User-agent: *
Allow: /
# Organisationsinterne Bereiche gehören nicht in einen Index. Sie sind ohnehin
# durch die Anmeldung geschützt; das hier spart nur nutzlose Abrufe.
Disallow: /admin
Disallow: /setup
Disallow: /o/
Disallow: /oauth/
Disallow: /share/
Disallow: /plan

${crawlers}
Sitemap: ${base}/sitemap.xml
# NLWeb Schema Feeds
Schemamap: ${base}/schema-map.xml
`;
}

export function sitemapXml(ctx: AgentContext): string {
	const { base } = ctx;
	const lastmod = new Date().toISOString().slice(0, 10);
	const urls = PAGES.map(
		(p) => `  <url>
    <loc>${base}${p.path === '/' ? '/' : p.path}</loc>
    <lastmod>${lastmod}</lastmod>
    <changefreq>${p.path === '/status' ? 'daily' : 'monthly'}</changefreq>
    <priority>${p.priority}</priority>
    <xhtml:link rel="alternate" type="text/markdown" href="${base}${p.markdown}" />
  </url>`
	).join('\n');
	const extras = ['/llms.txt', '/llms-full.txt', '/agents.md', '/auth.md', '/api.md', '/openapi.json']
		.map(
			(path) => `  <url>
    <loc>${base}${path}</loc>
    <lastmod>${lastmod}</lastmod>
    <changefreq>monthly</changefreq>
    <priority>0.6</priority>
  </url>`
		)
		.join('\n');
	return `<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"
        xmlns:xhtml="http://www.w3.org/1999/xhtml">
${urls}
${extras}
</urlset>
`;
}

/** Schema Map nach der NLWeb-Schema-Feeds-Konvention. */
export function schemaMapXml(ctx: AgentContext): string {
	const { base } = ctx;
	const lastmod = new Date().toISOString();
	return `<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"
        xmlns:schemamap="https://schemamap.org/schemas/schemamap/0.1">
  <url>
    <loc>${base}/feeds/site.jsonl</loc>
    <lastmod>${lastmod}</lastmod>
    <schemamap:type>application/x-ndjson</schemamap:type>
    <schemamap:schema>https://schema.org/WebPage</schemamap:schema>
  </url>
  <url>
    <loc>${base}/feeds/faq.jsonl</loc>
    <lastmod>${lastmod}</lastmod>
    <schemamap:type>application/x-ndjson</schemamap:type>
    <schemamap:schema>https://schema.org/Question</schemamap:schema>
  </url>
</urlset>
`;
}

export function siteJsonl(ctx: AgentContext): string {
	const { base } = ctx;
	return (
		PAGES.map((p) =>
			JSON.stringify({
				'@context': 'https://schema.org',
				'@type': 'WebPage',
				'@id': `${base}${p.path}`,
				url: `${base}${p.path}`,
				name: p.title,
				description: p.summary,
				inLanguage: PRODUCT.inLanguage,
				keywords: p.keywords.join(', '),
				encoding: { '@type': 'MediaObject', encodingFormat: 'text/markdown', contentUrl: `${base}${p.markdown}` },
				isPartOf: { '@type': 'WebSite', '@id': `${base}/#website`, name: PRODUCT.name }
			})
		).join('\n') + '\n'
	);
}

export function faqJsonl(ctx: AgentContext): string {
	const { base } = ctx;
	return (
		FAQ.map((item, i) =>
			JSON.stringify({
				'@context': 'https://schema.org',
				'@type': 'Question',
				'@id': `${base}/#faq-${i + 1}`,
				name: item.q,
				inLanguage: PRODUCT.inLanguage,
				acceptedAnswer: { '@type': 'Answer', text: item.a },
				isPartOf: { '@type': 'FAQPage', '@id': `${base}/#faq` }
			})
		).join('\n') + '\n'
	);
}

// ── Well-Known-Dokumente ────────────────────────────────────────────────

/** Agentic Resource Discovery — https://agenticresourcediscovery.org/ */
export function ardJson(ctx: AgentContext): unknown {
	const { base } = ctx;
	const resources: Record<string, unknown>[] = [
		{
			type: 'openapi',
			name: 'ConvoyPlan REST-API (öffentliche Endpunkte)',
			description:
				'OpenAPI 3.1 der ohne Anmeldung erreichbaren Endpunkte, inklusive der Sicherheitsschemata für die geschützten.',
			url: `${base}/openapi.json`,
			documentation: `${base}/api.md`,
			authentication: { type: 'bearer', description: 'JWT aus POST /api/auth/login, oder X-API-Key' }
		},
		{
			type: 'agent-instructions',
			name: 'ConvoyPlan für Agenten',
			description: 'Wann ConvoyPlan aufzurufen ist, wann nicht, und welche Regeln dabei gelten.',
			url: `${base}/agents.md`
		},
		{
			type: 'documentation',
			name: 'ConvoyPlan llms.txt',
			description: 'Navigationsindex für KI-Agenten.',
			url: `${base}/llms.txt`
		}
	];
	if (ctx.mcpEnabled) {
		resources.unshift({
			type: 'mcp',
			name: 'ConvoyPlan MCP-Server',
			description:
				'Konvois, Fahrzeuge, Wegpunkte, Routen und Status als MCP-Werkzeuge. Streamable HTTP, OAuth 2.1, keine löschenden Werkzeuge.',
			url: `${base}/mcp`,
			transport: 'streamable-http',
			card: `${base}/.well-known/mcp/server-card.json`,
			authentication: {
				type: 'oauth2',
				authorization_servers: [base],
				scopes: SCOPES.map((s) => s.name)
			}
		});
	}
	return {
		$schema: 'https://agenticresourcediscovery.org/schema/v1/ard.json',
		version: '1.0',
		name: PRODUCT.name,
		description: line(PRODUCT.tagline),
		url: `${base}/`,
		provider: {
			name: PRODUCT.legalName,
			url: PRODUCT.website,
			email: PRODUCT.email
		},
		updated: new Date().toISOString(),
		resources
	};
}

/** A2A Agent Card. */
export function agentCardJson(ctx: AgentContext): unknown {
	const { base } = ctx;
	return {
		protocolVersion: '0.3.0',
		name: PRODUCT.name,
		description: `${line(PRODUCT.tagline)} ${line(PRODUCT.taglineEn)}`,
		url: ctx.mcpEnabled ? `${base}/mcp` : `${base}/api`,
		preferredTransport: ctx.mcpEnabled ? 'streamable-http' : 'http+json',
		version: ctx.version || '1.0.0',
		documentationUrl: `${base}/agents.md`,
		iconUrl: `${base}/logo/light/AppIcon.png`,
		provider: {
			organization: PRODUCT.legalName,
			url: PRODUCT.website
		},
		capabilities: {
			streaming: true,
			pushNotifications: false,
			stateTransitionHistory: true
		},
		securitySchemes: ctx.mcpEnabled
			? {
					oauth2: {
						type: 'oauth2',
						description:
							'OAuth 2.1 mit PKCE. Zugriff entsteht durch die Zustimmung eines angemeldeten Benutzers und gilt für genau eine Organisation.',
						flows: {
							authorizationCode: {
								authorizationUrl: `${base}/authorize`,
								tokenUrl: `${base}/token`,
								scopes: Object.fromEntries(SCOPES.map((s) => [s.name, s.description]))
							}
						}
					},
					apiKey: { type: 'apiKey', in: 'header', name: 'X-API-Key' }
				}
			: {
					apiKey: { type: 'apiKey', in: 'header', name: 'X-API-Key' },
					bearer: { type: 'http', scheme: 'bearer', bearerFormat: 'JWT' }
				},
		security: ctx.mcpEnabled ? [{ oauth2: ['convoy:read'] }, { apiKey: [] }] : [{ apiKey: [] }, { bearer: [] }],
		defaultInputModes: ['text/plain', 'application/json'],
		defaultOutputModes: ['application/json', 'text/plain'],
		skills: CAPABILITIES.map((c) => ({
			id: c.id,
			name: c.name,
			description: c.description,
			tags: ['konvoi', 'marschplanung', 'bos', 'routing', 'tracking'],
			inputModes: ['text/plain', 'application/json'],
			outputModes: ['application/json']
		})),
		additionalInterfaces: [
			{ url: `${base}/api`, transport: 'http+json' },
			...(ctx.mcpEnabled ? [{ url: `${base}/mcp`, transport: 'streamable-http' }] : [])
		]
	};
}

/** Agent-Skills-Index. */
export function agentSkillsJson(ctx: AgentContext): unknown {
	const { base } = ctx;
	return {
		$schema: 'https://agent-skills.org/schema/v1/index.json',
		version: '1.0',
		name: PRODUCT.name,
		description: line(PRODUCT.tagline),
		homepage: `${base}/`,
		instructions: `${base}/agents.md`,
		authentication: `${base}/auth.md`,
		useWhen: USE_WHEN,
		useNotWhen: USE_NOT_WHEN,
		skills: CAPABILITIES.map((c) => ({
			name: c.id,
			title: c.name,
			description: c.description,
			scope: c.scope,
			endpoint: ctx.mcpEnabled ? `${base}/mcp` : `${base}/api`,
			protocol: ctx.mcpEnabled ? 'mcp' : 'rest',
			documentation: `${base}/agents.md`
		}))
	};
}

/** MCP Server Card. */
export function mcpServerCardJson(ctx: AgentContext): unknown {
	const { base } = ctx;
	return {
		$schema: 'https://modelcontextprotocol.io/schema/server-card/v1.json',
		name: 'convoyplan',
		title: `${PRODUCT.name} MCP-Server`,
		description:
			'Konvois, Fahrzeuge, Wegpunkte, Routen und Live-Status einer ConvoyPlan-Instanz als MCP-Werkzeuge. Zugriff entsteht durch die Zustimmung eines angemeldeten Benutzers, gilt für genau eine Organisation und ist durch dessen Rolle gedeckelt. Kein Werkzeug löscht Daten; jeder schreibende Aufruf landet im Audit-Log.',
		version: ctx.version || '1.0.0',
		serverUrl: `${base}/mcp`,
		transport: 'streamable-http',
		status: ctx.mcpEnabled ? 'available' : 'disabled',
		documentation: `${PRODUCT.wiki}/MCP-Server`,
		websiteUrl: `${base}/developers`,
		provider: { name: PRODUCT.legalName, url: PRODUCT.website },
		authentication: {
			type: 'oauth2',
			protectedResourceMetadata: `${base}/.well-known/oauth-protected-resource/mcp`,
			authorizationServerMetadata: `${base}/.well-known/oauth-authorization-server`,
			scopes: Object.fromEntries(SCOPES.map((s) => [s.name, s.description])),
			dynamicClientRegistration: 'optional'
		},
		capabilities: { tools: true, resources: true, subscriptions: true, prompts: false },
		tools: CAPABILITIES.map((c) => ({
			name: c.id,
			description: c.description,
			requiredScope: c.scope,
			destructive: false
		})),
		...(ctx.mcpEnabled
			? {}
			: {
					note: 'Die KI-Schnittstelle ist auf dieser Instanz abgeschaltet. Solange sie aus ist, existiert /mcp nicht (HTTP 404) — die Routen sind nicht montiert, nicht bloß gesperrt. Der Betreiber schaltet sie im Admin-Portal unter „System → KI-Schnittstelle" ein.'
				})
	};
}

/** API-Katalog nach RFC 9727 (`application/linkset+json`). */
export function apiCatalogJson(ctx: AgentContext): unknown {
	const { base } = ctx;
	const linkset: Record<string, unknown>[] = [
		{
			anchor: `${base}/api`,
			'service-desc': [
				{
					href: `${base}/openapi.json`,
					type: 'application/vnd.oai.openapi+json;version=3.1',
					title: 'ConvoyPlan REST-API — OpenAPI 3.1 der öffentlichen Endpunkte'
				}
			],
			'service-doc': [
				{ href: `${base}/api.md`, type: 'text/markdown', title: 'REST-API — Beschreibung' },
				{ href: `${base}/developers`, type: 'text/html', title: 'Entwicklerportal' }
			],
			'service-meta': [
				{ href: `${base}/.well-known/agent-card.json`, type: 'application/json', title: 'A2A Agent Card' }
			],
			author: [{ href: PRODUCT.website, title: PRODUCT.legalName }],
			describedby: [{ href: `${base}/auth.md`, type: 'text/markdown', title: 'Authentifizierung für Agenten' }]
		}
	];
	if (ctx.mcpEnabled) {
		linkset.push({
			anchor: `${base}/mcp`,
			'service-desc': [
				{
					href: `${base}/.well-known/mcp/server-card.json`,
					type: 'application/json',
					title: 'ConvoyPlan MCP Server Card'
				}
			],
			'service-doc': [
				{ href: `${base}/agents.md`, type: 'text/markdown', title: 'ConvoyPlan für KI-Agenten' }
			],
			describedby: [
				{
					href: `${base}/.well-known/oauth-protected-resource/mcp`,
					type: 'application/json',
					title: 'OAuth Protected Resource Metadata (RFC 9728)'
				}
			]
		});
	}
	return { linkset };
}
