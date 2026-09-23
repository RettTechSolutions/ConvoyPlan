import { derived, writable } from 'svelte/store';
import type { VehiclePosition } from '$lib/api';
import { getStreamTicket } from '$lib/api/client';
import { createConnectionTracker, type ConnectionState } from '$lib/tracking/connection';
import type { Betriebsstoff } from '$lib/tracking/betriebsstoff';
import type { Staerke } from '$lib/tracking/staerke';
import { createBelegung, geraeteKennung } from '$lib/tracking/belegung';

/** Live status (incl. sub-level and note) received over the WebSocket. */
export interface VehicleStatusInfo {
	status: string;
	level: string | null;
	note: string | null;
}

/** An incoming technical-halt / breakdown alert from another vehicle. */
export interface TrackingAlert {
	id: string;
	alert_type: 'technical_halt' | 'breakdown';
	vehicle_id: string;
	vehicle_label: string | null;
	level: string | null;
	note: string | null;
	ts: string;
	acknowledged: boolean;
}

export const livePositions = writable<Map<string, VehiclePosition>>(new Map());
export const vehicleStatuses = writable<Map<string, VehicleStatusInfo>>(new Map());
/**
 * Live gemeldete Mannschaftsstärken je Fahrzeug.
 *
 * Nur *gemeldete* — ein Fahrzeug, das schweigt, steht hier nicht drin und
 * darf in der Anzeige nicht als 0 erscheinen (siehe `$lib/tracking/staerke`).
 */
export const vehicleStaerken = writable<Map<string, Staerke>>(new Map());
/** Live gemeldete Betriebsstofflage je Fahrzeug (`$lib/tracking/betriebsstoff`). */
export const vehicleBetriebsstoff = writable<Map<string, Betriebsstoff>>(new Map());
/** Rolling log of incoming TH / breakdown alerts (newest first). */
export const trackingAlerts = writable<TrackingAlert[]>([]);
/**
 * Zustand des Live-Kanals für die Anzeige.
 *
 * Feiner als „an/aus": ein laufender Verbindungsaufbau ist kein „Getrennt".
 * Siehe `$lib/tracking/connection`.
 */
export const trackingConnection = writable<ConnectionState>('idle');
/** Kanal steht wirklich. Grundlage für alles, was echte Zustellung voraussetzt. */
export const trackingActive = derived(trackingConnection, ($state) => $state === 'open');
/** Vehicle id whose GPS sharing was just reset by an admin (signal for the sender to stop). */
export const gpsRevoked = writable<string | null>(null);
/**
 * Fahrzeuge, die ein **anderes** Gerät gewählt hat (App, Fahrer-Link, zweiter
 * Tab). Sie lassen sich nicht wählen — siehe `$lib/tracking/belegung`.
 */
export const fremdBelegt = writable<ReadonlySet<string>>(new Set());
/** Das eigene Fahrzeug war schon vergeben; die Ansicht nimmt die Wahl zurück. */
export const belegungAbgelehnt = writable<string | null>(null);

const belegung = createBelegung({
	send: (frame) => {
		if (ws?.readyState !== WebSocket.OPEN) return false;
		try { ws.send(JSON.stringify(frame)); return true; } catch { return false; }
	},
	onChange: (fremd) => fremdBelegt.set(fremd),
	onAbgelehnt: (vehicleId) => belegungAbgelehnt.set(vehicleId),
});

/** Das eigene Fahrzeug wählen (`''` = keins). Belegt es für dieses Gerät. */
export function fahrzeugWaehlen(vehicleId: string) {
	belegung.waehlen(vehicleId);
}

const connection = createConnectionTracker((state) => trackingConnection.set(state));

let alertSeq = 0;

let ws: WebSocket | null = null;
let reconnectTimer: ReturnType<typeof setTimeout> | null = null;
let watchdogTimer: ReturnType<typeof setInterval> | null = null;
let heartbeatTimer: ReturnType<typeof setInterval> | null = null;
// Timestamp (ms) of the last frame received from the server. Drives the
// application-level heartbeat: on flaky mobile signal the TCP socket stays
// "OPEN" (half-open) for a long time, so neither a 'close' event nor
// readyState reveal the drop. By pinging the server every few seconds and
// expecting any reply, we detect the dead link within HEARTBEAT_TIMEOUT_MS
// instead of waiting minutes for the OS-level timeout — that is what makes the
// "Du bist offline" banner appear promptly.
let lastMessageAt = 0;
// Bumped on every (re)connect/disconnect so in-flight async connects and pending
// reconnect timers from a superseded connection can detect they are stale and
// bail out — prevents parallel sockets and runaway reconnect loops.
let connectionGen = 0;
// Non-null while we want to stay connected (i.e. between connect/disconnect).
// Drives the auto-reconnect, the online-event recovery and the watchdog.
let desiredConvoyId: string | null = null;
let onlineHandlerAttached = false;

// Retry every few seconds while disconnected; a background watchdog re-checks
// the socket independently so we recover even when no 'close' event ever fires
// (half-open sockets on flaky mobile networks). A connect attempt that can't
// reach the backend (e.g. no ticket while offline) reschedules instead of
// giving up — the previous behaviour silently killed the reconnect loop, so the
// app stayed "offline" forever once signal returned.
const RECONNECT_DELAY_MS = 3000;
const WATCHDOG_INTERVAL_MS = 5000;
const OPEN_TIMEOUT_MS = 10000;
// Heartbeat: ping this often, and consider the link dead when no frame at all
// (position echo, status, or pong) has arrived within the timeout.
const HEARTBEAT_INTERVAL_MS = 3000;
const HEARTBEAT_TIMEOUT_MS = 7000;

export async function connectTracking(convoyId: string) {
	// Fresh, user-initiated connect → drop any alerts carried over from a
	// previous convoy. Auto-reconnects go through openSocket() and keep them.
	trackingAlerts.set([]);
	desiredConvoyId = convoyId;
	connection.connecting();
	ensureOnlineHandler();
	ensureWatchdog();
	ensureHeartbeat();
	await openSocket(convoyId);
}

async function openSocket(convoyId: string) {
	const myGen = ++connectionGen;

	// Tear down any existing connection/timer first.
	if (reconnectTimer) { clearTimeout(reconnectTimer); reconnectTimer = null; }
	if (ws) {
		const previous = ws;
		ws = null;
		previous.onclose = null;
		previous.close();
	}

	// SSE/WebSocket cannot send an Authorization header, so use a short-lived
	// stream ticket in the URL instead of the long-lived access token.
	let ticket: string | null = null;
	try { ticket = await getStreamTicket(); } catch { ticket = null; }
	if (myGen !== connectionGen || desiredConvoyId !== convoyId) return; // superseded
	if (!ticket) { connection.connecting(); scheduleReconnect(convoyId); return; }

	// WebSocket connects through the same origin (e.g. via Caddy reverse-proxy).
	// For local dev without Caddy set VITE_WS_HOST=localhost:8000 in .env.local.
	const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
	const backendHost = import.meta.env.VITE_WS_HOST ?? window.location.host;
	const socket = new WebSocket(
		`${protocol}//${backendHost}/api/ws/tracking/${convoyId}` +
			`?token=${encodeURIComponent(ticket)}&client=${encodeURIComponent(geraeteKennung())}`
	);
	ws = socket;

	// Guard against a socket that connects but never opens (half-open on a flaky
	// network): force it closed after a timeout so the reconnect path kicks in.
	const openTimer = setTimeout(() => {
		if (myGen !== connectionGen) return;
		if (socket.readyState !== WebSocket.OPEN) {
			socket.onclose = null;
			try { socket.close(); } catch { /* ignore */ }
			if (ws === socket) ws = null;
			connection.connecting();
			scheduleReconnect(convoyId);
		}
	}, OPEN_TIMEOUT_MS);

	socket.onmessage = (event) => {
		// Any frame proves the link is alive → feed the heartbeat.
		lastMessageAt = Date.now();
		const parsed = JSON.parse(event.data);
		if (belegung.handle(parsed)) return;
		const data = parsed as VehiclePosition & {
			type?: string;
			vehicle_status?: string;
			status_level?: string | null;
			status_note?: string | null;
			alert_type?: 'technical_halt' | 'breakdown';
			vehicle_label?: string | null;
			level?: string | null;
			note?: string | null;
			ts?: string;
			fuehrer?: number;
			unterfuehrer?: number;
			mannschaften?: number;
			verbrauch?: number | null;
			tank?: number | null;
			fuellstand?: number | null;
		};
		if (data.type === 'pong') {
			// Heartbeat reply — the timestamp above is all we need.
			return;
		} else if (data.type === 'status_update') {
			vehicleStatuses.update((m) => {
				m.set(data.vehicle_id, {
					status: data.vehicle_status!,
					level: data.status_level ?? null,
					note: data.status_note ?? null,
				});
				return new Map(m);
			});
		} else if (data.type === 'staerke_update') {
			if (
				typeof data.fuehrer === 'number' && typeof data.unterfuehrer === 'number' &&
				typeof data.mannschaften === 'number'
			) {
				vehicleStaerken.update((m) => {
					m.set(data.vehicle_id, {
						fuehrer: data.fuehrer!, unterfuehrer: data.unterfuehrer!, mannschaften: data.mannschaften!,
					});
					return new Map(m);
				});
			}
		} else if (data.type === 'betriebsstoff_update') {
			// Die Meldung ersetzt die vorige ganz — ein fehlendes Feld heißt
			// „nicht bekannt", nicht „wie vorher" (`_ingest_driver_betriebsstoff`).
			vehicleBetriebsstoff.update((m) => {
				m.set(data.vehicle_id, {
					verbrauch: typeof data.verbrauch === 'number' ? data.verbrauch : null,
					tank: typeof data.tank === 'number' ? data.tank : null,
					fuellstand: typeof data.fuellstand === 'number' ? data.fuellstand : null,
				});
				return new Map(m);
			});
		} else if (data.type === 'alert') {
			trackingAlerts.update((list) => [
				{
					id: `a${++alertSeq}`,
					alert_type: data.alert_type!,
					vehicle_id: data.vehicle_id,
					vehicle_label: data.vehicle_label ?? null,
					level: data.level ?? null,
					note: data.note ?? null,
					ts: data.ts ?? new Date().toISOString(),
					acknowledged: false,
				},
				...list,
			].slice(0, 50));
		} else if (data.type === 'position_cleared') {
			livePositions.update((m) => {
				m.delete(data.vehicle_id);
				return new Map(m);
			});
			gpsRevoked.set(data.vehicle_id);
		} else {
			livePositions.update((m) => {
				m.set(data.vehicle_id, data);
				return new Map(m);
			});
		}
	};

	socket.onopen = () => { clearTimeout(openTimer); lastMessageAt = Date.now(); connection.open(); };
	// Ein Fehler eines längst ersetzten oder bewusst geschlossenen Sockets darf
	// die Anzeige nicht mehr anfassen — sonst stünde nach `disconnectTracking`
	// wieder „Verbindet…" da.
	socket.onerror = () => {
		if (myGen !== connectionGen || ws !== socket) return;
		connection.connecting();
	};
	socket.onclose = () => {
		clearTimeout(openTimer);
		// Ignore close events from a socket that has been replaced or from a
		// connection that was intentionally torn down (disconnect/reconnect).
		if (myGen !== connectionGen || ws !== socket) return;
		connection.connecting();
		scheduleReconnect(convoyId);
	};
}

// Schedule the next reconnect attempt (deduplicated). Keeps retrying as long as
// a connection is still desired — recovers once the network returns.
function scheduleReconnect(convoyId: string) {
	if (desiredConvoyId !== convoyId) return;
	if (reconnectTimer) return; // already scheduled
	reconnectTimer = setTimeout(() => {
		reconnectTimer = null;
		openSocket(convoyId);
	}, RECONNECT_DELAY_MS);
}

// Background watchdog: independently of socket events, periodically verify the
// connection is alive and kick a reconnect if it is dead and none is pending.
function ensureWatchdog() {
	if (watchdogTimer) return;
	watchdogTimer = setInterval(() => {
		if (!desiredConvoyId) return;
		const state = ws?.readyState;
		const alive = state === WebSocket.OPEN || state === WebSocket.CONNECTING;
		if (!alive && !reconnectTimer) openSocket(desiredConvoyId);
	}, WATCHDOG_INTERVAL_MS);
}

// Application-level heartbeat. Sends a ping on the open socket and, more
// importantly, declares the link dead when no frame has been received within
// HEARTBEAT_TIMEOUT_MS — the only reliable way to notice a silently dropped
// mobile connection quickly (readyState stays OPEN on a half-open socket).
function ensureHeartbeat() {
	if (heartbeatTimer) return;
	heartbeatTimer = setInterval(() => {
		if (!desiredConvoyId) return;
		const socket = ws;
		if (socket && socket.readyState === WebSocket.OPEN) {
			try { socket.send(JSON.stringify({ type: 'ping' })); } catch { /* ignore */ }
			// No reply within the timeout → treat as offline and force a reconnect.
			if (lastMessageAt && Date.now() - lastMessageAt > HEARTBEAT_TIMEOUT_MS) {
				connection.connecting();
				const convoyId = desiredConvoyId;
				socket.onclose = null;
				try { socket.close(); } catch { /* ignore */ }
				if (ws === socket) ws = null;
				scheduleReconnect(convoyId);
			}
		}
	}, HEARTBEAT_INTERVAL_MS);
}

// Reconnect immediately when the OS reports connectivity is back, rather than
// waiting for the next timer tick.
function ensureOnlineHandler() {
	if (onlineHandlerAttached || typeof window === 'undefined') return;
	window.addEventListener('online', handleOnline);
	onlineHandlerAttached = true;
}

function handleOnline() {
	if (!desiredConvoyId) return;
	if (reconnectTimer) { clearTimeout(reconnectTimer); reconnectTimer = null; }
	openSocket(desiredConvoyId);
}

export function disconnectTracking() {
	// Freigeben, solange der Kanal noch steht — danach ginge der Frame ins Leere.
	belegung.stop();
	fremdBelegt.set(new Set());
	connectionGen++; // invalidate any in-flight connect and pending reconnect
	desiredConvoyId = null;
	if (reconnectTimer) { clearTimeout(reconnectTimer); reconnectTimer = null; }
	if (watchdogTimer) { clearInterval(watchdogTimer); watchdogTimer = null; }
	if (heartbeatTimer) { clearInterval(heartbeatTimer); heartbeatTimer = null; }
	if (onlineHandlerAttached && typeof window !== 'undefined') {
		window.removeEventListener('online', handleOnline);
		onlineHandlerAttached = false;
	}
	const _ws = ws;
	ws = null; // clear first so reconnect logic doesn't fire
	if (_ws) { _ws.onclose = null; _ws.onerror = null; _ws.close(); }
	connection.idle();
	livePositions.set(new Map());
}

export function sendPosition(convoyId: string, vehicleId: string, lat: number, lon: number, speedKmh?: number, heading?: number) {
	if (ws?.readyState === WebSocket.OPEN) {
		ws.send(JSON.stringify({ vehicle_id: vehicleId, lat, lon, speed_kmh: speedKmh, heading }));
	}
}

/** Mark a single alert as acknowledged (removes the banner highlight). */
export function acknowledgeAlert(id: string) {
	trackingAlerts.update((list) => list.map((a) => (a.id === id ? { ...a, acknowledged: true } : a)));
}

/** Clear an alert from the log entirely. */
export function dismissAlert(id: string) {
	trackingAlerts.update((list) => list.filter((a) => a.id !== id));
}

/** Acknowledge every currently active alert. */
export function acknowledgeAllAlerts() {
	trackingAlerts.update((list) => list.map((a) => ({ ...a, acknowledged: true })));
}
