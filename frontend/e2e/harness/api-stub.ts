/**
 * Ersatz für `$lib/api` in der Komponentenhülle.
 *
 * Nur das, was `ShareLinkModal` aufruft. Die Daten decken die Fälle ab, an
 * denen sich die Oberfläche entscheidet: offen/passwortgeschützt, Fahrer/Viewer
 * und widerrufen — Letzteres bekommt keinen QR-Knopf.
 */

export type ShareLinkPasswordMode = 'none' | 'generate' | 'set';
export type ShareLinkScope = 'track' | 'driver';

export interface ShareLink {
	id: string;
	slug: string;
	scope: string;
	requires_password: boolean;
	created_at: string;
	last_accessed_at: string | null;
	access_count: number;
	revoked: boolean;
	url: string;
}

export interface ShareLinkCreated extends ShareLink {
	password_plain: string | null;
}

const LINKS: ShareLink[] = [
	{
		id: 'l-offen', slug: '6dA4KrUG', scope: 'driver', requires_password: false,
		created_at: '2026-09-18T12:22:56Z', last_accessed_at: '2026-09-18T12:23:01Z',
		access_count: 1, revoked: false, url: 'https://demo.convoyplan.de/track/6dA4KrUG',
	},
	{
		id: 'l-geschuetzt', slug: 'pENCIVTf', scope: 'driver', requires_password: true,
		created_at: '2026-09-17T20:04:53Z', last_accessed_at: '2026-09-17T20:05:07Z',
		access_count: 1, revoked: false, url: 'https://demo.convoyplan.de/track/pENCIVTf',
	},
	{
		id: 'l-widerrufen', slug: 'GLhXPSX0', scope: 'track', requires_password: false,
		created_at: '2026-09-17T19:53:32Z', last_accessed_at: '2026-09-17T19:53:39Z',
		access_count: 1, revoked: true, url: 'https://demo.convoyplan.de/track/GLhXPSX0',
	},
];

/** Das Passwort, das der Dialog nach dem Anlegen genau einmal zeigt. */
export const ERZEUGTES_PASSWORT = 'Xh4Kq7Tp2M';

export const shareLinksApi = {
	list: async (): Promise<ShareLink[]> => LINKS,
	create: async (): Promise<ShareLinkCreated> => ({
		id: 'l-neu', slug: 'Nw7Kq2Zt', scope: 'driver', requires_password: true,
		created_at: '2026-09-18T10:40:00Z', last_accessed_at: null, access_count: 0,
		revoked: false, url: 'https://demo.convoyplan.de/track/Nw7Kq2Zt',
		password_plain: ERZEUGTES_PASSWORT,
	}),
	revoke: async (): Promise<void> => {},
};

// ── Melde-Dialog ─────────────────────────────────────────────────────────────

export type FeedbackKind = 'bug' | 'feature';
export type FeedbackSeverity = 'niedrig' | 'normal' | 'hoch' | 'kritisch';

export interface FeedbackPayload {
	kind: FeedbackKind;
	title: string;
	description: string;
	severity: FeedbackSeverity;
	page_url?: string | null;
	user_agent?: string | null;
	app_version?: string | null;
	viewport?: string | null;
	screenshot?: string | null;
}

/**
 * Legt ab, was der Dialog abgeschickt hätte.
 *
 * Genau darum geht es im Test: nicht, ob ein Aufruf stattfand, sondern **was
 * in ihm stand**. Eine Zusage wie „mitgeschickt wird nur, was der Ausklapper
 * nennt" lässt sich an einem Bildschirmfoto nicht ablesen.
 */
declare global {
	interface Window {
		__letzteMeldung?: FeedbackPayload;
		__meldungen?: number;
	}
}

export const feedbackApi = {
	submit: async (data: FeedbackPayload) => {
		window.__letzteMeldung = data;
		window.__meldungen = (window.__meldungen ?? 0) + 1;
		return { id: 'f-1', kind: data.kind, created_at: '2026-09-19T10:00:00Z' };
	},
};
