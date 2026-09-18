export function getBaseUrl(): string {
	if (import.meta.env.VITE_API_URL) return import.meta.env.VITE_API_URL;
	return '';
}

/**
 * Welche Sitzung eine Anfrage meint.
 *
 * `'seite'` (Standard) — die Organisation, auf deren Seite der Aufruf
 * geschieht. `null` — ausdrücklich die organisationslose (Superadmin-)
 * Sitzung; das brauchen genau die Aufrufe des `auth`-Stores.
 */
export type Sitzung = 'seite' | null;

// Dieselbe Form, die `Organization._slugify` erzeugt und die das Backend in
// `cookies.ist_gueltiger_slug` noch einmal prüft.
const ORG_PFAD = /^\/o\/([a-z0-9]+(?:-[a-z0-9]+)*)(?:\/|$)/;
const SLUG_MAX = 80;

/**
 * Ein Organisations-Slug am Anfang des Pfades: `/o/<slug>/…`, sonst `null`.
 *
 * Was nicht wie ein Slug aussieht, wird gar nicht erst angekündigt und führt
 * damit auf die globale Sitzung — also auf genau das, was ohne den Kopf
 * ohnehin gälte. Das Backend verfährt mit einem unbrauchbaren Kopf genauso.
 */
export function orgSlugAusPfad(pfad: string): string | null {
	const slug = ORG_PFAD.exec(pfad)?.[1];
	return slug && slug.length <= SLUG_MAX ? slug : null;
}

/**
 * Die Organisation, um die es gerade geht — aus der Adresszeile.
 *
 * Vorher stand sie in einer Modulvariablen, die das Org-Layout vor seinen
 * Aufrufen setzte. Das war eine Wette auf die Reihenfolge der `onMount`s,
 * und die ging verloren: das Org-Layout mountet **vor** dem Wurzel-Layout,
 * dessen `auth.init()` die Variable auf `null` zurücksetzte — danach ging
 * jede Anfrage der Seite ohne `X-Org-Slug` hinaus und landete auf der
 * globalen Sitzung. Wer zusätzlich als Superadmin angemeldet war, bekam
 * deshalb „Org context required", alle anderen ein 401; sichtbar wurde es
 * beim harten Laden einer Org-Seite (Tracking-Ansicht im neuen Tab, F5).
 *
 * Die Adresse ist die ehrlichere Quelle: sie gilt für *diese* Anfrage,
 * überlebt keinen Seitenwechsel und kennt keine Reihenfolge.
 */
export function getActiveSlug(): string | null {
	if (typeof location === 'undefined') return null;
	return orgSlugAusPfad(location.pathname);
}

/**
 * Die Anmeldung liegt im HttpOnly-Cookie, nicht mehr im `localStorage`.
 *
 * Vorher stand das Zugriffstoken unter `token` bzw. `token__<slug>` im
 * `localStorage` und wurde hier in jeden `Authorization`-Header geschrieben.
 * Damit konnte es aber auch jedes andere Skript auf der Seite lesen — und
 * ein siebentägig gültiges Token, das einmal abgeflossen ist, ist eine Woche
 * lang eine vollwertige Anmeldung von einem beliebigen Rechner aus.
 *
 * Jetzt schickt der Browser das Cookie von sich aus mit (`credentials`), und
 * JavaScript kommt an den Wert nicht mehr heran. Der Preis sind zwei Header:
 *
 * - `X-Org-Slug` wählt aus, welche Organisationssitzung gemeint ist — es gibt
 *   eine je Organisation, weil man sich in ConvoyPlan pro Organisation
 *   getrennt anmeldet. Der Slug steht ohnehin in der URL, er ist kein
 *   Geheimnis; er zeigt nur auf das richtige Cookie.
 * - `X-Requested-With` ist der CSRF-Schutz. Ein Cookie schickt der Browser
 *   auch dann mit, wenn eine fremde Seite die Anfrage auslöst; einen eigenen
 *   Header kann fremdes JavaScript aber nur nach einem CORS-Preflight setzen,
 *   und den beantwortet das Backend nur für den eigenen Ursprung. Ein
 *   Formular-POST von außen kann ihn gar nicht setzen.
 */
const CSRF_HEADER = 'X-Requested-With';
const CSRF_VALUE = 'ConvoyPlan';
const ORG_SLUG_HEADER = 'X-Org-Slug';

/**
 * Die Header, die eine Anfrage mit Cookie-Anmeldung braucht.
 *
 * Exportiert für die wenigen Stellen, die `fetch` direkt aufrufen, weil
 * sie etwas brauchen, was `api` nicht kann — ein `AbortSignal` etwa. Wer
 * sie vergisst, bekommt bei ändernden Methoden ein 403 statt einer stillen
 * Fehlfunktion; das ist Absicht.
 */
export function authHeaders(
	base: Record<string, string> = {},
	sitzung: Sitzung = 'seite'
): Record<string, string> {
	const headers: Record<string, string> = { ...base, [CSRF_HEADER]: CSRF_VALUE };
	const slug = sitzung === null ? null : getActiveSlug();
	if (slug) headers[ORG_SLUG_HEADER] = slug;
	return headers;
}

/**
 * Hinterlassenschaften der alten Token-Ablage entfernen.
 *
 * Wer schon angemeldet war, hat die Tokens noch im `localStorage` liegen.
 * Gelesen werden sie nicht mehr, aber liegenlassen hieße: das, was hier
 * gerade aus der Reichweite von Skripten geholt wurde, bleibt daneben noch
 * bis zu sieben Tage in ihrer Reichweite liegen. Wird beim Start einmal
 * aufgeräumt.
 */
export function purgeLegacyTokens(): void {
	if (typeof localStorage === 'undefined') return;
	try {
		const keys: string[] = [];
		for (let i = 0; i < localStorage.length; i++) {
			const key = localStorage.key(i);
			if (key === 'token' || key?.startsWith('token__')) keys.push(key);
		}
		for (const key of keys) localStorage.removeItem(key);
	} catch {
		/* Privater Modus o. ä. — dann gibt es auch nichts aufzuräumen. */
	}
}

/**
 * Exchange the bearer token for a short-lived (60 s) stream ticket usable in
 * SSE/WebSocket URLs, which cannot carry an Authorization header. Avoids
 * putting the long-lived access token in the URL (proxy logs / history).
 * Returns null if not authenticated or the request fails.
 */
export async function getStreamTicket(): Promise<string | null> {
	try {
		const res = await fetch(`${getBaseUrl()}/api/auth/stream-ticket`, {
			method: 'POST',
			credentials: 'same-origin',
			headers: authHeaders(),
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
	options: RequestInit = {},
	sitzung: Sitzung = 'seite'
): Promise<T> {
	const headers = authHeaders(
		{
			'Content-Type': 'application/json',
			...(options.headers as Record<string, string>),
		},
		sitzung
	);

	const res = await fetch(`${getBaseUrl()}${path}`, {
		...options,
		credentials: 'same-origin',
		headers,
	});
	if (!res.ok) throw await toApiError(res, 'Request failed');
	if (res.status === 204) return undefined as T;
	return res.json();
}

/**
 * Der letzte Parameter ist überall `sitzung` und fast überall wegzulassen:
 * gemeint ist die Organisation aus der Adresse. Ausdrücklich `null` setzt
 * nur, wer die organisationslose Sitzung meint (siehe `authApi.me`).
 */
export const api = {
	get: <T>(path: string, sitzung: Sitzung = 'seite') => request<T>(path, {}, sitzung),
	post: <T>(path: string, body: unknown, sitzung: Sitzung = 'seite') =>
		request<T>(path, { method: 'POST', body: JSON.stringify(body) }, sitzung),
	put: <T>(path: string, body: unknown, sitzung: Sitzung = 'seite') =>
		request<T>(path, { method: 'PUT', body: JSON.stringify(body) }, sitzung),
	patch: <T>(path: string, body: unknown, sitzung: Sitzung = 'seite') =>
		request<T>(path, { method: 'PATCH', body: JSON.stringify(body) }, sitzung),
	delete: <T = void>(path: string, sitzung: Sitzung = 'seite') =>
		request<T>(path, { method: 'DELETE' }, sitzung),
};

/**
 * Load an authenticated endpoint and hand the response to the browser as a
 * download. Needed wherever the export lives behind a Bearer token — a plain
 * `<a href>` cannot carry the Authorization header.
 */
export async function downloadFile(path: string, filename: string): Promise<void> {
	const res = await fetch(`${getBaseUrl()}${path}`, {
		credentials: 'same-origin',
		headers: authHeaders(),
	});
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
	// Do NOT set Content-Type — browser sets multipart/form-data + boundary automatically
	const formData = new FormData();
	formData.append('file', file);
	const res = await fetch(`${getBaseUrl()}${path}`, {
		method: 'POST',
		credentials: 'same-origin',
		headers: authHeaders(),
		body: formData,
	});
	if (!res.ok) throw await toApiError(res, 'Request failed');
	return res.json() as Promise<T>;
}
