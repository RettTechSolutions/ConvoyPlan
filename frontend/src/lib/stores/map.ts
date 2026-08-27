import { writable } from 'svelte/store';

export type MapMode = 'idle' | 'set-start' | 'set-end' | 'add-waypoint';

export const mapMode = writable<MapMode>('idle');
export const mapCenter = writable<[number, number]>([11.5, 50.7]); // DACH-Mitte [lon, lat]
