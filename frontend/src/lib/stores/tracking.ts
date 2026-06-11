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
// Bumped on every connect/disconnect so in-flight async connects and pending
// reconnect timers from a superseded connection can detect they are stale and
// bail out — prevents parallel sockets and runaway reconnect loops.
let connectionGen = 0;

export async function connectTracking(convoyId: string) {
	const myGen = ++connectionGen;
	// Fresh session → drop any alerts carried over from a previous convoy.
	trackingAlerts.set([]);

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
	const ticket = await getStreamTicket();
	if (myGen !== connectionGen) return; // superseded while awaiting the ticket
	if (!ticket) return;

	// WebSocket connects through the same origin (e.g. via Caddy reverse-proxy).
	// For local dev without Caddy set VITE_WS_HOST=localhost:8000 in .env.local.
	const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
	const backendHost = import.meta.env.VITE_WS_HOST ?? window.location.host;
	const socket = new WebSocket(
		`${protocol}//${backendHost}/api/ws/tracking/${convoyId}?token=${encodeURIComponent(ticket)}`
	);
	ws = socket;

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

	socket.onopen = () => trackingActive.set(true);
	socket.onerror = () => trackingActive.set(false);
	socket.onclose = () => {
		// Ignore close events from a socket that has been replaced or from a
		// connection that was intentionally torn down (disconnect/reconnect).
		if (myGen !== connectionGen || ws !== socket) return;
		trackingActive.set(false);
		reconnectTimer = setTimeout(() => connectTracking(convoyId), 3000);
	};
}

export function disconnectTracking() {
	connectionGen++; // invalidate any in-flight connect and pending reconnect
	if (reconnectTimer) { clearTimeout(reconnectTimer); reconnectTimer = null; }
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
