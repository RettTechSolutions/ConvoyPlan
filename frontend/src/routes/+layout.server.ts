/**
 * Was jede Seite über diese Instanz wissen muss.
 *
 * Bisher wusste nur die Startseite, ob die Agenten-Auskunft eingeschaltet ist
 * — und damit, ob es die Seiten `/about` bis `/privacy` auf dieser Instanz
 * überhaupt gibt. Der Seitenfuß steht dagegen unter jeder öffentlichen Seite
 * und muss entscheiden, wohin „Datenschutz" zeigt: auf die eigene Seite der
 * Instanz oder, wenn es die nicht gibt, auf die des Herstellers.
 *
 * Der Wert kommt aus der Umgebung und hängt weder an Parametern noch an der
 * Anfrage. SvelteKit führt diese Funktion deshalb einmal je Seitenaufruf aus
 * und nicht bei jeder Navigation.
 */
import { discoveryEnabled } from '$lib/server/agent/dispatch';
import type { LayoutServerLoad } from './$types';

export const load: LayoutServerLoad = () => ({ agentDiscovery: discoveryEnabled() });
