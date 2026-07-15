export function getBaseUrl(): string {
	if (import.meta.env.VITE_API_URL) return import.meta.env.VITE_API_URL;
	return '';
}

let _activeSlug: string | null = null;

/** Wird vom Org-Guard-Layout gesetzt bevor API-Calls gemacht werden */
export function setActiveSlug(slug: string | null): void {
    _activeSlug = slug;
}

export function getToken(): string | null {
	if (typeof localStorage === 'undefined') return null;
	// Org-scoped token hat Vorrang
	if (_activeSlug) {
		const orgToken = localStorage.getItem(`token__${_activeSlug}`);
		if (orgToken) return orgToken;
	}
	// Fallback: globaler Superadmin-Token
	return localStorage.getItem('token');
}

/**
 * Exchange the bearer token for a short-lived (60 s) stream ticket usable in
 * SSE/WebSocket URLs, which cannot carry an Authorization header. Avoids
 * putting the long-lived access token in the URL (proxy logs / history).
 * Returns null if not authenticated or the request fails.
 */
export async function getStreamTicket(): Promise<string | null> {
	const token = getToken();
	if (!token) return null;
	try {
		const res = await fetch(`${getBaseUrl()}/api/auth/stream-ticket`, {
			method: 'POST',
			headers: { Authorization: `Bearer ${token}` },
		});
		if (!res.ok) return null;
		const data = await res.json().catch(() => null);
		return data?.ticket ?? null;
	} catch {
		return null;
	}
}

async function request<T>(
	path: string,
	options: RequestInit = {}
): Promise<T> {
	const token = getToken();
	const headers: Record<string, string> = {
		'Content-Type': 'application/json',
		...(options.headers as Record<string, string>),
	};
	if (token) headers['Authorization'] = `Bearer ${token}`;

	const res = await fetch(`${getBaseUrl()}${path}`, { ...options, headers });
	if (!res.ok) {
		const err = await res.json().catch(() => ({ detail: res.statusText }));
		throw new Error(err.detail ?? 'Request failed');
	}
	if (res.status === 204) return undefined as T;
	return res.json();
}

export const api = {
	get: <T>(path: string) => request<T>(path),
	post: <T>(path: string, body: unknown) =>
		request<T>(path, { method: 'POST', body: JSON.stringify(body) }),
	put: <T>(path: string, body: unknown) =>
		request<T>(path, { method: 'PUT', body: JSON.stringify(body) }),
	patch: <T>(path: string, body: unknown) =>
		request<T>(path, { method: 'PATCH', body: JSON.stringify(body) }),
	delete: <T = void>(path: string) => request<T>(path, { method: 'DELETE' }),
};

export async function uploadFile<T>(path: string, file: File): Promise<T> {
	const token = getToken();
	const headers: Record<string, string> = {};
	if (token) headers['Authorization'] = `Bearer ${token}`;
	// Do NOT set Content-Type — browser sets multipart/form-data + boundary automatically
	const formData = new FormData();
	formData.append('file', file);
	const res = await fetch(`${getBaseUrl()}${path}`, {
		method: 'POST',
		headers,
		body: formData,
	});
	if (!res.ok) {
		const err = await res.json().catch(() => ({ detail: res.statusText }));
		throw new Error(err.detail ?? 'Request failed');
	}
	return res.json() as Promise<T>;
}
