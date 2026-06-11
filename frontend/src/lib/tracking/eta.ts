// Live schedule / delay estimation for the Zeitplan tab.
//
// The convoy's progress is derived by projecting the leading vehicle's live
// position onto the planned route polyline. Comparing the time the convoy
// *should* have needed to reach that point (a fraction of the total planned
// driving time) with the time actually elapsed since start yields a delay
// estimate that is then applied to every upcoming waypoint.

import type { Geometry } from 'geojson';

export interface LatLon {
	lat: number;
	lon: number;
}

/** Haversine distance in meters. */
export function haversine(a: LatLon, b: LatLon): number {
	const R = 6371000;
	const dLat = ((b.lat - a.lat) * Math.PI) / 180;
	const dLon = ((b.lon - a.lon) * Math.PI) / 180;
	const lat1 = (a.lat * Math.PI) / 180;
	const lat2 = (b.lat * Math.PI) / 180;
	const h =
		Math.sin(dLat / 2) ** 2 + Math.cos(lat1) * Math.cos(lat2) * Math.sin(dLon / 2) ** 2;
	return 2 * R * Math.asin(Math.min(1, Math.sqrt(h)));
}

/** Flatten a route Geometry into an ordered list of [lon, lat] coordinates. */
export function routeCoords(geo: Geometry | null | undefined): number[][] {
	if (!geo) return [];
	if (geo.type === 'LineString') return geo.coordinates as number[][];
	if (geo.type === 'MultiLineString') return (geo.coordinates as number[][][]).flat();
	return [];
}

/** Cumulative along-route distance (m) at each coordinate index. */
function cumulativeDistances(coords: number[][]): number[] {
	const cum = [0];
	for (let i = 1; i < coords.length; i++) {
		const prev = { lon: coords[i - 1][0], lat: coords[i - 1][1] };
		const cur = { lon: coords[i][0], lat: coords[i][1] };
		cum.push(cum[i - 1] + haversine(prev, cur));
	}
	return cum;
}

/**
 * Project a point onto the route polyline and return how far along the route
 * (in meters) the nearest point lies. Returns null if the route is too short.
 */
export function distanceAlongRoute(coords: number[][], point: LatLon): number | null {
	if (coords.length < 2) return null;
	const cum = cumulativeDistances(coords);
	let best = { dist: Infinity, along: 0 };
	for (let i = 1; i < coords.length; i++) {
		const ax = coords[i - 1][0];
		const ay = coords[i - 1][1];
		const bx = coords[i][0];
		const by = coords[i][1];
		// Work in a local equirectangular projection (good enough at convoy scale).
		const latRef = (ay * Math.PI) / 180;
		const sx = Math.cos(latRef);
		const px = (point.lon - ax) * sx;
		const py = point.lat - ay;
		const vx = (bx - ax) * sx;
		const vy = by - ay;
		const segLen2 = vx * vx + vy * vy;
		const t = segLen2 > 0 ? Math.max(0, Math.min(1, (px * vx + py * vy) / segLen2)) : 0;
		const projLon = ax + ((bx - ax) * t);
		const projLat = ay + ((by - ay) * t);
		const d = haversine(point, { lon: projLon, lat: projLat });
		if (d < best.dist) {
			best = { dist: d, along: cum[i - 1] + (cum[i] - cum[i - 1]) * t };
		}
	}
	return best.along;
}

export interface DelayEstimate {
	/** Seconds behind schedule (positive) or ahead (negative). */
	delaySeconds: number;
	/** Along-route distance covered by the lead vehicle (m). */
	coveredM: number;
}

/**
 * Estimate the convoy's current schedule delay from the lead vehicle position.
 * Returns null when there is not enough data (no route, no start time…).
 */
export function estimateDelay(opts: {
	coords: number[][];
	totalDistanceM: number;
	totalDurationS: number;
	startTime: Date;
	leadPos: LatLon;
	now?: Date;
}): DelayEstimate | null {
	const { coords, totalDistanceM, totalDurationS, startTime, leadPos } = opts;
	if (coords.length < 2 || totalDistanceM <= 0 || totalDurationS <= 0) return null;
	const covered = distanceAlongRoute(coords, leadPos);
	if (covered == null) return null;
	const now = opts.now ?? new Date();
	const plannedForCovered = (covered / totalDistanceM) * totalDurationS;
	const actualElapsed = (now.getTime() - startTime.getTime()) / 1000;
	return { delaySeconds: actualElapsed - plannedForCovered, coveredM: covered };
}
