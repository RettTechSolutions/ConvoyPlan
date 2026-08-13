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

/**
 * Fehlgeschlagene Antwort des Backends — mit Statuscode und der Klartext-
 * Begründung aus `detail`. `message` bleibt wie bisher der Text, den bestehende
 * Aufrufer anzeigen; `detail` ist zusätzlich der Marker dafür, dass die
 * Begründung *vom Backend* stammt und nicht aus einem Netzwerkfehler — nur die
 * darf man dem Besucher unverändert vorsetzen.
 */
export class ApiError extends Error {
	readonly status: number;
	readonly detail: string | null;
	/**
	 * Strukturierte Begründung, wenn das Backend statt eines Textes ein Objekt
	 * geschickt hat (`detail: { message, … }`) — etwa der Zeitpunkt, ab dem eine
	 * abgelehnte Demo wieder möglich ist. `detail` bleibt dabei der Text daraus,
	 * bestehende Aufrufer merken vom Unterschied nichts.
	 */
	readonly data: Record<string, unknown> | null;

	constructor(
		status: number,
		detail: string | null,
		fallback: string,
		data: Record<string, unknown> | null = null
	) {
		super(detail ?? fallback);
		this.name = 'ApiError';
		this.status = status;
		this.detail = detail;
		this.data = data;
	}
}

async function toApiError(res: Response, fallback: string): Promise<ApiError> {
	const body = await res.json().catch(() => null);
	const raw = body?.detail;
	// FastAPI liefert bei Validierungsfehlern eine Liste statt eines Textes —
	// die ist nichts, was ein Besucher lesen will.
	const data =
		raw && typeof raw === 'object' && !Array.isArray(raw) ? (raw as Record<string, unknown>) : null;
	const detail =
		typeof raw === 'string'
			? raw
			: typeof data?.message === 'string'
				? (data.message as string)
				: null;
	return new ApiError(res.status, detail, res.statusText || fallback, data);
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
	if (!res.ok) throw await toApiError(res, 'Request failed');
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

/**
 * Load an authenticated endpoint and hand the response to the browser as a
 * download. Needed wherever the export lives behind a Bearer token — a plain
 * `<a href>` cannot carry the Authorization header.
 */
export async function downloadFile(path: string, filename: string): Promise<void> {
	const token = getToken();
	const headers: Record<string, string> = {};
	if (token) headers['Authorization'] = `Bearer ${token}`;
	const res = await fetch(`${getBaseUrl()}${path}`, { headers });
	if (!res.ok) throw await toApiError(res, 'Download fehlgeschlagen');
	const blob = await res.blob();
	const url = URL.createObjectURL(blob);
	const anchor = document.createElement('a');
	anchor.href = url;
	anchor.download = filename;
	document.body.appendChild(anchor);
	anchor.click();
	anchor.remove();
	// Give the browser a moment to start the download before dropping the blob.
	setTimeout(() => URL.revokeObjectURL(url), 60_000);
}

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
	if (!res.ok) throw await toApiError(res, 'Request failed');
	return res.json() as Promise<T>;
}
