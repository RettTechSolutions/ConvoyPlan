import { writable } from 'svelte/store';
import type { LageLayer } from '$lib/api';

export const lageLayers = writable<LageLayer[]>([]);
