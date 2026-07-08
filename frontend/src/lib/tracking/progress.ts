// Convoy progress along the planned route: which waypoints and
// Leitstellen-Übergabepunkte lie ahead, which has the convoy reached, and
// which has the *whole* convoy (front to rear) already passed.
//
// All positions are projected onto the route polyline (see eta.ts). The
// convoy occupies the km interval [rear, front] of its live vehicles; a point
// counts as "reached" once the front crosses it and as "passed" once the rear
// has crossed it too.

import { distanceAlongRoute, type LatLon } from './eta';

export interface KanalwechselLike {
	km: number;
	leitstelle_name: string;
	anrufgruppe: string;
	typ?: 'anmelden' | 'abmelden' | 'convoy_anmeldung';
}

export interface WaypointLike {
	name: string;
	lat: number | null;
	lon: number | null;
}

export interface RoutePoint {
	id: string;
	kind: 'waypoint' | 'kanalwechsel';
	/** Along-route position in meters. */
	m: number;
	/** Short label, e.g. "Wegpunkt Rosenheim" or "Leitstellenwechsel → ILS FFB". */
	label: string;
	/** Optional secondary line, e.g. "Abmelden ILS München · Anmelden ILS FFB (20)". */
	detail: string | null;
}

/**
 * Merge waypoints and Kanalwechsel entries into a single ordered list of
 * along-route points. Kanalwechsel entries at the same km (Abmelden alt +
 * Anmelden neu) are combined into one handover point; the Convoy-Anmeldung at
 * km 0 is skipped — it happens before departure.
 */
export function buildRoutePoints(
	coords: number[][],
	kanalwechsel: KanalwechselLike[],
	waypoints: WaypointLike[]
): RoutePoint[] {
	const points: RoutePoint[] = [];

	waypoints.forEach((wp, i) => {
		if (wp.lat == null || wp.lon == null) return;
		const m = distanceAlongRoute(coords, { lat: wp.lat, lon: wp.lon });
		if (m == null) return;
		points.push({ id: `wp-${i}`, kind: 'waypoint', m, label: `Wegpunkt ${wp.name}`, detail: null });
	});

	// Group handover entries by km (rounded to 0,1 km — the backend emits
	// Abmelden/Anmelden of one handover at the identical km).
	const groups = new Map<number, KanalwechselLike[]>();
	for (const kw of kanalwechsel) {
		if (kw.typ === 'convoy_anmeldung') continue;
		const key = Math.round(kw.km * 10);
		const list = groups.get(key) ?? [];
		list.push(kw);
		groups.set(key, list);
	}
	for (const [key, entries] of groups) {
		const anmelden = entries.find((e) => e.typ !== 'abmelden');
		const abmelden = entries.find((e) => e.typ === 'abmelden');
		const label = anmelden
			? `Leitstellenwechsel → ${anmelden.leitstelle_name}`
			: `Abmelden bei ${abmelden!.leitstelle_name}`;
		const parts: string[] = [];
		if (abmelden) parts.push(`Abmelden ${abmelden.leitstelle_name}`);
		if (anmelden) parts.push(`Anmelden ${anmelden.leitstelle_name} (Gruppe ${anmelden.anrufgruppe})`);
		points.push({
			id: `kw-${key}`,
			kind: 'kanalwechsel',
			m: (key / 10) * 1000,
			label,
			detail: parts.join(' · ') || null,
		});
	}

	points.sort((a, b) => a.m - b.m);
	return points;
}

export interface ConvoyProgress {
	/** Along-route meters of the leading live vehicle. */
	frontM: number;
	/** Along-route meters of the trailing live vehicle. */
	rearM: number;
	/** Number of live vehicles considered. */
	count: number;
	/** Along-route meters of every live vehicle (for "n/x passiert"). */
	alongM: number[];
}

/** Project all live positions onto the route; null while nothing is live. */
export function computeConvoyProgress(coords: number[][], positions: LatLon[]): ConvoyProgress | null {
	if (coords.length < 2 || positions.length === 0) return null;
	const alongM: number[] = [];
	for (const p of positions) {
		const m = distanceAlongRoute(coords, p);
		if (m != null) alongM.push(m);
	}
	if (!alongM.length) return null;
	return { frontM: Math.max(...alongM), rearM: Math.min(...alongM), count: alongM.length, alongM };
}

/** Format a distance ahead of the convoy front, e.g. "2,4 km" or "350 m". */
export function formatDistance(m: number): string {
	if (m >= 950) return `${(m / 1000).toLocaleString('de-DE', { maximumFractionDigits: 1 })} km`;
	return `${Math.max(0, Math.round(m / 50) * 50)} m`;
}
