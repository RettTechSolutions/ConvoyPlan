/**
 * Einrichten eines Trackers per USB aus dem Browser (Web Serial).
 *
 * Das Protokoll steht im Repo ConvoyPlan-Tracker (`docs/PROTOKOLL.md`, „Einrichten per
 * USB"), die Geräteseite setzt dort `simulator/tracker_sim/usb.py` um. Je Zeile ein
 * JSON-Objekt; das Gerät antwortet mit Zwischenständen (`schritt`) und genau einer
 * Schlusszeile mit `ok`.
 *
 * Diese Seite schickt dem Gerät Instanzadresse, Einmal-Code und optional eigene
 * Wurzelzertifikate. Das Gerät löst den Code **selbst** über sein Mobilfunknetz ein —
 * so prüft das Einrichten gleich mit, ob Netz, Adresse und Zertifikat stimmen. Ein Token
 * sieht der Browser nie.
 */

export const PROTOKOLL = 1;
export const WURZELN_MAX = 3;
/** Die erste Anmeldung im Mobilfunknetz kann dauern. */
export const EINRICHTEN_MS = 180_000;
const INFO_MS = 5_000;

/** Der Teil von `SerialPort`, den diese Datei braucht — so lässt er sich im Test nachbauen. */
export interface SeriellerAnschluss {
	open(optionen: { baudRate: number }): Promise<void>;
	close(): Promise<void>;
	readonly readable: ReadableStream<Uint8Array> | null;
	readonly writable: WritableStream<Uint8Array> | null;
}

interface SerialLike {
	requestPort(optionen?: object): Promise<SeriellerAnschluss>;
}

export interface GeraeteInfo {
	protokoll: number;
	hardware_id: string;
	hardware: string;
	firmware: string;
	eingerichtet: boolean;
	instanz: string | null;
}

export type Schritt = 'netz' | 'einloesen';

export type FehlerArt =
	| 'ungueltig'
	| 'kein_netz'
	| 'tls'
	| 'code_abgelehnt'
	| 'keine_lizenz'
	| 'unbekannt'
	| 'zeitablauf'
	| 'verbindung'
	| 'protokoll'
	/** Ein Fehlername, den dieses Frontend nicht kennt (neuere Firmware). Gezeigt wird der Text des Geräts. */
	| 'geraet';

export class UsbFehler extends Error {
	constructor(
		readonly art: FehlerArt,
		readonly detail = ''
	) {
		super(art === 'geraet' && detail ? `Das Gerät meldet: ${detail}` : FEHLERTEXT[art] + (detail ? ` (${detail})` : ''));
	}
}

export const FEHLERTEXT: Record<FehlerArt, string> = {
	ungueltig: 'Das Gerät hat die Angaben abgelehnt.',
	kein_netz:
		'Der Tracker erreicht diese Instanz nicht. Hat er Mobilfunkempfang, und ist die Adresse von außen erreichbar?',
	tls: 'Der Tracker kann das Zertifikat dieser Instanz nicht prüfen. Bei einer eigenen Zertifizierungsstelle deren Wurzelzertifikat unten mitgeben.',
	code_abgelehnt: 'Der Code wurde abgelehnt — abgelaufen oder schon benutzt. „Neu einrichten" erzeugt einen neuen.',
	keine_lizenz:
		'Diese Instanz hat keine gültige Lizenz, deshalb lässt sie keine neuen Tracker zu. Lizenz im Superadmin eintragen, der Code bleibt gültig.',
	unbekannt: 'Das Gerät kennt diesen Befehl nicht. Ist die Firmware zu alt?',
	zeitablauf: 'Das Gerät antwortet nicht.',
	verbindung: 'Die Verbindung zum Gerät ist abgebrochen.',
	protokoll: 'Das Gerät spricht ein anderes Protokoll. Ist es ein ConvoyPlan-Tracker?',
	geraet: 'Das Gerät meldet einen Fehler.'
};

export const SCHRITTTEXT: Record<Schritt, string> = {
	netz: 'Tracker verbindet sich mit dem Mobilfunknetz …',
	einloesen: 'Tracker meldet sich bei dieser Instanz …'
};

export function webSerialVerfuegbar(nav: Navigator = navigator): boolean {
	return 'serial' in nav && !!(nav as unknown as { serial?: SerialLike }).serial;
}

/** Zerlegt eingefügten Text in einzelne PEM-Zertifikate. Alles andere fällt weg. */
export function wurzelnLesen(text: string): string[] {
	return (text.match(/-----BEGIN CERTIFICATE-----[\s\S]*?-----END CERTIFICATE-----/g) ?? []).map((w) => w.trim());
}

/**
 * Die Adresse, unter der Geräte diese Instanz erreichen. Ohne Pfad, wie das Protokoll es
 * verlangt — der Org-Admin liegt unter `/o/<slug>/…`, die Geräte-API unter `/api/geraete/`.
 */
export function instanzAdresse(loc: Pick<Location, 'origin'> = location): string {
	return loc.origin;
}

export class TrackerUsb {
	private puffer = '';
	private leser: ReadableStreamDefaultReader<Uint8Array> | null = null;
	private dekodierer = new TextDecoder();

	private constructor(private anschluss: SeriellerAnschluss) {}

	/** Lässt den Benutzer das Gerät wählen und öffnet es. Muss aus einem Klick heraus kommen. */
	static async waehlen(nav: Navigator = navigator): Promise<TrackerUsb> {
		const serial = (nav as unknown as { serial: SerialLike }).serial;
		const anschluss = await serial.requestPort();
		await anschluss.open({ baudRate: 115200 });
		return new TrackerUsb(anschluss);
	}

	async info(): Promise<GeraeteInfo> {
		const a = await this.anfrage({ befehl: 'info' }, INFO_MS);
		if (a.protokoll !== PROTOKOLL || typeof a.hardware_id !== 'string') throw new UsbFehler('protokoll');
		return a as unknown as GeraeteInfo;
	}

	async einrichten(
		instanz: string,
		code: string,
		wurzeln: string[],
		beiSchritt: (s: Schritt) => void = () => {}
	): Promise<{ geraet_id: string }> {
		const anfrage: Record<string, unknown> = { befehl: 'einrichten', instanz, code };
		if (wurzeln.length) anfrage.wurzeln = wurzeln;
		const a = await this.anfrage(anfrage, EINRICHTEN_MS, beiSchritt);
		return { geraet_id: String(a.geraet_id ?? '') };
	}

	async schliessen(): Promise<void> {
		try {
			await this.leser?.cancel();
			this.leser?.releaseLock();
		} catch {
			// schon zu
		}
		this.leser = null;
		try {
			await this.anschluss.close();
		} catch {
			// schon zu
		}
	}

	/** Schickt eine Zeile und liest bis zur Schlusszeile mit `ok`. */
	private async anfrage(
		anfrage: Record<string, unknown>,
		zeitlimitMs: number,
		beiSchritt: (s: Schritt) => void = () => {}
	): Promise<Record<string, unknown>> {
		await this.schreiben(JSON.stringify(anfrage) + '\n');
		const ende = Date.now() + zeitlimitMs;
		for (;;) {
			const zeile = await this.zeileLesen(ende);
			let antwort: unknown;
			try {
				antwort = JSON.parse(zeile);
			} catch {
				continue; // Startmeldungen der Firmware o. Ä.
			}
			if (!antwort || typeof antwort !== 'object') continue;
			const a = antwort as Record<string, unknown>;
			if (typeof a.schritt === 'string' && !('ok' in a)) {
				if (a.schritt in SCHRITTTEXT) beiSchritt(a.schritt as Schritt);
				continue;
			}
			if (a.ok === true) return a;
			if (a.ok === false) {
				const text = typeof a.text === 'string' ? a.text : '';
				if (typeof a.fehler !== 'string') throw new UsbFehler('protokoll', text);
				// Neuere Firmware kann Fehler melden, die dieses Frontend noch nicht kennt
				// (so kam `keine_lizenz` dazu). Das ist kein Protokollfehler: der Text des
				// Geräts sagt, was los ist.
				if (!Object.hasOwn(FEHLERTEXT, a.fehler) || a.fehler === 'geraet') throw new UsbFehler('geraet', text || a.fehler);
				throw new UsbFehler(a.fehler as FehlerArt, text);
			}
		}
	}

	private async schreiben(text: string): Promise<void> {
		const w = this.anschluss.writable?.getWriter();
		if (!w) throw new UsbFehler('verbindung');
		try {
			await w.write(new TextEncoder().encode(text));
		} finally {
			w.releaseLock();
		}
	}

	private async zeileLesen(ende: number): Promise<string> {
		for (;;) {
			const umbruch = this.puffer.indexOf('\n');
			if (umbruch >= 0) {
				const zeile = this.puffer.slice(0, umbruch).replace(/\r$/, '');
				this.puffer = this.puffer.slice(umbruch + 1);
				if (zeile.trim()) return zeile;
				continue;
			}
			const restMs = ende - Date.now();
			if (restMs <= 0) throw new UsbFehler('zeitablauf');
			if (!this.leser) {
				if (!this.anschluss.readable) throw new UsbFehler('verbindung');
				this.leser = this.anschluss.readable.getReader();
			}
			let uhr: ReturnType<typeof setTimeout> | undefined;
			const zeit = new Promise<'zeit'>((r) => (uhr = setTimeout(() => r('zeit'), restMs)));
			const ergebnis = await Promise.race([this.leser.read(), zeit]).finally(() => clearTimeout(uhr));
			if (ergebnis === 'zeit') throw new UsbFehler('zeitablauf');
			if (ergebnis.done) throw new UsbFehler('verbindung');
			this.puffer += this.dekodierer.decode(ergebnis.value, { stream: true });
		}
	}
}
