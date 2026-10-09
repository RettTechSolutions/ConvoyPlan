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

// ── Aktionsseiten ────────────────────────────────────────────────────────────
//
// Die Verwaltung im Org-Admin. Wie beim Melde-Dialog legt der Stub ab, was
// abgeschickt wurde — die Zusage „der interne Konvoiname geht nicht hinaus"
// steht im Körper des Aufrufs, nicht auf dem Bildschirm.

export type AktionsseitenThema = 'neutral' | 'weihnachten';
export interface AktionsseiteKonvoi {
	convoy_id: string;
	display_name: string;
	destination_label: string | null;
	color: string | null;
}
export interface AktionsseiteDaten {
	title: string;
	subtitle: string | null;
	facts: string | null;
	theme: AktionsseitenThema;
	delay_minutes: number;
	show_destination: boolean;
	valid_until: string | null;
	enabled: boolean;
	convoys: AktionsseiteKonvoi[];
}
export interface Aktionsseite extends Omit<AktionsseiteDaten, 'convoys'> {
	id: string;
	slug: string;
	active: boolean;
	endpoint: string;
	convoys: (AktionsseiteKonvoi & { convoy_name: string })[];
	created_at: string;
}
export interface AktionsseiteMitToken extends Aktionsseite {
	fetch_token: string;
}
export interface AktionsseiteVorschau {
	title: string;
	delay_minutes: number;
	as_of: string;
	generated_at: string;
	convoys: {
		key: string;
		name: string;
		status: 'vor_abfahrt' | 'unterwegs' | 'pause' | 'angekommen';
		position: { lat: number; lon: number; coarse: boolean; at: string } | null;
		driven_km: number;
		total_km: number | null;
	}[];
}

/** Interne Namen, wie sie in der Planung stehen. */
export const KONVOIS = [
	{ id: 'c-bih', name: 'KV 3 / Los B Ladeliste' },
	{ id: 'c-rou', name: 'KV 1 Sibiu' },
];

/** Das Token, das die Verwaltung genau einmal zeigt. */
export const ABRUF_TOKEN = 'tok_Zr8Qm2Lw5Xc9Vb3Nh7Kp';

declare global {
	interface Window {
		__aktionAngelegt?: AktionsseiteDaten;
	}
}

const seiten: Aktionsseite[] = [];

function zeile(id: string, d: AktionsseiteDaten): Aktionsseite {
	return {
		...d,
		id,
		slug: 'Hq3vT8kLm2Pw',
		active: d.enabled,
		endpoint: 'https://einsatz.example.de/api/public/aktion/Hq3vT8kLm2Pw',
		convoys: d.convoys.map((c) => ({
			...c,
			convoy_name: KONVOIS.find((k) => k.id === c.convoy_id)?.name ?? '',
		})),
		created_at: '2026-10-02T15:00:00Z',
	};
}

export const convoysApi = {
	list: async () => KONVOIS,
};

export const aktionsseitenApi = {
	list: async (): Promise<Aktionsseite[]> => seiten.map((s) => ({ ...s })),
	create: async (d: AktionsseiteDaten): Promise<AktionsseiteMitToken> => {
		window.__aktionAngelegt = d;
		const s = zeile('a-1', d);
		seiten.push(s);
		return { ...s, fetch_token: ABRUF_TOKEN };
	},
	update: async (id: string, d: AktionsseiteDaten): Promise<Aktionsseite> => {
		const s = zeile(id, d);
		seiten.splice(seiten.findIndex((x) => x.id === id), 1, s);
		return s;
	},
	rotateToken: async (id: string): Promise<AktionsseiteMitToken> => ({
		...seiten.find((s) => s.id === id)!,
		fetch_token: 'tok_neu_Pz4Wq8Ln1Hc6',
	}),
	delete: async (id: string) => {
		seiten.splice(seiten.findIndex((x) => x.id === id), 1);
	},
	preview: async (): Promise<AktionsseiteVorschau> => ({
		title: 'Weihnachtskonvois 2026',
		delay_minutes: 120,
		as_of: '2026-12-27T16:00:00Z',
		generated_at: '2026-12-27T18:00:00Z',
		convoys: [
			{
				key: '1', name: 'Konvoi Bosnien', status: 'pause', driven_km: 498,
				total_km: 1120.5,
				position: { lat: 46.05, lon: 14.5072, coarse: true, at: '2026-12-27T15:20:00Z' },
			},
		],
	}),
};

// ── Passkeys (`PasskeyVerwaltung`) ───────────────────────────────────────────
//
// Die Prüfung der Antwort ist Sache des Servers; hier zählt, was die
// Komponente hinausschickt. Jeder Aufruf landet in `window.__passkeyAufrufe`,
// der Test liest ihn von dort.

export interface PasskeyInfo {
	id: string;
	name: string;
	created_at: string;
	last_used_at: string | null;
	backed_up: boolean;
}

export const PASSKEY_CHALLENGE = 'q2Vt8eYp3Lr7Wn1Kc5Xh9Zb4Md6Sf0Ga';
export const PASSKEY_USER_ID = 'dXNlci1pZC1wbGFuZXI';

function passkeyAufruf(name: string, body: unknown) {
	const w = window as unknown as { __passkeyAufrufe?: { name: string; body: unknown }[] };
	(w.__passkeyAufrufe ??= []).push({ name, body });
}

let passkeys: PasskeyInfo[] = [];

export const passkeyApi = {
	list: async () => passkeys,
	registerOptions: async (password: string) => {
		passkeyAufruf('registerOptions', { password });
		return {
			challenge_id: 'ch-1',
			options: {
				rp: { id: 'localhost', name: 'ConvoyPlan' },
				user: { id: PASSKEY_USER_ID, name: 'planer@example.org', displayName: 'Pia Planer' },
				challenge: PASSKEY_CHALLENGE,
				pubKeyCredParams: [{ type: 'public-key', alg: -7 }],
				timeout: 60000,
				excludeCredentials: [],
				authenticatorSelection: { residentKey: 'required', requireResidentKey: true, userVerification: 'required' },
				attestation: 'none',
			},
		};
	},
	register: async (challenge_id: string, credential: Record<string, unknown>, name?: string) => {
		passkeyAufruf('register', { challenge_id, credential, name });
		const neu: PasskeyInfo = {
			id: 'pk-1', name: name ?? 'Passkey', created_at: '2026-10-07T08:00:00Z',
			last_used_at: null, backed_up: false,
		};
		passkeys = [...passkeys, neu];
		return neu;
	},
	remove: async (id: string) => {
		passkeyAufruf('remove', { id });
		passkeys = passkeys.filter((p) => p.id !== id);
	},
};

// ── Kartenregion (Admin-Portal, System) ──────────────────────────────────────
// `?k=region&bau=import|download|haengt|keiner`. Ein Graph-Bau ohne
// Regionswechsel: Die Karte liest ihn aus `status().graph_build`.

export type RegionPhase = string;
export interface GraphBuild {
	phase: 'download' | 'import' | 'haengt';
	since: string | null;
	grace_hours: number;
}
export interface RegionStatus {
	phase: RegionPhase;
	graph_build?: GraphBuild;
}

const bau = new URLSearchParams(location.search).get('bau') ?? 'keiner';
const vorMinuten = (min: number) => new Date(Date.now() - min * 60_000).toISOString();
const GRAPH_BUILD: Record<string, GraphBuild | undefined> = {
	import: { phase: 'import', since: vorMinuten(12), grace_hours: 4 },
	download: { phase: 'download', since: null, grace_hours: 4 },
	haengt: { phase: 'haengt', since: vorMinuten(5 * 60), grace_hours: 4 },
	keiner: undefined,
};

export const regionApi = {
	current: async () => ({
		url: 'https://download.geofabrik.de/europe/dach-latest.osm.pbf',
		filename: 'dach-latest.osm.pbf',
		java_opts: '-Xmx8g',
		sources: ['europe/dach'],
	}),
	preview: async () => ({ extract_bytes: 4_100_000_000, disk_free_bytes: 92_000_000_000 }),
	list: async () => [],
	status: async (): Promise<RegionStatus> => {
		const gb = GRAPH_BUILD[bau];
		return gb ? { phase: 'idle', graph_build: gb } : { phase: 'idle' };
	},
	logStream: async () => null,
	switch: async () => ({ status: 'queued' }),
	cancel: async () => ({ status: 'cancelling' }),
};
