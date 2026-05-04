import { writable } from 'svelte/store';

export type MapMode = 'idle' | 'set-start' | 'set-end' | 'add-waypoint';

export const mapMode = writable<MapMode>('idle');
export const mapCenter = writable<[number, number]>([10.0, 51.5]); // Deutschland-Mitte
