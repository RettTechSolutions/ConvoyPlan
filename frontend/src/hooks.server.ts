import type { Handle } from '@sveltejs/kit';
import * as agent from '$lib/server/agent/dispatch';

const BACKEND = 'http://backend:8000';

// hop-by-hop headers that must not be forwarded
const HOP_BY_HOP = new Set([
	'host', 'connection', 'keep-alive', 'proxy-authenticate',
	'proxy-authorization', 'te', 'trailers', 'transfer-encoding', 'upgrade',
	'content-length', // recalculated by fetch after buffering
]);

export const handle: Handle = async ({ event, resolve }) => {
	const ua = event.request.headers.get('user-agent') ?? '';
	console.log(`[req] ${event.request.method} ${event.url.pathname} — ${ua.slice(0, 60)}`);

	// Maschinenlesbare Auskünfte zuerst: llms.txt, die Well-Known-Dokumente,
	// die Markdown-Zwillinge, /ask und /openapi.json. Der Verteiler prüft den
	// Pfad ohne Netzwerkaufruf und gibt für alles andere sofort `null` zurück.
	// Er steht vor dem API-Proxy, weil /api/llms.txt uns gehört und nicht dem
	// Backend.
	const machineReadable = await agent.dispatch(event.url, event.request, fetch);
	if (machineReadable) return machineReadable;

	if (event.url.pathname.startsWith('/api/')) {
		const url = `${BACKEND}${event.url.pathname}${event.url.search}`;

		const reqHeaders: Record<string, string> = {};
		event.request.headers.forEach((value, key) => {
			if (!HOP_BY_HOP.has(key.toLowerCase())) reqHeaders[key] = value;
		});

		const isGetOrHead = ['GET', 'HEAD'].includes(event.request.method);
		const body = isGetOrHead ? undefined : await event.request.arrayBuffer();

		let response: Response;
		try {
			response = await fetch(url, {
				method: event.request.method,
				headers: reqHeaders,
				body: body,
			});
		} catch (err) {
			console.error(`[proxy] ${event.request.method} ${url} → fetch error:`, err);
			return new Response(JSON.stringify({ detail: 'Proxy error' }), { status: 502 });
		}

		const resHeaders = new Headers();
		response.headers.forEach((value, key) => {
			// skip headers the Node http server manages itself
			if (!['transfer-encoding', 'connection'].includes(key.toLowerCase())) {
				resHeaders.set(key, value);
			}
		});

		return new Response(response.body, {
			status: response.status,
			headers: resHeaders,
		});
	}

	// Ab hier geht es um die Seiten selbst. Alles Folgende ist abschaltbar —
	// eine rein interne Instanz muss Agenten nichts anbieten.
	if (agent.discoveryEnabled() && !event.url.pathname.startsWith('/_app/')) {
		const accept = event.request.headers.get('accept') ?? '';

		if (event.url.searchParams.get('mode') === 'agent') {
			const ctx = await agent.buildContext(event.url, fetch);
			return agent.agentModeView(event.url.pathname, ctx);
		}

		// Markdown gibt es, wer danach fragt. Bewusst *nicht* nach User-Agent:
		// unterschiedliche Inhalte je nach Crawler-Kennung wären Cloaking, und
		// seit die Seiten ihren Inhalt serverseitig ausliefern (siehe
		// +page.server.ts und das JSON-LD im Layout) hätte ein Bot davon auch
		// nichts — das HTML trägt dasselbe.
		if (agent.prefersMarkdown(accept)) {
			const ctx = await agent.buildContext(event.url, fetch);
			const twin = agent.markdownTwin(event.url.pathname, ctx);
			if (twin) return twin;
			// Kein Zwilling: die Seite normal ausliefern. Ist sie gar nicht da,
			// übernimmt der 404-Zweig weiter unten und antwortet in Markdown.
		}
	}

	const response = await resolve(event);

	if (agent.discoveryEnabled()) {
		const type = response.headers.get('content-type') ?? '';
		if (type.includes('text/html')) {
			// Ein 404 für eine Maschine ist ein Markdown-Dokument mit Wegweiser,
			// kein SPA-Rumpf mit Statuszeile.
			if (response.status === 404 && agent.prefersMarkdown(event.request.headers.get('accept') ?? '')) {
				const ctx = await agent.buildContext(event.url, fetch);
				return agent.notFoundMarkdown(event.url.pathname, ctx);
			}
			// `Vary: Accept`, weil dieselbe URL je nach Wunsch HTML oder
			// Markdown liefert — ohne das cacht ein Proxy die falsche Fassung.
			appendVary(response.headers, 'Accept');
			const existing = response.headers.get('link');
			const ours = agent.linkHeader(event.url.pathname, event.url.origin);
			response.headers.set('link', existing ? `${existing}, ${ours}` : ours);
		}
	}

	return response;
};

function appendVary(headers: Headers, value: string): void {
	const current = headers.get('vary');
	if (!current) {
		headers.set('vary', value);
		return;
	}
	const parts = current.split(',').map((p) => p.trim().toLowerCase());
	if (!parts.includes(value.toLowerCase())) headers.set('vary', `${current}, ${value}`);
}
