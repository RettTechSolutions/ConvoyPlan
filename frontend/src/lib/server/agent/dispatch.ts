/**
 * Der Verteiler für alles, was ConvoyPlan an Maschinen ausliefert.
 *
 * Warum eine Tabelle in `hooks.server.ts` statt je einer SvelteKit-Route:
 * die Hälfte dieser Pfade liegt unter `/.well-known/`, und ein Verzeichnis,
 * das mit einem Punkt beginnt, übergeht der Dateisystem-Router. Eine Tabelle
 * hält außerdem Sitemap, llms.txt, Markdown-Zwillinge und die Aushandlung in
 * `hooks.server.ts` beieinander — sie beschreiben dieselbe Menge Seiten und
 * dürfen nicht auseinanderlaufen.
 *
 * Abgeschaltet (`AGENT_DISCOVERY=false`) liefert der Verteiler `null`, und die
 * Pfade gibt es schlicht nicht. Eine rein interne Instanz muss nichts über
 * sich erzählen.
 */
import { env } from '$env/dynamic/private';
import * as docs from './documents';
import type { AgentContext } from './documents';
import * as ask from './ask';
import { PAGES, pageFor } from '$lib/agent/pages';

const BACKEND = 'http://backend:8000';

/** Ob die Agenten-Auskunft auf dieser Instanz eingeschaltet ist (Standard: ja). */
export function discoveryEnabled(): boolean {
	const raw = (env.AGENT_DISCOVERY ?? '').trim().toLowerCase();
	if (raw === '') return true;
	return !['false', '0', 'no', 'off'].includes(raw);
}

// ── Kontext ─────────────────────────────────────────────────────────────

interface Capabilities {
	mcp_enabled: boolean;
	demo_enabled: boolean;
	version: string;
}

let cache: { value: Capabilities; at: number } | null = null;
const CACHE_MS = 60_000;

/**
 * Was diese Instanz tatsächlich anbietet. Das Backend weiß es; ein Fehlschlag
 * darf die Auslieferung nicht aufhalten, also fällt die Antwort dann auf das
 * vorsichtigere „nicht vorhanden" zurück — lieber verschweigen wir eine
 * Schnittstelle, als eine anzukündigen, die mit 404 antwortet.
 */
async function capabilities(fetchFn: typeof fetch): Promise<Capabilities> {
	if (cache && Date.now() - cache.at < CACHE_MS) return cache.value;
	const fallback: Capabilities = { mcp_enabled: false, demo_enabled: false, version: '' };
	try {
		const resp = await fetchFn(`${BACKEND}/api/status/capabilities`, {
			signal: AbortSignal.timeout(3000)
		});
		if (!resp.ok) return fallback;
		const data = (await resp.json()) as Partial<Capabilities>;
		const value: Capabilities = {
			mcp_enabled: data.mcp_enabled === true,
			demo_enabled: data.demo_enabled === true,
			version: typeof data.version === 'string' ? data.version : ''
		};
		cache = { value, at: Date.now() };
		return value;
	} catch {
		return fallback;
	}
}

export async function buildContext(url: URL, fetchFn: typeof fetch): Promise<AgentContext> {
	const caps = await capabilities(fetchFn);
	return {
		base: url.origin.replace(/\/$/, ''),
		mcpEnabled: caps.mcp_enabled,
		demoEnabled: caps.demo_enabled,
		version: caps.version
	};
}

// ── Antworten ───────────────────────────────────────────────────────────

const CACHE_HEADER = 'public, max-age=300, stale-while-revalidate=3600';

function text(body: string, type: string): Response {
	return new Response(body, {
		headers: {
			'content-type': `${type}; charset=utf-8`,
			'cache-control': CACHE_HEADER,
			'access-control-allow-origin': '*',
			vary: 'Accept'
		}
	});
}

function json(body: unknown, type = 'application/json'): Response {
	return new Response(JSON.stringify(body, null, 2), {
		headers: {
			'content-type': `${type}; charset=utf-8`,
			'cache-control': CACHE_HEADER,
			'access-control-allow-origin': '*'
		}
	});
}

export const markdown = (body: string) => text(body, 'text/markdown');

// ── Die Tabelle ─────────────────────────────────────────────────────────

type Builder = (ctx: AgentContext) => Response;

const ROUTES: Record<string, Builder> = {
	// Einstiege
	'/llms.txt': (c) => text(docs.llmsTxt(c), 'text/plain'),
	'/.well-known/llms.txt': (c) => text(docs.llmsTxt(c), 'text/plain'),
	'/llms-full.txt': (c) => text(docs.llmsFullTxt(c), 'text/plain'),
	'/api/llms.txt': (c) => text(docs.sectionLlmsTxt('api', c), 'text/plain'),
	'/docs/llms.txt': (c) => text(docs.sectionLlmsTxt('docs', c), 'text/plain'),
	'/developers/llms.txt': (c) => text(docs.sectionLlmsTxt('developers', c), 'text/plain'),

	// Markdown-Zwillinge der Seiten
	'/index.md': (c) => markdown(docs.indexMd(c)),
	'/llms.md': (c) => markdown(docs.indexMd(c)),
	'/about.md': (c) => markdown(docs.aboutMd(c)),
	'/contact.md': (c) => markdown(docs.contactMd(c)),
	'/privacy.md': (c) => markdown(docs.privacyMd(c)),
	'/pricing.md': (c) => markdown(docs.pricingMd(c)),
	'/developers.md': (c) => markdown(docs.developersMd(c)),
	'/developer.md': (c) => markdown(docs.developersMd(c)),
	'/docs.md': (c) => markdown(docs.docsMd(c)),
	'/status.md': (c) => markdown(docs.statusMd(c)),

	// Agentenspezifische Markdown-Dokumente
	'/agents.md': (c) => markdown(docs.agentsMd(c)),
	'/agent.md': (c) => markdown(docs.agentsMd(c)),
	'/skill.md': (c) => markdown(docs.agentsMd(c)),
	'/auth.md': (c) => markdown(docs.authMd(c)),
	'/api.md': (c) => markdown(docs.apiMd(c)),

	// Indexdateien
	'/robots.txt': (c) => text(docs.robotsTxt(c), 'text/plain'),
	'/sitemap.xml': (c) => text(docs.sitemapXml(c), 'application/xml'),
	'/schema-map.xml': (c) => text(docs.schemaMapXml(c), 'application/xml'),
	'/feeds/site.jsonl': (c) => text(docs.siteJsonl(c), 'application/x-ndjson'),
	'/feeds/faq.jsonl': (c) => text(docs.faqJsonl(c), 'application/x-ndjson'),

	// Well-Known
	'/.well-known/ard.json': (c) => json(docs.ardJson(c)),
	'/.well-known/ai-catalog.json': (c) => json(docs.ardJson(c)),
	'/.well-known/agent-card.json': (c) => json(docs.agentCardJson(c)),
	'/.well-known/agent.json': (c) => json(docs.agentCardJson(c)),
	'/.well-known/agent-skills/index.json': (c) => json(docs.agentSkillsJson(c)),
	'/.well-known/mcp/server-card.json': (c) => json(docs.mcpServerCardJson(c)),
	'/.well-known/api-catalog': (c) =>
		json(docs.apiCatalogJson(c), 'application/linkset+json;profile="https://www.rfc-editor.org/info/rfc9727"')
};

/** Pfad ohne abschließenden Schrägstrich, damit `/llms.txt/` dasselbe trifft. */
export const normalize = (pathname: string): string =>
	pathname !== '/' && pathname.endsWith('/') ? pathname.slice(0, -1) : pathname;

/** Ob dieser Pfad dem Verteiler gehört — ohne Netzwerkaufruf beantwortbar. */
export function handles(pathname: string): boolean {
	const path = normalize(pathname);
	return path in ROUTES || path === '/ask' || path === '/openapi.json' || path === '/api';
}

/** Markdown-Zwilling zu einer HTML-Seite, für die Aushandlung über `Accept`. */
export function markdownTwin(pathname: string, ctx: AgentContext): Response | null {
	const page = pageFor(pathname);
	if (!page) return null;
	const builder = ROUTES[page.markdown];
	return builder ? builder(ctx) : null;
}

/**
 * Der 401-Hinweis an der API-Wurzel.
 *
 * `GET /api` ist kein Endpunkt — genau deshalb ist er der richtige Ort für die
 * Auskunft, wie man sich hier anmeldet. Ein Agent erfährt sie so aus *einer*
 * Anfrage, statt Well-Known-Pfade zu raten.
 */
function apiChallenge(ctx: AgentContext): Response {
	const metadata = ctx.mcpEnabled
		? `${ctx.base}/.well-known/oauth-protected-resource/mcp`
		: `${ctx.base}/.well-known/oauth-protected-resource`;
	return new Response(
		JSON.stringify(
			{
				error: 'unauthorized',
				error_description:
					'Die ConvoyPlan-REST-API verlangt ein Bearer-JWT aus POST /api/auth/login oder einen API-Key im Header X-API-Key.',
				resource_metadata: metadata,
				documentation: `${ctx.base}/auth.md`,
				openapi: `${ctx.base}/openapi.json`
			},
			null,
			2
		),
		{
			status: 401,
			headers: {
				'content-type': 'application/json; charset=utf-8',
				'www-authenticate': `Bearer realm="ConvoyPlan", resource_metadata="${metadata}"`,
				link: `<${ctx.base}/openapi.json>; rel="service-desc"; type="application/vnd.oai.openapi+json;version=3.1", <${ctx.base}/auth.md>; rel="describedby"; type="text/markdown"`,
				'cache-control': 'no-store',
				'access-control-allow-origin': '*'
			}
		}
	);
}

/** Die öffentliche OpenAPI-Beschreibung, aus dem Backend durchgereicht. */
async function publicOpenapi(fetchFn: typeof fetch, ctx: AgentContext): Promise<Response> {
	try {
		const resp = await fetchFn(`${BACKEND}/api/public/openapi.json`, {
			headers: { 'x-forwarded-host': new URL(ctx.base).host, 'x-public-base-url': ctx.base },
			signal: AbortSignal.timeout(5000)
		});
		if (!resp.ok) {
			return json({ error: 'openapi_unavailable', status: resp.status }, 'application/json');
		}
		return new Response(await resp.text(), {
			headers: {
				'content-type': 'application/vnd.oai.openapi+json;version=3.1; charset=utf-8',
				'cache-control': CACHE_HEADER,
				'access-control-allow-origin': '*'
			}
		});
	} catch {
		return json({ error: 'openapi_unavailable' }, 'application/json');
	}
}

/**
 * Die Anfrage beantworten, wenn sie einem Agentenpfad gilt — sonst `null`,
 * und SvelteKit macht weiter wie bisher.
 */
export async function dispatch(
	url: URL,
	request: Request,
	fetchFn: typeof fetch
): Promise<Response | null> {
	if (!discoveryEnabled()) return null;

	const path = normalize(url.pathname);
	// Erst prüfen, ob der Pfad überhaupt uns gehört. `buildContext` fragt das
	// Backend; das darf nicht an jedem Seitenaufruf hängen.
	if (!handles(path)) return null;

	if (request.method === 'OPTIONS') {
		return new Response(null, {
			status: 204,
			headers: {
				'access-control-allow-origin': '*',
				'access-control-allow-methods': 'GET, POST, HEAD, OPTIONS',
				'access-control-allow-headers': 'Content-Type, Accept, Prefer, Authorization'
			}
		});
	}

	const ctx = await buildContext(url, fetchFn);

	const builder = ROUTES[path];
	if (builder) return builder(ctx);

	if (path === '/openapi.json') return publicOpenapi(fetchFn, ctx);

	if (path === '/ask') {
		const query = await ask.readQuery(request, url);
		return ask.wantsStream(request, url) ? ask.streamResponse(query, ctx) : ask.jsonResponse(query, ctx);
	}

	// `/api` selbst ist kein Endpunkt; Caddy reicht nur `/api/*` weiter.
	if (path === '/api' && request.method !== 'POST') return apiChallenge(ctx);

	return null;
}

// ── Kopfzeilen und Sonderansichten ──────────────────────────────────────

/**
 * `Link`-Kopfzeilen nach RFC 8288: Sitemap, Markdown-Zwilling,
 * API-Beschreibung und Katalog. Ein Agent, der nur die Kopfzeilen liest,
 * findet damit alles Weitere.
 */
export function linkHeader(pathname: string, base: string): string {
	const page = pageFor(pathname);
	const parts = [
		`<${base}/sitemap.xml>; rel="sitemap"; type="application/xml"`,
		`<${base}/llms.txt>; rel="describedby"; type="text/plain"`,
		`<${base}/openapi.json>; rel="service-desc"; type="application/vnd.oai.openapi+json;version=3.1"`,
		`<${base}/.well-known/api-catalog>; rel="api-catalog"`,
		`<${base}/.well-known/agent-card.json>; rel="service-meta"; type="application/json"`
	];
	if (page) {
		parts.unshift(`<${base}${page.markdown}>; rel="alternate"; type="text/markdown"`);
		parts.push(`<${base}${page.path}>; rel="canonical"`);
	}
	return parts.join(', ');
}

export function prefersMarkdown(accept: string): boolean {
	if (!accept) return false;
	// Nur wenn Markdown ausdrücklich gewünscht ist und HTML nicht bevorzugt wird.
	if (!accept.includes('text/markdown')) return false;
	const mdQ = qualityOf(accept, 'text/markdown');
	const htmlQ = Math.max(qualityOf(accept, 'text/html'), qualityOf(accept, 'application/xhtml+xml'));
	return mdQ >= htmlQ;
}

function qualityOf(accept: string, type: string): number {
	for (const part of accept.split(',')) {
		const [mime, ...params] = part.trim().split(';');
		if (mime.trim().toLowerCase() !== type) continue;
		const q = params.map((p) => p.trim()).find((p) => p.startsWith('q='));
		return q ? Number.parseFloat(q.slice(2)) || 0 : 1;
	}
	return 0;
}

/**
 * Der Agentenmodus (`?mode=agent`): eine maschinenlesbare Fassung der Seite
 * statt der Oberfläche. Kein Marketing, sondern Endpunkte, Zugang, Fähigkeiten.
 */
export function agentModeView(pathname: string, ctx: AgentContext): Response {
	const page = pageFor(pathname);
	const body = {
		name: 'ConvoyPlan',
		mode: 'agent',
		instance: ctx.base,
		page: page
			? { path: page.path, title: page.title, description: page.summary, markdown: `${ctx.base}${page.markdown}` }
			: { path: pathname },
		instructions: `${ctx.base}/agents.md`,
		index: `${ctx.base}/llms.txt`,
		authentication: {
			documentation: `${ctx.base}/auth.md`,
			methods: [
				{ type: 'apiKey', in: 'header', name: 'X-API-Key' },
				{ type: 'http', scheme: 'bearer', bearerFormat: 'JWT', tokenEndpoint: `${ctx.base}/api/auth/login` },
				...(ctx.mcpEnabled
					? [
							{
								type: 'oauth2',
								authorizationEndpoint: `${ctx.base}/authorize`,
								tokenEndpoint: `${ctx.base}/token`,
								metadata: `${ctx.base}/.well-known/oauth-authorization-server`
							}
						]
					: [])
			]
		},
		endpoints: {
			rest: `${ctx.base}/api`,
			openapi: `${ctx.base}/openapi.json`,
			mcp: ctx.mcpEnabled ? `${ctx.base}/mcp` : null,
			websocket: `${ctx.base}/api/ws/track/`,
			ask: `${ctx.base}/ask`,
			status: `${ctx.base}/api/status/public`
		},
		discovery: {
			agentCard: `${ctx.base}/.well-known/agent-card.json`,
			agentSkills: `${ctx.base}/.well-known/agent-skills/index.json`,
			ard: `${ctx.base}/.well-known/ard.json`,
			mcpServerCard: `${ctx.base}/.well-known/mcp/server-card.json`,
			apiCatalog: `${ctx.base}/.well-known/api-catalog`,
			sitemap: `${ctx.base}/sitemap.xml`
		},
		pages: PAGES.map((p) => ({
			path: `${ctx.base}${p.path}`,
			markdown: `${ctx.base}${p.markdown}`,
			title: p.title,
			description: p.summary
		})),
		sandbox: ctx.demoEnabled ? `${ctx.base}/demo` : null
	};
	return new Response(JSON.stringify(body, null, 2), {
		headers: {
			'content-type': 'application/json; charset=utf-8',
			'cache-control': 'no-store',
			vary: 'Accept',
			'access-control-allow-origin': '*'
		}
	});
}

/** Ein 404, das auch für eine Maschine brauchbar ist. */
export function notFoundMarkdown(pathname: string, ctx: AgentContext): Response {
	const body = `# 404 — Seite nicht gefunden

Der Pfad \`${pathname}\` existiert auf dieser ConvoyPlan-Instanz (${ctx.base}) nicht.
Möglich ist auch, dass die Funktion dahinter auf dieser Instanz abgeschaltet ist:
ConvoyPlan ist self-hosted, und der Betreiber entscheidet, was montiert wird.

Von hier kommst du weiter:

- [llms.txt](${ctx.base}/llms.txt) — Einstieg und Wegweiser für Agenten
- [sitemap.xml](${ctx.base}/sitemap.xml) — alle öffentlichen Seiten
- [agents.md](${ctx.base}/agents.md) — wann und wie ConvoyPlan aufzurufen ist
- [auth.md](${ctx.base}/auth.md) — Zugangsdaten beschaffen
- [openapi.json](${ctx.base}/openapi.json) — die öffentlichen API-Endpunkte
- [Startseite](${ctx.base}/)

Suchen statt raten: \`GET ${ctx.base}/ask?query=…\` beantwortet Fragen über ConvoyPlan
mit einer Liste passender Seiten.
`;
	return new Response(body, {
		status: 404,
		headers: {
			'content-type': 'text/markdown; charset=utf-8',
			'cache-control': 'no-store',
			vary: 'Accept',
			'access-control-allow-origin': '*'
		}
	});
}
