// Positionsquelle: sendet ein Tracker, gehört ihm die Position.
//
// Die Belegung (`./belegung`) sagt, welches Gerät der Besatzung ein Fahrzeug
// hält — Status, Stärke, Betriebsstoff, Quittung. Ein festes Ortungsgerät im
// Fahrzeug nimmt ihr davon nichts weg, nur die Position: Positionsframes vom
// Telefon verwirft der Server (`backend/app/services/positionsquelle.py`) und
// sagt es **nur dem Absender**. Diese Datei ist die Gegenstelle im Browser; die
// Begleit-App spricht dasselbe Protokoll.
//
// Vom Server (nur an Verbindungen mit `?client=<kennung>`):
//   { type: 'position_abgelehnt', vehicle_id, grund: 'tracker' }   nur an den Absender
//   { type: 'positionsquelle', vehicle_id, tracker_uebersteuert }   die Führung hat umgestellt
// In jeder Position: `quelle: 'tracker'`, wenn sie vom Gerät kam.

export const TRACKER_HINWEIS =
	'Die Position kommt vom Fahrzeugtracker. Status und Meldungen gehen weiter von hier.';

export interface PositionAbgelehnt {
	type: 'position_abgelehnt';
	vehicle_id: string;
	grund: string;
}

export interface PositionsquelleGeaendert {
	type: 'positionsquelle';
	vehicle_id: string;
	tracker_uebersteuert: boolean;
}

export function istPositionAbgelehnt(msg: unknown): msg is PositionAbgelehnt {
	const m = msg as { type?: unknown; vehicle_id?: unknown } | null;
	return !!m && m.type === 'position_abgelehnt' && typeof m.vehicle_id === 'string';
}

export function istPositionsquelle(msg: unknown): msg is PositionsquelleGeaendert {
	const m = msg as { type?: unknown; vehicle_id?: unknown; tracker_uebersteuert?: unknown } | null;
	return !!m && m.type === 'positionsquelle' && typeof m.vehicle_id === 'string' &&
		typeof m.tracker_uebersteuert === 'boolean';
}

/**
 * So lange nach seinem letzten Punkt hat der Tracker Vorrang — dieselbe Frist
 * wie `VORRANG_S` im Backend. Danach gilt wieder das Telefon.
 */
export const VORRANG_MS = 300_000;

/**
 * Hält der Tracker gerade die Position dieses Fahrzeugs? Dann bietet die
 * Ansicht „GPS senden" gar nicht erst an: Der Server verwürfe jeden Punkt, und
 * der eigene Marker überdeckte lokal den des Trackers.
 *
 * Gemessen am letzten Punkt mit `quelle: 'tracker'` — ohne Zeitstempel gilt er
 * als gerade eben empfangen. Hat die Führung übersteuert, gilt das Telefon.
 */
export function trackerHaeltPosition(
	pos: { quelle?: 'tracker' | null; recorded_at?: string } | undefined,
	uebersteuert: boolean,
	jetzt: number,
): boolean {
	if (uebersteuert || pos?.quelle !== 'tracker') return false;
	const t = pos.recorded_at ? Date.parse(pos.recorded_at) : NaN;
	return !Number.isFinite(t) || jetzt - t <= VORRANG_MS;
}
