import type { Handle } from '@sveltejs/kit';

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

	return resolve(event);
};
