/**
 * Die Form der Daten, die eine Informationsseite vom Server bekommt.
 *
 * Steht bewusst *nicht* in `lib/server/`: die Svelte-Komponente braucht den
 * Typ, und alles unter `lib/server/` darf in Client-Code nicht importiert
 * werden — auch nicht als Typ, weil der Import erst nach dem Bündeln
 * verschwindet.
 */
export interface InfoPageData {
	readonly title: string;
	readonly heading: string;
	readonly description: string;
	readonly html: string;
	readonly markdownUrl: string;
	readonly canonical: string;
}
