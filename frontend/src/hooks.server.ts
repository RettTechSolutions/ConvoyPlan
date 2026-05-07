import type { Handle } from '@sveltejs/kit';

const BACKEND = 'http://backend:8000';

export const handle: Handle = async ({ event, resolve }) => {
	if (event.url.pathname.startsWith('/api/')) {
		const url = `${BACKEND}${event.url.pathname}${event.url.search}`;

		const reqHeaders = new Headers(event.request.headers);
		reqHeaders.delete('host');

		const response = await fetch(url, {
			method: event.request.method,
			headers: reqHeaders,
			body: ['GET', 'HEAD'].includes(event.request.method) ? undefined : event.request.body,
			// @ts-expect-error Node fetch duplex
			duplex: 'half',
		});

		return new Response(response.body, {
			status: response.status,
			headers: response.headers,
		});
	}

	return resolve(event);
};
