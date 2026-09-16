/**
 * NLWeb-Endpunkt (`/ask`) — https://github.com/microsoft/NLWeb
 *
 * Bewusst klein gehalten: das ist eine Suche über den eigenen Seitenkatalog und
 * die FAQ, kein Sprachmodell. Eine Instanz von ConvoyPlan hat kein Budget für
 * eine Einbettungsdatenbank, und ein Endpunkt, der ehrlich sagt „das sind die
 * Seiten, die zu deiner Frage passen", ist für einen Agenten mehr wert als ein
 * erfundener Fließtext.
 *
 * Nicht durchsucht werden Organisationsdaten. `/ask` beantwortet Fragen *über*
 * ConvoyPlan, nicht Fragen *an* eine Instanz — dafür gibt es die API und MCP.
 */
import { PRODUCT, FAQ } from '$lib/agent/facts';
import { PAGES } from '$lib/agent/pages';
import type { AgentContext } from './documents';

const VERSION = '0.1';

interface Hit {
	readonly score: number;
	readonly item: Record<string, unknown>;
}

/** Wörter ab drei Zeichen, kleingeschrieben, ohne Satzzeichen und Umlaut-Ärger. */
function tokenize(text: string): string[] {
	return text
		.toLowerCase()
		.replace(/ä/g, 'ae')
		.replace(/ö/g, 'oe')
		.replace(/ü/g, 'ue')
		.replace(/ß/g, 'ss')
		.split(/[^a-z0-9]+/)
		.filter((w) => w.length >= 3);
}

function overlap(query: string[], haystack: string): number {
	const words = new Set(tokenize(haystack));
	let hits = 0;
	for (const q of query) {
		if (words.has(q)) hits += 1;
		// Teiltreffer: „lizenzen" soll auf „lizenz" greifen.
		else if ([...words].some((w) => w.startsWith(q) || q.startsWith(w))) hits += 0.5;
	}
	return hits;
}

export function search(query: string, ctx: AgentContext): Hit[] {
	const q = tokenize(query);
	if (q.length === 0) return [];
	const { base } = ctx;
	const hits: Hit[] = [];

	for (const page of PAGES) {
		const score =
			overlap(q, page.keywords.join(' ')) * 2 + overlap(q, page.title) * 1.5 + overlap(q, page.summary);
		if (score > 0) {
			hits.push({
				score,
				item: {
					'@type': 'WebPage',
					url: `${base}${page.path}`,
					name: page.title,
					description: page.summary,
					inLanguage: PRODUCT.inLanguage,
					encodingFormat: 'text/markdown',
					markdownUrl: `${base}${page.markdown}`
				}
			});
		}
	}

	for (const [i, item] of FAQ.entries()) {
		const score = overlap(q, item.q) * 2 + overlap(q, item.a) * 0.5;
		if (score > 0) {
			hits.push({
				score,
				item: {
					'@type': 'Question',
					url: `${base}/#faq-${i + 1}`,
					name: item.q,
					acceptedAnswer: { '@type': 'Answer', text: item.a },
					inLanguage: PRODUCT.inLanguage
				}
			});
		}
	}

	return hits.sort((a, b) => b.score - a.score).slice(0, 8);
}

function envelope(query: string, hits: Hit[], ctx: AgentContext) {
	return {
		_meta: {
			response_type: hits.length > 0 ? 'list' : 'no_results',
			version: VERSION,
			protocol: 'nlweb',
			site: ctx.base,
			query,
			result_count: hits.length,
			generated_at: new Date().toISOString()
		},
		query_id: `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`,
		site: ctx.base,
		query,
		results: hits.map((h, rank) => ({
			'@context': 'https://schema.org',
			rank: rank + 1,
			score: Math.round(h.score * 100) / 100,
			...h.item
		})),
		...(hits.length === 0
			? {
					message: `Keine passende Seite gefunden. Der Einstieg für Agenten liegt unter ${ctx.base}/llms.txt, die Dokumentation unter ${ctx.base}/docs.`
				}
			: {})
	};
}

/** Die Anfrage aus Query-String oder JSON-Body herausholen. */
export async function readQuery(request: Request, url: URL): Promise<string> {
	const fromUrl = url.searchParams.get('query') ?? url.searchParams.get('q');
	if (fromUrl) return fromUrl;
	if (request.method !== 'POST') return '';
	try {
		const raw = await request.text();
		if (!raw) return '';
		try {
			const body = JSON.parse(raw) as Record<string, unknown>;
			const value = body.query ?? body.q ?? body.question ?? body.prompt;
			return typeof value === 'string' ? value : '';
		} catch {
			// Auch `query=…` als Formular-Body annehmen.
			return new URLSearchParams(raw).get('query') ?? '';
		}
	} catch {
		return '';
	}
}

/** Ob der Aufrufer einen Stream will (NLWeb: `prefer: streaming=true` oder `streaming=1`). */
export function wantsStream(request: Request, url: URL): boolean {
	const param = (url.searchParams.get('streaming') ?? '').toLowerCase();
	if (param === 'true' || param === '1') return true;
	const prefer = (request.headers.get('prefer') ?? '').toLowerCase();
	if (prefer.includes('streaming=true') || prefer.includes('streaming')) return true;
	const accept = request.headers.get('accept') ?? '';
	return accept.includes('text/event-stream');
}

export function jsonResponse(query: string, ctx: AgentContext): Response {
	const payload = envelope(query, search(query, ctx), ctx);
	return new Response(JSON.stringify(payload, null, 2), {
		headers: {
			'content-type': 'application/json; charset=utf-8',
			'cache-control': 'no-store',
			'access-control-allow-origin': '*'
		}
	});
}

export function streamResponse(query: string, ctx: AgentContext): Response {
	const hits = search(query, ctx);
	const payload = envelope(query, hits, ctx);
	const encoder = new TextEncoder();
	const event = (type: string, data: unknown) =>
		encoder.encode(`event: ${type}\ndata: ${JSON.stringify(data)}\n\n`);

	const stream = new ReadableStream<Uint8Array>({
		start(controller) {
			controller.enqueue(event('start', { _meta: payload._meta, query_id: payload.query_id, query }));
			for (const result of payload.results) {
				controller.enqueue(event('result', result));
			}
			controller.enqueue(
				event('complete', {
					_meta: payload._meta,
					query_id: payload.query_id,
					result_count: payload.results.length
				})
			);
			controller.close();
		}
	});

	return new Response(stream, {
		headers: {
			'content-type': 'text/event-stream; charset=utf-8',
			'cache-control': 'no-store',
			connection: 'keep-alive',
			'x-accel-buffering': 'no',
			'access-control-allow-origin': '*'
		}
	});
}
