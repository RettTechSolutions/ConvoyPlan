import { writable } from 'svelte/store';
import type { VehiclePosition } from '$lib/api';
import { getStreamTicket } from '$lib/api/client';

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
/** Rolling log of incoming TH / breakdown alerts (newest first). */
export const trackingAlerts = writable<TrackingAlert[]>([]);
export const trackingActive = writable(false);
/** Vehicle id whose GPS sharing was just reset by an admin (signal for the sender to stop). */
export const gpsRevoked = writable<string | null>(null);

let alertSeq = 0;

let ws: WebSocket | null = null;
let reconnectTimer: ReturnType<typeof setTimeout> | null = null;
let watchdogTimer: ReturnType<typeof setInterval> | null = null;
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

export async function connectTracking(convoyId: string) {
	// Fresh, user-initiated connect → drop any alerts carried over from a
	// previous convoy. Auto-reconnects go through openSocket() and keep them.
	trackingAlerts.set([]);
	desiredConvoyId = convoyId;
	ensureOnlineHandler();
	ensureWatchdog();
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
	if (!ticket) { trackingActive.set(false); scheduleReconnect(convoyId); return; }

	// WebSocket connects through the same origin (e.g. via Caddy reverse-proxy).
	// For local dev without Caddy set VITE_WS_HOST=localhost:8000 in .env.local.
	const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
	const backendHost = import.meta.env.VITE_WS_HOST ?? window.location.host;
	const socket = new WebSocket(
		`${protocol}//${backendHost}/api/ws/tracking/${convoyId}?token=${encodeURIComponent(ticket)}`
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
			trackingActive.set(false);
			scheduleReconnect(convoyId);
		}
	}, OPEN_TIMEOUT_MS);

	socket.onmessage = (event) => {
		const data = JSON.parse(event.data) as VehiclePosition & {
			type?: string;
			vehicle_status?: string;
			status_level?: string | null;
			status_note?: string | null;
			alert_type?: 'technical_halt' | 'breakdown';
			vehicle_label?: string | null;
			level?: string | null;
			note?: string | null;
			ts?: string;
		};
		if (data.type === 'status_update') {
			vehicleStatuses.update((m) => {
				m.set(data.vehicle_id, {
					status: data.vehicle_status!,
					level: data.status_level ?? null,
					note: data.status_note ?? null,
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

	socket.onopen = () => { clearTimeout(openTimer); trackingActive.set(true); };
	socket.onerror = () => trackingActive.set(false);
	socket.onclose = () => {
		clearTimeout(openTimer);
		// Ignore close events from a socket that has been replaced or from a
		// connection that was intentionally torn down (disconnect/reconnect).
		if (myGen !== connectionGen || ws !== socket) return;
		trackingActive.set(false);
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
	connectionGen++; // invalidate any in-flight connect and pending reconnect
	desiredConvoyId = null;
	if (reconnectTimer) { clearTimeout(reconnectTimer); reconnectTimer = null; }
	if (watchdogTimer) { clearInterval(watchdogTimer); watchdogTimer = null; }
	if (onlineHandlerAttached && typeof window !== 'undefined') {
		window.removeEventListener('online', handleOnline);
		onlineHandlerAttached = false;
	}
	const _ws = ws;
	ws = null; // clear first so reconnect logic doesn't fire
	if (_ws) { _ws.onclose = null; _ws.close(); }
	trackingActive.set(false);
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
