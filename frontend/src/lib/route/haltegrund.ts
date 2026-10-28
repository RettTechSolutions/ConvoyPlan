/**
 * Haltegrund (`halt_purpose`) für die Anzeige. Dieselben Wörter wie die Auswahl
 * im Wegpunkt-Formular der Planung; ohne Zuordnung stand der Schlüssel roh da
 * („rest").
 */
export const HALTEGRUND: Record<string, string> = {
	fuel: 'Tanken',
	rest: 'Pause',
	maintenance: 'Wartung',
	other: 'Sonstiges',
};

export const haltegrundText = (grund: string): string => HALTEGRUND[grund] ?? grund;
