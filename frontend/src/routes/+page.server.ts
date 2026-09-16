/**
 * Was die Startseite serverseitig braucht.
 *
 * Bis hierher war `/` eine reine Client-Seite: im ausgelieferten HTML stand ein
 * Logo, ein Eingabefeld und ein Knopf — zusammen rund 40 Zeichen Text. Für
 * einen Menschen reicht das, für einen Crawler oder ein Sprachmodell ist es
 * eine leere Seite. Der beschreibende Teil kommt deshalb vom Server und steht
 * im HTML, bevor irgendein Skript läuft.
 */
import { buildContext, discoveryEnabled } from '$lib/server/agent/dispatch';
import type { PageServerLoad } from './$types';

export const load: PageServerLoad = async ({ url, fetch }) => {
	if (!discoveryEnabled()) {
		return { agentDiscovery: false, base: url.origin, demoHint: false };
	}
	const ctx = await buildContext(url, fetch);
	return {
		agentDiscovery: true,
		base: ctx.base,
		demoHint: ctx.demoEnabled
	};
};
