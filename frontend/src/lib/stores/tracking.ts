import { writable } from 'svelte/store';
import type { VehiclePosition } from '$lib/api';

export const livePositions = writable<Map<string, VehiclePosition>>(new Map());
export const vehicleStatuses = writable<Map<string, string>>(new Map());
export const trackingActive = writable(false);

let ws: WebSocket | null = null;

export function connectTracking(convoyId: string) {
	const token = localStorage.getItem('token');
	if (!token) return;

	// WebSocket connects through the same origin (e.g. via Caddy reverse-proxy).
	// For local dev without Caddy set VITE_WS_HOST=localhost:8000 in .env.local.
	const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
	const backendHost = import.meta.env.VITE_WS_HOST ?? window.location.host;
	ws = new WebSocket(`${protocol}//${backendHost}/api/ws/tracking/${convoyId}?token=${token}`);

	ws.onmessage = (event) => {
		const data = JSON.parse(event.data) as VehiclePosition & { type?: string; vehicle_status?: string };
		if (data.type === 'status_update') {
			vehicleStatuses.update((m) => {
				m.set(data.vehicle_id, data.vehicle_status!);
				return new Map(m);
			});
		} else {
			livePositions.update((m) => {
				m.set(data.vehicle_id, data);
				return new Map(m);
			});
		}
	};

	ws.onopen = () => trackingActive.set(true);
	ws.onerror = () => trackingActive.set(false);
	ws.onclose = () => {
		trackingActive.set(false);
		// Auto-reconnect after 3 s unless disconnected intentionally
		if (ws) setTimeout(() => connectTracking(convoyId), 3000);
	};
}

export function disconnectTracking() {
	const _ws = ws;
	ws = null; // clear first so reconnect logic doesn't fire
	_ws?.close();
	trackingActive.set(false);
	livePositions.set(new Map());
}

export function sendPosition(convoyId: string, vehicleId: string, lat: number, lon: number, speedKmh?: number, heading?: number) {
	if (ws?.readyState === WebSocket.OPEN) {
		ws.send(JSON.stringify({ vehicle_id: vehicleId, lat, lon, speed_kmh: speedKmh, heading }));
	}
}
