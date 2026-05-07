function getBaseUrl(): string {
	if (import.meta.env.VITE_API_URL) return import.meta.env.VITE_API_URL;
	return '';
}

function getToken(): string | null {
	if (typeof localStorage === 'undefined') return null;
	return localStorage.getItem('token');
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
	delete: (path: string) => request<void>(path, { method: 'DELETE' }),
};
