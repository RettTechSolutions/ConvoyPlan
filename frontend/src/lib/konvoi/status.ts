// Status eines Konvois (`Convoy.status`) — nicht zu verwechseln mit dem
// Marschstatus der Fahrzeuge in `$lib/tracking/status`.
//
// „Aktiv" ist mehr als eine Beschriftung: fest eingebaute Tracker senden nur,
// solange ihr Fahrzeug in einem aktiven Konvoi steht (`ortungsgeraet.LAUFEND`
// im Backend). `running` kennt das Backend aus älteren Ständen; es gilt als aktiv.

export type KonvoiStatus = 'planning' | 'active' | 'running' | 'completed';

export function istAktiv(status: string | null | undefined): boolean {
	return status === 'active' || status === 'running';
}

export function statusLabel(status: string | null | undefined): string {
	if (istAktiv(status)) return 'Aktiv';
	if (status === 'completed') return 'Abgeschlossen';
	return 'In Planung';
}
