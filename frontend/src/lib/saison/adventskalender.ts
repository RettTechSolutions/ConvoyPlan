import { writable } from 'svelte/store';
import { hash, liesListe, schreibListe, wuerfeln, type Lage } from './anker';
import { VERSTECKE } from './ostereier';

/**
 * Adventskalender: Vom 1. bis 24. Dezember versteckt sich jeden Tag ein
 * Türchen an einem der Anker, an denen zu Ostern die Eier liegen. Wer es
 * findet, öffnet es; verpasste Tage lassen sich im Kalender nachholen, das
 * heutige nur durch Finden, künftige gar nicht.
 *
 * Die Inhalte sind entweder Kniffe aus ConvoyPlan — dann müssen sie stimmen,
 * wer eine Funktion ändert, sieht hier nach — oder erkennbar Quatsch.
 */

export interface Tuerchen {
	symbol: string;
	text: string;
}

export const TUERCHEN: Tuerchen[] = [
	{ symbol: '🕯️', text: 'Das erste Türchen! Bis Heiligabend versteckt sich hier jeden Tag ein neues – mal in diesem Reiter, mal in einem anderen.' },
	{ symbol: '🚨', text: 'Die Rettungsgasse wird gebildet, sobald der Verkehr stockt – nicht erst, wenn das Martinshorn zu hören ist. Ganz links fahrend nach links, alle anderen nach rechts.' },
	{ symbol: '🖱️', text: 'Rechtsklick, Umschalt+F10 oder langes Drücken öffnet fast überall ein Kontextmenü – mit denselben Funktionen wie die Knöpfe daneben.' },
	{ symbol: '🦌', text: 'Auch der Weihnachtsmann fährt im geschlossenen Verband: neun Rentiere, ein Führungsfahrzeug, null Funklöcher.' },
	{ symbol: '🤝', text: 'Heute ist der Internationale Tag des Ehrenamts. Danke an alle, die ihre Freizeit in Wachen, Hallen und auf der Autobahn verbringen!' },
	{ symbol: '🎅', text: 'Nikolaus! Eine Route über die Schornsteine gibt es trotzdem nicht – auch nicht mit der Straßenpräferenz „schnell“.' },
	{ symbol: '🗺️', text: 'Die Route lässt sich auf der Karte ziehen: Der neue Wegpunkt landet genau zwischen den beiden, zwischen denen du gezogen hast.' },
	{ symbol: '📏', text: 'Durchfahrtshöhen: Gesperrt wird nach dem höchsten Fahrzeug im Verband. Wo es trotzdem eng wird, steht unter der Route.' },
	{ symbol: '⛴️', text: 'Fähren zählen als Reisezeit, nicht als Lenkzeit. Eine Überfahrt ab neun Stunden gilt als Tagesruhe – an Bord nur mit Schlafkabine.' },
	{ symbol: '📱', text: 'Der Fahrer-Link geht per QR-Code aufs Telefon. Im Code steht nur die Adresse – kein Passwort, keine Sitzung.' },
	{ symbol: '☕', text: 'Technischer Halt: anhalten, Ladung und Fahrzeuge prüfen, weiterfahren. Kaffee ist dabei ausdrücklich nicht verboten.' },
	{ symbol: '📄', text: 'Den Marschbefehl gibt es auch als Word-Dokument – aus der eigenen Vorlage der Organisation (Org-Admin → Marschbefehl).' },
	{ symbol: '📶', text: 'Funkloch? Die Fahrzeugbelegung bleibt bestehen. Erst nach fünf Minuten ohne jedes Lebenszeichen wird das Fahrzeug wieder frei.' },
	{ symbol: '🧭', text: 'Die Reihenfolge der Wegpunkte gehört dir. ConvoyPlan sortiert nichts heimlich um – nur übernommene Halte-Vorschläge werden einmal eingeordnet.' },
	{ symbol: '⚖️', text: 'Gewichtsgrenzen mit „Anlieger frei“ werden gemieden, nicht gesperrt – sonst gäbe es zu manchem Ziel gar keine Route.' },
	{ symbol: '🌉', text: 'Brücken ohne Höhenangabe in OpenStreetMap kennt das Routing nicht. Die Brückensuche nach der Berechnung findet sie trotzdem.' },
	{ symbol: '🛰️', text: 'Ein Tracker sendet nur, solange sein Fahrzeug in einem laufenden Konvoi eingeplant ist. Ortung rund um die Uhr gibt es nicht.' },
	{ symbol: '🐞', text: 'Etwas klemmt? „Melden“ in der Seitenleiste schickt auf Wunsch gleich ein Bildschirmfoto mit.' },
	{ symbol: '⛓️', text: 'Schneeketten werden vor der Passstraße aufgezogen, nicht in der dritten Kehre. Ein Halt davor passt in jeden Zeitplan.' },
	{ symbol: '📖', text: 'Das Roadbook nennt auch freie Durchfahrten: „4,5 m, +85 cm“ sagt der Besatzung, wo sie nicht bremsen muss.' },
	{ symbol: '🌌', text: 'Um den 21. Dezember ist die längste Nacht des Jahres. Gute Gelegenheit, den Verband im Tracking als Lichterkette zu betrachten.' },
	{ symbol: '🔑', text: 'Passkey statt Passwort: Anmelden per Fingerabdruck oder Gesichtserkennung – einzurichten unter „Konto“.' },
	{ symbol: '🍪', text: 'Morgen ist Heiligabend. Plätzchen für die Wache sind kein Gefahrgut – aber bitte trotzdem gesichert verladen.' },
	{ symbol: '🛷', text: 'Frohe Weihnachten! Heute ist ein ganz besonderer Konvoi unterwegs … Danke für ein Jahr voller Einsätze, Übungen und Verlegungen.' },
];

/** Das Türchen von heute, oder `null` außerhalb des 1. bis 24. Dezember. */
export function tuerchenHeute(jetzt: Date): number | null {
	if (jetzt.getMonth() !== 11) return null;
	const tag = jetzt.getDate();
	return tag <= 24 ? tag : null;
}

/** Bis zu welchem Tag Türchen offen stehen dürfen: im Advent heute, ab dem 25. alle. */
export function bisTag(jetzt: Date): number {
	if (jetzt.getMonth() !== 11) return jetzt.getMonth() === 0 ? 24 : 0;
	return Math.min(jetzt.getDate(), 24);
}

/** Wo sich das Türchen eines Tages versteckt — je Jahr anders. */
export function versteck(tag: number, schluessel: string): string {
	return VERSTECKE[hash(`tuer-${tag}:${schluessel}`) % VERSTECKE.length];
}

export function lage(tag: number, schluessel: string): Lage {
	return wuerfeln(`tuer-${tag}-lage:${schluessel}`);
}

const SPEICHER = 'convoyplan-advent:';

function createKalenderStore() {
	const { subscribe, set, update } = writable<{ schluessel: string; offen: number[] }>({ schluessel: '', offen: [] });

	return {
		subscribe,
		laden(schluessel: string) {
			set({ schluessel, offen: liesListe<number>(SPEICHER + schluessel).filter((t) => Number.isInteger(t) && t >= 1 && t <= 24) });
		},
		oeffnen(tag: number) {
			update((z) => {
				if (z.offen.includes(tag)) return z;
				const offen = [...z.offen, tag].sort((a, b) => a - b);
				schreibListe(SPEICHER + z.schluessel, offen);
				return { ...z, offen };
			});
		},
	};
}

export const kalenderStore = createKalenderStore();
