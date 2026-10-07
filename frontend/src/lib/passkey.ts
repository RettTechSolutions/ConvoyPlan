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

/** `navigator.credentials.get` mit den Optionen des Servers. */
export async function passkeyAnmelden(options: AnmeldeOptionenJSON): Promise<Record<string, unknown>> {
	const publicKey = {
		...options,
		challenge: ausBase64url(options.challenge),
		allowCredentials: (options.allowCredentials ?? []).map(descriptor),
	} as unknown as PublicKeyCredentialRequestOptions;
	const cred = (await navigator.credentials.get({ publicKey })) as PublicKeyCredential | null;
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
