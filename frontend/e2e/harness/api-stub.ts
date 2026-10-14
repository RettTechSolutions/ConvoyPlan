/**
 * Ersatz für `$lib/api` in der Komponentenhülle.
 *
 * Nur das, was `ShareLinkModal` aufruft. Die Daten decken die Fälle ab, an
 * denen sich die Oberfläche entscheidet: offen/passwortgeschützt, Fahrer/Viewer
 * und widerrufen — Letzteres bekommt keinen QR-Knopf.
 */

import type { Tracker, TrackerDaten, TrackerMitCode, TrackerTakt, Vehicle } from '$lib/api';

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
	// `?hersteller=0` spielt den Hosting-Server, sonst eine selbst gehostete Instanz.
	empfaenger: async () => ({
		hersteller: new URLSearchParams(location.search).get('hersteller') !== '0',
	}),
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
	destination_point: { lat: number; lon: number } | null;
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

// ── Telegram für die Aktionsseiten (`TelegramBotKarte`, `FotosVonUnterwegs`) ──
//
// Jeder Aufruf landet in `window.__telegramAufrufe` — der Test prüft dort, dass
// der Token nur an `botSetzen` geht und die Knöpfe die Aufrufe aus § 8.3
// schicken. `?mit_seite=1` legt vorab eine Seite mit einem Konvoi an;
// `?code_s=<n>` lässt Codes nach n Sekunden ablaufen.

export type TelegramBotStatus = 'bereit' | 'privat' | 'ungueltig' | 'konflikt' | 'fehler' | 'ungeprueft';
export interface TelegramBotStand {
	eingerichtet: boolean;
	bot_username?: string | null;
	status?: TelegramBotStatus | null;
	last_error?: string | null;
	checked_at?: string | null;
}
export interface TelegramCode {
	code: string;
	expires_at: string;
}
export interface AktionsseiteTelegram {
	gruppen: { convoy_id: string; chat_title: string | null; thema: boolean }[];
	presse: { telegram_user_id: number; display_name: string; username: string | null; added_at: string }[];
}

declare global {
	interface Window {
		__telegramAufrufe?: [string, ...unknown[]][];
	}
}

export const BOT_TOKEN = '7712345678:AAFh3kQx9Lm2Pw8Zr5Tn1Vb6Yc4Hd0Gs7Jq';

const suche = new URLSearchParams(location.search);
let bot: TelegramBotStand = { eingerichtet: false };
const telegramSeite: AktionsseiteTelegram = {
	gruppen: [],
	presse: [{ telegram_user_id: 55, display_name: 'Anna Presse', username: 'anna_p', added_at: '2026-12-20T10:00:00Z' }],
};

export type BeitragStatus = 'wartet' | 'freigegeben' | 'abgelehnt' | 'zurueckgezogen';
export interface AktionsseiteBeitrag {
	id: string;
	convoy_id: string;
	taken_at: string;
	status: BeitragStatus;
	text_public: string | null;
	text_raw: string | null;
	sender_name: string | null;
	reviewed_at: string | null;
	public_since: string | null;
	photos: { id: string; position: number; width: number; height: number }[];
	link_url?: string | null;
	link_dienst?: 'instagram' | 'youtube' | 'facebook' | 'tiktok' | null;
	not_before?: string | null;
}
export interface BeitragAenderung {
	aktion?: 'frei' | 'ablehnen' | 'zurueck';
	text_public?: string | null;
	not_before?: string | null;
}

let beitraege: AktionsseiteBeitrag[] = [];

function tgAufruf(name: string, ...args: unknown[]) {
	(window.__telegramAufrufe ??= []).push([name, ...args]);
}

function codeBis(): string {
	const s = Number(suche.get('code_s') ?? 900);
	return new Date(Date.now() + s * 1000).toISOString();
}

if (suche.get('mit_seite') === '1') {
	seiten.push(
		zeile('a-1', {
			title: 'Weihnachtskonvois 2026', subtitle: null, facts: null, theme: 'weihnachten',
			delay_minutes: 120, show_destination: false, valid_until: null, enabled: true,
			convoys: [
				{ convoy_id: 'c-bih', display_name: 'Konvoi Bosnien', destination_label: 'Tuzla', destination_point: null, color: null },
				{ convoy_id: 'c-rou', display_name: 'Konvoi Rumänien', destination_label: 'Sibiu', destination_point: null, color: null },
			],
		}),
	);
	telegramSeite.gruppen.push({ convoy_id: 'c-rou', chat_title: 'Weihnachtskonvoi 2026', thema: true });
	const foto = (id: string) => ({ id, position: 0, width: 1600, height: 1200 });
	beitraege = [
		{
			id: 'p-wartet', convoy_id: 'c-bih', taken_at: '2026-12-27T15:10:00Z', status: 'wartet',
			text_public: 'Wir stehen an der A3 bei Würzburg', text_raw: 'Wir stehen an der A3 bei Würzburg',
			sender_name: 'Jonas', reviewed_at: null, public_since: null, photos: [foto('f-1'), { ...foto('f-2'), position: 1 }],
		},
		{
			id: 'p-frei', convoy_id: 'c-rou', taken_at: '2026-12-27T13:40:00Z', status: 'freigegeben',
			text_public: 'Grenze geschafft', text_raw: 'Grenze geschafft', sender_name: 'Mia',
			reviewed_at: '2026-12-27T14:00:00Z', public_since: '2026-12-27T15:41:00Z', photos: [foto('f-3')],
		},
		{
			id: 'p-link', convoy_id: 'c-rou', taken_at: '2026-12-27T12:00:00Z', status: 'abgelehnt',
			text_public: 'Unser Reel', text_raw: 'Unser Reel', sender_name: 'Mia',
			reviewed_at: '2026-12-27T12:30:00Z', public_since: null, photos: [],
			link_url: 'https://www.instagram.com/reel/XyZ/', link_dienst: 'instagram',
		},
	];
}

export const aktionsseitenTelegramApi = {
	bot: async (): Promise<TelegramBotStand> => ({ ...bot }),
	botSetzen: async (token: string): Promise<TelegramBotStand> => {
		tgAufruf('botSetzen', token);
		bot = {
			eingerichtet: true, bot_username: 'AktionsBot',
			status: suche.get('privat') === '1' ? 'privat' : 'bereit',
			last_error: null, checked_at: '2026-12-27T18:00:00Z',
		};
		return { ...bot };
	},
	botEntfernen: async () => {
		tgAufruf('botEntfernen');
		bot = { eingerichtet: false };
	},
	seite: async (id: string): Promise<AktionsseiteTelegram> => {
		tgAufruf('seite', id);
		return structuredClone(telegramSeite);
	},
	verbindenCode: async (id: string, convoyId: string): Promise<TelegramCode> => {
		tgAufruf('verbindenCode', id, convoyId);
		return { code: 'K7Q-2MX', expires_at: codeBis() };
	},
	trennen: async (id: string, convoyId: string) => {
		tgAufruf('trennen', id, convoyId);
		telegramSeite.gruppen = telegramSeite.gruppen.filter((g) => g.convoy_id !== convoyId);
	},
	presseCode: async (id: string): Promise<TelegramCode> => {
		tgAufruf('presseCode', id);
		return { code: '4TR-8LK', expires_at: new Date(Date.now() + 86_400_000).toISOString() };
	},
	presseEntfernen: async (id: string, telegramUserId: number) => {
		tgAufruf('presseEntfernen', id, telegramUserId);
		telegramSeite.presse = telegramSeite.presse.filter((p) => p.telegram_user_id !== telegramUserId);
	},
	beitraege: async (id: string): Promise<AktionsseiteBeitrag[]> => {
		tgAufruf('beitraege', id);
		return structuredClone(beitraege);
	},
	beitragAendern: async (id: string, postId: string, aenderung: BeitragAenderung): Promise<AktionsseiteBeitrag> => {
		tgAufruf('beitragAendern', id, postId, aenderung);
		const b = beitraege.find((x) => x.id === postId)!;
		if ('text_public' in aenderung) b.text_public = aenderung.text_public ?? null;
		if ('not_before' in aenderung) b.not_before = aenderung.not_before ?? null;
		if (aenderung.aktion) {
			b.status = { frei: 'freigegeben', ablehnen: 'abgelehnt', zurueck: 'zurueckgezogen' }[aenderung.aktion] as BeitragStatus;
			if (b.status !== 'freigegeben') b.public_since = null;
		}
		return structuredClone(b);
	},
	bild: async (id: string, photoId: string, groesse: 'gross' | 'klein'): Promise<string> => {
		tgAufruf('bild', id, photoId, groesse);
		// 1×1 PNG — was hier zählt, ist der Weg über den API-Client, nicht das Bild.
		const png = Uint8Array.from(atob('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg=='), (c) => c.charCodeAt(0));
		return URL.createObjectURL(new Blob([png], { type: 'image/png' }));
	},
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
// `?k=region&bau=import|download|haengt|keiner|wartet`. Ein Graph-Bau ohne
// Regionswechsel: Die Karte liest ihn aus `status().graph_build`. `wartet` ist
// ein fälliger geplanter Wechsel, den der Updater bis zum Ende des Baus hält.

export type RegionPhase = string;
export interface GraphBuild {
	phase: 'download' | 'import' | 'haengt';
	since: string | null;
	grace_hours: number;
}
export interface RegionStatus {
	phase: RegionPhase;
	at?: string;
	seen?: boolean;
	scheduled_for?: string;
	graph_build?: GraphBuild;
	waiting_for_graph?: boolean;
}

const bau = new URLSearchParams(location.search).get('bau') ?? 'keiner';
const vorMinuten = (min: number) => new Date(Date.now() - min * 60_000).toISOString();
const GRAPH_BUILD: Record<string, GraphBuild | undefined> = {
	import: { phase: 'import', since: vorMinuten(12), grace_hours: 4 },
	download: { phase: 'download', since: null, grace_hours: 4 },
	haengt: { phase: 'haengt', since: vorMinuten(5 * 60), grace_hours: 4 },
	keiner: undefined,
	wartet: { phase: 'import', since: vorMinuten(12), grace_hours: 4 },
};

// `?quellen=europe/dach,europe/italy` lädt eine zusammengesetzte Karte;
// was der Wechsel abschickt, steht in `window.__regionWechsel`.
declare global {
	interface Window {
		__regionWechsel?: string[];
		__regionLogZeile?: (zeile: string) => void;
	}
}

// `?log=<n>&phase=done|importing`: ein Wechsel mit Log. Der Strom spielt wie
// der echte beim Verbinden alle bisherigen Zeilen ab Byte 0 nach — als ein
// Schwall, so wie sie in einem Netzpaket ankommen, aber jede als eigenes
// Ereignis; bei `done` endet er danach, sonst bleibt er offen, und
// `window.__regionLogZeile` hängt eine weitere Zeile an.
const logZeilen = Number(new URLSearchParams(location.search).get('log') ?? 0);
const logPhase = new URLSearchParams(location.search).get('phase');
// Fest statt relativ: Die Quittung muss über ein Neuladen hinweg passen.
const LOG_ENDE_AT = '2026-10-14T06:08:13Z';
// Die Quittung des Servers (`POST …/seen`) überlebt ein Neuladen wie dort —
// hier in sessionStorage, damit jeder Test frisch anfängt.
const gesehen = () => sessionStorage.getItem('region.gesehen');

function logStrom(): EventSource {
	const lauscher: Record<string, ((e: MessageEvent) => void)[]> = {};
	let offen = true;
	const es = {
		onmessage: null as ((e: MessageEvent) => void) | null,
		onerror: null as (() => void) | null,
		addEventListener(typ: string, fn: (e: MessageEvent) => void) {
			(lauscher[typ] ??= []).push(fn);
		},
		close() {
			offen = false;
		},
	};
	const senden = (data: string) => {
		if (offen) es.onmessage?.(new MessageEvent('message', { data }));
	};
	window.__regionLogZeile = senden;
	void (async () => {
		await new Promise((r) => setTimeout(r, 50));
		for (let i = 1; i <= logZeilen; i++) {
			senden(i === logZeilen ? 'Regionswechsel abgeschlossen' : `INFO Zeile ${i}`);
		}
		if (logPhase === 'done' && offen) {
			for (const fn of lauscher.done ?? []) fn(new MessageEvent('done', { data: 'done' }));
		}
	})();
	return es as unknown as EventSource;
}
const quellen = new URLSearchParams(location.search).get('quellen')?.split(',') ?? ['europe/dach'];

export const regionApi = {
	current: async () => ({
		url: `https://download.geofabrik.de/${quellen[0]}-latest.osm.pbf`,
		filename: quellen.length > 1 ? 'merged-19b731a7.osm.pbf' : 'dach-latest.osm.pbf',
		java_opts: '-Xmx8g',
		sources: quellen,
	}),
	preview: async () => ({
		sources: ['europe/dach'], composed: false, overlapping: [],
		extract_bytes: 4_100_000_000, graph_bytes: 6_000_000_000,
		ram_needed_bytes: 8_000_000_000, ram_available_bytes: 16_000_000_000,
		ram_reclaimable_bytes: 0, ram_effective_available_bytes: 16_000_000_000,
		disk_needed_bytes: 20_000_000_000, disk_free_bytes: 92_000_000_000,
		duration_minutes: [45, 75], verdict: 'ok', reason: 'Reicht.',
	}),
	list: async () => [
		{ id: 'europe/poland', name: 'Poland', path: 'Europe › Poland', url: 'https://download.geofabrik.de/europe/poland-latest.osm.pbf' },
	],
	status: async (): Promise<RegionStatus> => {
		const gb = GRAPH_BUILD[bau];
		if (logPhase) {
			const ende = { phase: logPhase, at: LOG_ENDE_AT };
			return gesehen() === `${logPhase}@${LOG_ENDE_AT}` ? { ...ende, seen: true } : ende;
		}
		if (bau === 'wartet') {
			return { phase: 'scheduled', scheduled_for: vorMinuten(20), graph_build: gb, waiting_for_graph: true };
		}
		return gb ? { phase: 'idle', graph_build: gb } : { phase: 'idle' };
	},
	logStream: async () => (logZeilen ? logStrom() : null),
	switch: async (urls: string[]) => {
		window.__regionWechsel = urls;
		return { status: 'queued' };
	},
	cancel: async () => ({ status: 'cancelling' }),
	seen: async (phase: string, at: string) => {
		if (phase === logPhase && at === LOG_ENDE_AT) sessionStorage.setItem('region.gesehen', `${phase}@${at}`);
	},
};

// ── Ortungsgeräte (`TrackerVerwaltung`) ──────────────────────────────────────
//
// Was die Komponente abschickt, landet in `window.__trackerAngelegt`; der Code
// kommt genau einmal zurück, mit dem Anlegen und beim Neu-Einrichten. Jeder
// Aufruf an die Instanz steht dazu in `window.__trackerAufrufe` — so prüft der
// USB-Test, dass ein WLAN-Passwort nie dorthin geht.

declare global {
	interface Window {
		__trackerAngelegt?: TrackerDaten;
		__trackerTakt?: number;
		__trackerAufrufe?: { name: string; args: unknown[] }[];
		/** Was das Gerät inzwischen gemeldet hat — die nächste Abfrage liefert es. */
		__trackerMelden?: (id: string, felder: Partial<Tracker>) => void;
		/** Ab jetzt antwortet die Liste nicht mehr (hängender Abruf). */
		__trackerHaengt?: boolean;
	}
}

function trackerAufruf(name: string, ...args: unknown[]) {
	(window.__trackerAufrufe ??= []).push({ name, args });
}

export const EINMAL_CODE = 'K7Q2-M9XD';

const FAHRZEUGE = [
	{ id: 'v-hlf', name: 'HLF 20', callsign: 'Florian Peißenberg 40/1' },
	{ id: 'v-mtw', name: 'MTW', callsign: null },
	{ id: 'v-lf', name: 'LF 10', callsign: null },
] as Vehicle[];

const tracker: Tracker[] = [
	{
		id: 't-lf', name: 'Tracker LF 10', vehicle_id: 'v-lf', vehicle_name: 'LF 10', kanal: 'stable',
		aktiv: true, eingerichtet: true, code_offen: false, hardware_id: '352656100000002',
		hardware: 'nrf9151-v1', firmware: '0.1.0', zuletzt_gesehen: new Date().toISOString(),
		akku_prozent: 87, extern: false, akku_seit: new Date(Date.now() - 3 * 86400_000 - 3600_000).toISOString(), signal_dbm: -95, netz: 'mobil', akku_niedrig: false, update_version: null, update_ergebnis: null,
		update_meldung: null, update_at: null, angebot_version: '0.2.0', wurzeln_aktuell: false, created_at: '2026-10-01T09:00:00Z',
	},
];

if (typeof window !== 'undefined')
	window.__trackerMelden = (id, felder) => Object.assign(tracker.find((t) => t.id === id)!, felder);

function trackerZeile(id: string, d: TrackerDaten): Tracker {
	return {
		id, name: d.name, vehicle_id: d.vehicle_id,
		vehicle_name: FAHRZEUGE.find((f) => f.id === d.vehicle_id)?.name ?? null,
		kanal: d.kanal, aktiv: d.aktiv, eingerichtet: false, code_offen: true,
		hardware_id: null, hardware: null, firmware: null, zuletzt_gesehen: null, akku_prozent: null,
		extern: null, akku_seit: null, signal_dbm: null, netz: null, akku_niedrig: false, update_version: null, update_ergebnis: null, update_meldung: null,
		update_at: null, angebot_version: null, wurzeln_aktuell: null, created_at: '2026-10-09T10:00:00Z',
	};
}

export const vehiclesApi = {
	list: async () => FAHRZEUGE,
};

// Wie das Backend (`og.volumen_kb_pro_stunde`), auf ganze KB gerundet.
function taktStub(buendel_s: number): TrackerTakt {
	return {
		buendel_s,
		standard_s: 15,
		intervall_s: 10,
		wahl: [
			{ buendel_s: 10, kb_pro_stunde: 545, kb_pro_stunde_ohne_keepalive: 2345 },
			{ buendel_s: 15, kb_pro_stunde: 377, kb_pro_stunde_ohne_keepalive: 1577 },
			{ buendel_s: 30, kb_pro_stunde: 209, kb_pro_stunde_ohne_keepalive: 809 },
			{ buendel_s: 60, kb_pro_stunde: 125, kb_pro_stunde_ohne_keepalive: 425 },
			{ buendel_s: 120, kb_pro_stunde: 83, kb_pro_stunde_ohne_keepalive: 233 },
		],
	};
}
let taktGesetzt = 15;

export const geraeteApi = {
	list: async (): Promise<Tracker[]> => {
		trackerAufruf('list');
		if (window.__trackerHaengt) return new Promise(() => {});
		return tracker.map((t) => ({ ...t }));
	},
	takt: async (): Promise<TrackerTakt> => taktStub(taktGesetzt),
	taktSetzen: async (buendel_s: number): Promise<TrackerTakt> => {
		trackerAufruf('taktSetzen', buendel_s);
		window.__trackerTakt = buendel_s;
		taktGesetzt = buendel_s;
		return taktStub(buendel_s);
	},
	create: async (d: TrackerDaten): Promise<TrackerMitCode> => {
		trackerAufruf('create', d);
		window.__trackerAngelegt = d;
		const t = trackerZeile('t-neu', d);
		tracker.push(t);
		return { ...t, code: EINMAL_CODE, code_expires_at: '2026-10-10T10:00:00Z' };
	},
	update: async (id: string, d: TrackerDaten): Promise<Tracker> => {
		trackerAufruf('update', id, d);
		const t = { ...trackerZeile(id, d), eingerichtet: true, code_offen: false };
		tracker.splice(tracker.findIndex((x) => x.id === id), 1, t);
		return t;
	},
	rotateCode: async (id: string): Promise<TrackerMitCode> => {
		trackerAufruf('rotateCode', id);
		const t = tracker.find((x) => x.id === id)!;
		Object.assign(t, { eingerichtet: false, code_offen: true });
		return { ...t, code: 'PX3N-7RTF', code_expires_at: '2026-10-10T10:00:00Z' };
	},
	delete: async (id: string) => {
		tracker.splice(tracker.findIndex((x) => x.id === id), 1);
	},
};
