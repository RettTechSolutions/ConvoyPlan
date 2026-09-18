// Live-Kanal des öffentlichen Tracking-Links — mit Wiederverbindung.
//
// Der Kanal der Tracking-Seite hatte keine: ging er einmal verloren (Tunnel,
// Netzwechsel, Telefon im Standby, Leerlauf-Zeitlimit des Reverse-Proxy), stand
// „Getrennt" da, bis jemand die Seite neu lud. Für einen Fahrer, der das Gerät
// in der Halterung hat, heisst das: die Karte friert ein, und niemand sieht es.
//
// Zwei Eigenheiten des öffentlichen Endpunkts bestimmen den Bau:
//
// 1. Er beantwortet **kein** Ping/Pong (anders als `/api/ws/tracking/<id>` für
//    Angemeldete). Ein Ping wäre auf einem Fahrer-Link sogar schädlich: der
//    Server liest dort jeden Frame ohne `type: "status"` als Positionsmeldung.
//    Stille wird deshalb nur gemessen, nicht provoziert.
// 2. Stille ist der Normalfall. Ein stehender Konvoi meldet minutenlang nichts.
//    Darum zwei Stufen: erst `stale` („Still"), dann ein erzwungener Neuaufbau.
//
// Die Begleit-App macht es genauso (`packages/track-api/src/socket.ts` im Repo
// Convoyplan-Companion); die Zustandsnamen sind absichtlich dieselben.

import { createConnectionTracker, type ConnectionState } from './connection';

/** Schliesscodes, nach denen ein neuer Versuch sinnlos ist. */
export const CLOSE_REVOKED = 4404;
export const CLOSE_UNAUTHORIZED = 4001;

export interface LiveSocketOptions {
	/** Wird vor **jedem** Versuch neu ausgewertet, damit ein frisches Token greift. */
	url: () => string;
	onMessage: (data: unknown) => void;
	onState: (state: ConnectionState) => void;
	/** Endgültiges Scheitern (4404/4001). Danach passiert nichts mehr von allein. */
	onFatal?: (code: number) => void;
}

export interface LiveSocket {
	connect(): void;
	/** Sofort neu verbinden, ohne die Backoff-Wartezeit — Netz ist wieder da. */
	wake(): void;
	send(payload: unknown): boolean;
	canSend(): boolean;
	close(): void;
}

const BACKOFF_INITIAL_MS = 1000;
const BACKOFF_MAX_MS = 20000;
/** Ohne Meldung so lange → „Still". Kein Fehler, nur nichts los. */
const STALE_AFTER_MS = 90_000;
/** Ohne Meldung so lange → Zwangs-Neuaufbau; der Kanal ist vermutlich tot. */
const FORCE_RECONNECT_AFTER_MS = 180_000;

export function createLiveSocket(options: LiveSocketOptions): LiveSocket {
	let socket: WebSocket | null = null;
	let attempt = 0;
	let stopped = true;
	let generation = 0;
	let reconnectTimer: ReturnType<typeof setTimeout> | null = null;
	let staleTimer: ReturnType<typeof setTimeout> | null = null;
	let deadTimer: ReturnType<typeof setTimeout> | null = null;

	const tracker = createConnectionTracker(options.onState);

	function clearTimer(timer: ReturnType<typeof setTimeout> | null) {
		if (timer) clearTimeout(timer);
		return null;
	}

	function clearSilenceTimers() {
		staleTimer = clearTimer(staleTimer);
		deadTimer = clearTimer(deadTimer);
	}

	/** Nach jeder empfangenen Meldung neu stellen — sie ist der Lebensbeweis. */
	function armSilenceTimers() {
		clearSilenceTimers();
		staleTimer = setTimeout(() => tracker.stale(), STALE_AFTER_MS);
		deadTimer = setTimeout(() => {
			// Kein `close`-Ereignis, kein Fehler — nur Stille. Selbst abräumen.
			drop();
			scheduleReconnect();
		}, FORCE_RECONNECT_AFTER_MS);
	}

	function drop() {
		const previous = socket;
		socket = null;
		clearSilenceTimers();
		if (previous) {
			previous.onopen = previous.onmessage = previous.onerror = null;
			previous.onclose = null;
			try { previous.close(); } catch { /* egal */ }
		}
	}

	function scheduleReconnect() {
		if (stopped || reconnectTimer) return;
		tracker.connecting();
		const base = Math.min(BACKOFF_INITIAL_MS * 2 ** attempt, BACKOFF_MAX_MS);
		// Jitter, damit nicht der ganze Verband gleichzeitig wieder anklopft.
		const delay = base * (0.7 + Math.random() * 0.6);
		attempt += 1;
		reconnectTimer = setTimeout(() => {
			reconnectTimer = null;
			open();
		}, delay);
	}

	function open() {
		if (stopped) return;
		const myGen = ++generation;
		drop();
		tracker.connecting();

		let next: WebSocket;
		try {
			next = new WebSocket(options.url());
		} catch {
			scheduleReconnect();
			return;
		}
		socket = next;

		next.onopen = () => {
			if (myGen !== generation) return;
			attempt = 0;
			tracker.open();
			armSilenceTimers();
		};
		next.onmessage = (event) => {
			if (myGen !== generation) return;
			tracker.open();
			armSilenceTimers();
			try {
				options.onMessage(JSON.parse(event.data));
			} catch { /* kaputter Frame — der Kanal bleibt davon unberührt */ }
		};
		next.onerror = () => {
			if (myGen !== generation) return;
			tracker.connecting();
		};
		next.onclose = (event) => {
			if (myGen !== generation) return;
			clearSilenceTimers();
			socket = null;
			if (event.code === CLOSE_REVOKED || event.code === CLOSE_UNAUTHORIZED) {
				// Gegen eine Wand hilft kein zweiter Versuch: der Link ist weg oder
				// die Sitzung abgelaufen. Das muss die Seite entscheiden.
				stopped = true;
				tracker.idle();
				options.onFatal?.(event.code);
				return;
			}
			scheduleReconnect();
		};
	}

	return {
		connect() {
			stopped = false;
			attempt = 0;
			open();
		},
		wake() {
			if (stopped) return;
			if (socket?.readyState === WebSocket.OPEN) return;
			reconnectTimer = clearTimer(reconnectTimer);
			attempt = 0;
			open();
		},
		send(payload: unknown) {
			if (socket?.readyState !== WebSocket.OPEN) return false;
			try {
				socket.send(JSON.stringify(payload));
				return true;
			} catch {
				return false;
			}
		},
		canSend() {
			return socket?.readyState === WebSocket.OPEN;
		},
		close() {
			stopped = true;
			generation += 1;
			reconnectTimer = clearTimer(reconnectTimer);
			drop();
			tracker.idle();
			tracker.dispose();
		},
	};
}
