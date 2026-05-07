import type { Handle } from '@sveltejs/kit';

const BACKEND = 'http://backend:8000';

export const handle: Handle = async ({ event, resolve }) => {
	if (event.url.pathname.startsWith('/api/')) {
		const url = `${BACKEND}${event.url.pathname}${event.url.search}`;

		const reqHeaders: Record<string, string> = {};
		event.request.headers.forEach((value, key) => {
			if (key.toLowerCase() !== 'host') reqHeaders[key] = value;
		});

		const isGetOrHead = ['GET', 'HEAD'].includes(event.request.method);
		const body = isGetOrHead ? undefined : await event.request.arrayBuffer();

		const response = await fetch(url, {
			method: event.request.method,
			headers: reqHeaders,
			body: body,
		});

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
