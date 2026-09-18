// Zustand eines Live-Kanals — und die Frage, ab wann „Getrennt" dasteht.
//
// Die Anzeige hatte bisher zwei Zustände: verbunden oder getrennt. Damit steht
// „Getrennt" auch dann da, wenn die Verbindung gerade erst aufgebaut wird oder
// nach einem Funkloch in Sekunden wieder steht — also genau in den Momenten, in
// denen sie nichts aussagt. Ein Rot, das jede Sekunde lügt, liest im Einsatz
// niemand mehr.
//
// Deshalb drei Aussagen statt zwei: sie steht (`open`), sie wird gerade
// aufgebaut (`connecting`/`reconnecting`), sie ist weg (`offline`). Vom Aufbau
// zum Weg führt eine Frist, kein Ereignis — erst wenn die Wiederverbindung
// `DOWN_GRACE_MS` lang nicht klappt, ist das eine Störung, die der Fahrer sehen
// muss. Die Begleit-App macht es genauso (`packages/track-api/src/socket.ts`),
// und die Begriffe bleiben absichtlich dieselben.

export type ConnectionState =
	/** Kein Kanal gewünscht (noch nicht verbunden oder bewusst beendet). */
	| 'idle'
	/** Erster Verbindungsversuch läuft. */
	| 'connecting'
	/** Kanal steht. */
	| 'open'
	/** Kanal steht, aber seit einer Weile still — kein Fehler, nur nichts los. */
	| 'stale'
	/** Kanal war schon da, ist weg, ein neuer Versuch läuft. */
	| 'reconnecting'
	/** Versuche laufen weiter, aber lange genug erfolglos, um es zu sagen. */
	| 'offline';

/** So lange gilt eine unterbrochene Verbindung noch als „im Aufbau". */
export const DOWN_GRACE_MS = 12_000;

export interface ConnectionLook {
	label: string;
	title: string;
	/** Farbklasse der Anzeige. */
	tone: 'live' | 'pending' | 'down';
}

export function connectionLook(state: ConnectionState): ConnectionLook {
	switch (state) {
		case 'open':
			return { label: 'Live', title: 'Verbunden', tone: 'live' };
		case 'stale':
			// Ein stehender Konvoi meldet minutenlang nichts. Das ist kein
			// Verbindungsfehler und darf nicht als „getrennt" erscheinen.
			return { label: 'Still', title: 'Verbindung steht, seit einer Weile keine Meldung', tone: 'pending' };
		case 'connecting':
			return { label: 'Verbindet…', title: 'Verbindung wird aufgebaut', tone: 'pending' };
		case 'reconnecting':
			return { label: 'Verbindet…', title: 'Verbindung unterbrochen – neuer Versuch läuft', tone: 'pending' };
		case 'offline':
			return { label: 'Getrennt', title: 'Keine Verbindung zum Server', tone: 'down' };
		default:
			return { label: 'Getrennt', title: 'Nicht verbunden', tone: 'down' };
	}
}

export interface ConnectionTracker {
	readonly state: ConnectionState;
	/** Ein Verbindungsversuch läuft (oder ist gerade gescheitert und wird wiederholt). */
	connecting(): void;
	/** Der Kanal steht. */
	open(): void;
	/** Der Kanal steht, meldet aber nichts mehr. */
	stale(): void;
	/** Kein Kanal mehr gewünscht. */
	idle(): void;
	dispose(): void;
}

/**
 * Hält den Zustand eines Live-Kanals und die Frist bis „Getrennt".
 *
 * Die Frist läuft **durchgehend**, nicht je Versuch: sonst setzte jeder
 * Reconnect-Tick sie zurück und „Getrennt" erschiene nie. Sie endet erst, wenn
 * der Kanal wieder steht.
 */
export function createConnectionTracker(
	onChange: (state: ConnectionState) => void,
	downGraceMs: number = DOWN_GRACE_MS
): ConnectionTracker {
	let state: ConnectionState = 'idle';
	let everOpen = false;
	let timer: ReturnType<typeof setTimeout> | null = null;

	function set(next: ConnectionState) {
		if (next === state) return;
		state = next;
		onChange(next);
	}

	function clearTimer() {
		if (timer) { clearTimeout(timer); timer = null; }
	}

	return {
		get state() { return state; },
		connecting() {
			// Einmal „Getrennt" bleibt „Getrennt", bis der Kanal wieder steht —
			// sonst flackert die Anzeige im Sekundentakt der Versuche.
			if (state === 'offline') return;
			set(everOpen ? 'reconnecting' : 'connecting');
			if (!timer) {
				timer = setTimeout(() => { timer = null; set('offline'); }, downGraceMs);
			}
		},
		open() {
			everOpen = true;
			clearTimer();
			set('open');
		},
		stale() {
			if (state === 'open') set('stale');
		},
		idle() {
			everOpen = false;
			clearTimer();
			set('idle');
		},
		dispose() {
			clearTimer();
		},
	};
}
