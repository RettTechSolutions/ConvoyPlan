/**
 * Passkeys im Browser: zwischen dem JSON des Servers und der WebAuthn-API.
 *
 * Der Server liefert die Optionen als JSON mit base64url-Feldern
 * (`options_to_json_dict` aus `py_webauthn`), `navigator.credentials` will
 * ArrayBuffer — und gibt ArrayBuffer zurück, die wieder als base64url zum
 * Server gehen. Die Browser haben dafür inzwischen
 * `PublicKeyCredential.parseCreationOptionsFromJSON` und `toJSON()`, aber
 * nicht alle, die im Einsatz noch laufen (Safari erst ab 18.4). Die paar
 * Zeilen hier ersparen die Fallunterscheidung.
 *
 * Geprüft wird hier nichts: was zählt, entscheidet der Server
 * (`backend/app/services/passkey.py`).
 */

function zuBase64url(puffer: ArrayBuffer): string {
	const bytes = new Uint8Array(puffer);
	let binaer = '';
	for (const b of bytes) binaer += String.fromCharCode(b);
	return btoa(binaer).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
}

function ausBase64url(text: string): ArrayBuffer {
	const b64 = text.replace(/-/g, '+').replace(/_/g, '/') + '='.repeat((4 - (text.length % 4)) % 4);
	const binaer = atob(b64);
	const bytes = new Uint8Array(binaer.length);
	for (let i = 0; i < binaer.length; i++) bytes[i] = binaer.charCodeAt(i);
	return bytes.buffer;
}

type Descriptor = { id: string; type: string; transports?: string[] };

/** Die Optionen, wie der Server sie schickt — Binärfelder als base64url. */
export interface ErstellOptionenJSON {
	challenge: string;
	user: { id: string; name: string; displayName: string };
	excludeCredentials?: Descriptor[];
	[feld: string]: unknown;
}

export interface AnmeldeOptionenJSON {
	challenge: string;
	allowCredentials?: Descriptor[];
	[feld: string]: unknown;
}

function descriptor(d: Descriptor): PublicKeyCredentialDescriptor {
	return {
		id: ausBase64url(d.id),
		type: 'public-key',
		transports: d.transports as AuthenticatorTransport[] | undefined,
	};
}

/** Ob dieser Browser Passkeys überhaupt anbietet — sonst gibt es keinen Knopf. */
export function passkeysVerfuegbar(): boolean {
	return typeof window !== 'undefined' && 'PublicKeyCredential' in window && !!navigator.credentials;
}

/**
 * Der Nutzer hat den Dialog abgebrochen oder er lief ab. Kein Fehler, den man
 * rot anzeigen muss — der Browser sagt dann nur `NotAllowedError`, und das
 * heißt meist genau das.
 */
export function istAbbruch(e: unknown): boolean {
	return e instanceof DOMException && (e.name === 'NotAllowedError' || e.name === 'AbortError');
}

/** `navigator.credentials.create` mit den Optionen des Servers. */
export async function passkeyErstellen(options: ErstellOptionenJSON): Promise<Record<string, unknown>> {
	const publicKey = {
		...options,
		challenge: ausBase64url(options.challenge),
		user: { ...options.user, id: ausBase64url(options.user.id) },
		excludeCredentials: (options.excludeCredentials ?? []).map(descriptor),
	} as unknown as PublicKeyCredentialCreationOptions;
	const cred = (await navigator.credentials.create({ publicKey })) as PublicKeyCredential | null;
	if (!cred) throw new Error('Kein Passkey erstellt');
	const antwort = cred.response as AuthenticatorAttestationResponse;
	return {
		id: cred.id,
		rawId: zuBase64url(cred.rawId),
		type: cred.type,
		response: {
			clientDataJSON: zuBase64url(antwort.clientDataJSON),
			attestationObject: zuBase64url(antwort.attestationObject),
			transports: typeof antwort.getTransports === 'function' ? antwort.getTransports() : [],
		},
		clientExtensionResults: cred.getClientExtensionResults(),
		authenticatorAttachment: cred.authenticatorAttachment ?? undefined,
	};
}

/**
 * `navigator.credentials.get` mit den Optionen des Servers.
 *
 * Ohne `mediation` öffnet der Browser seinen Dialog sofort (Knopf „Mit
 * Passkey anmelden"); mit `'conditional'` wartet die Anfrage still, bis
 * jemand im E-Mail-Feld einen vorgeschlagenen Passkey wählt (Autofill).
 */
export async function passkeyAnmelden(
	options: AnmeldeOptionenJSON,
	weiter: { mediation?: CredentialMediationRequirement; signal?: AbortSignal } = {},
): Promise<Record<string, unknown>> {
	const publicKey = {
		...options,
		challenge: ausBase64url(options.challenge),
		allowCredentials: (options.allowCredentials ?? []).map(descriptor),
	} as unknown as PublicKeyCredentialRequestOptions;
	const cred = (await navigator.credentials.get({ publicKey, ...weiter })) as PublicKeyCredential | null;
	if (!cred) throw new Error('Kein Passkey gewählt');
	const antwort = cred.response as AuthenticatorAssertionResponse;
	return {
		id: cred.id,
		rawId: zuBase64url(cred.rawId),
		type: cred.type,
		response: {
			clientDataJSON: zuBase64url(antwort.clientDataJSON),
			authenticatorData: zuBase64url(antwort.authenticatorData),
			signature: zuBase64url(antwort.signature),
			userHandle: antwort.userHandle ? zuBase64url(antwort.userHandle) : null,
		},
		clientExtensionResults: cred.getClientExtensionResults(),
		authenticatorAttachment: cred.authenticatorAttachment ?? undefined,
	};
}

// ── Autofill ─────────────────────────────────────────────────────────────────

/** Ob der Browser Passkeys im Vorschlagsmenü eines Eingabefelds anbieten kann. */
export async function autofillMoeglich(): Promise<boolean> {
	if (!passkeysVerfuegbar()) return false;
	const pkc = window.PublicKeyCredential as unknown as { isConditionalMediationAvailable?: () => Promise<boolean> };
	try {
		return (await pkc.isConditionalMediationAvailable?.()) === true;
	} catch {
		return false;
	}
}

/** Woher die Challenge kommt und was nach der Antwort des Geräts geschieht —
 *  dieselben zwei Schritte für Knopf und Autofill, je Anmeldeseite. */
export interface PasskeyAblauf {
	optionen: () => Promise<{ challenge_id: string; options: AnmeldeOptionenJSON }>;
	abschliessen: (challenge_id: string, credential: Record<string, unknown>) => Promise<void>;
}

/**
 * So lange wartet eine Autofill-Anfrage, bevor sie mit frischer Challenge neu
 * gestellt wird. Der Server verwirft eine Challenge nach fünf Minuten, die
 * Optionen nennen dem Browser zwei Minuten (`TIMEOUT_MS`) — wer die
 * Anmeldeseite länger offen lässt, soll trotzdem eine gültige einlösen.
 */
export const AUTOFILL_ERNEUERN_MS = 100_000;

/** Kürzer als das bricht keine Anfrage ab, die ein Mensch beendet hat. */
const SOFORT_MS = 1_000;

/**
 * Stellt eine Autofill-Anfrage und hält sie am Leben, bis eine Anmeldung
 * gelingt oder die zurückgegebene Funktion aufgerufen wird.
 *
 * Drei Fälle, in denen danach eine neue Anfrage folgt: die Challenge wird
 * erneuert, der Mensch bricht den Gerätedialog ab, oder der Server lehnt ab
 * (`beiFehler` bekommt dessen Meldung). In jedem anderen Fall hört sie still
 * auf — dann gibt es weiter den Knopf, und ein Browser, der sofort wieder
 * ablehnt, bringt die Seite nicht dazu, im Kreis Challenges abzurufen.
 */
export function starteAutofill(ablauf: PasskeyAblauf, beiFehler: (e: unknown) => void): () => void {
	let gestoppt = false;
	let laufend: AbortController | null = null;
	let uhr: ReturnType<typeof setTimeout> | undefined;

	(async () => {
		if (!(await autofillMoeglich())) return;
		while (!gestoppt) {
			let runde: Awaited<ReturnType<PasskeyAblauf['optionen']>>;
			try {
				runde = await ablauf.optionen();
			} catch {
				return;
			}
			if (gestoppt) return;

			const ctrl = new AbortController();
			laufend = ctrl;
			uhr = setTimeout(() => ctrl.abort(), AUTOFILL_ERNEUERN_MS);
			const begonnen = Date.now();
			let credential: Record<string, unknown>;
			try {
				credential = await passkeyAnmelden(runde.options, { mediation: 'conditional', signal: ctrl.signal });
			} catch (e) {
				clearTimeout(uhr);
				if (gestoppt || ctrl.signal.aborted) continue;
				const abgebrochen = e instanceof DOMException && e.name === 'NotAllowedError';
				if (abgebrochen && Date.now() - begonnen >= SOFORT_MS) continue;
				return;
			}
			clearTimeout(uhr);
			if (gestoppt) return;
			try {
				await ablauf.abschliessen(runde.challenge_id, credential);
				return;
			} catch (e) {
				beiFehler(e);
			}
		}
	})();

	return () => {
		gestoppt = true;
		clearTimeout(uhr);
		laufend?.abort();
	};
}
