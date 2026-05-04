import { writable } from 'svelte/store';
import type { Convoy, RouteResult } from '$lib/api';

export const convoys = writable<Convoy[]>([]);
export const activeConvoy = writable<Convoy | null>(null);
export const activeRoute = writable<RouteResult | null>(null);
