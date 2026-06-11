// Single source of truth for the live-tracking vehicle statuses (Kurz-Stati)
// used to ease communication between vehicles and the convoy leadership.

export type VehicleStatus =
	| 'planned'
	| 'en_route'
	| 'arrived'
	| 'technical_halt'
	| 'breakdown';

/** Urgency for a requested technical halt. */
export type HaltLevel = 'standard' | 'dringend' | 'sehr_dringend';
/** Severity of a breakdown / technical failure. */
export type BreakdownLevel = 'total' | 'limited';

export const STATUS_LABELS: Record<string, string> = {
	planned: 'Geplant',
	en_route: 'Unterwegs',
	arrived: 'Angekommen',
	technical_halt: 'Techn. Halt',
	breakdown: 'Ausfall/Störung',
	// Legacy value tolerated on old convoys.
	delayed: 'Unterwegs',
};

export const STATUS_COLORS: Record<string, string> = {
	planned: '#95a5a6', // grau
	en_route: '#3498db', // blau
	arrived: '#27ae60', // grün
	technical_halt: '#f1c40f', // gelb
	breakdown: '#E23D28', // rot
	delayed: '#3498db',
};

export const STATUS_ICONS: Record<string, string> = {
	planned: '○',
	en_route: '▶',
	arrived: '✓',
	technical_halt: '⏸',
	breakdown: '⚠',
};

export const HALT_LEVEL_LABELS: Record<HaltLevel, string> = {
	standard: 'Standard',
	dringend: 'Dringend',
	sehr_dringend: 'Sehr dringend',
};

export const BREAKDOWN_LEVEL_LABELS: Record<BreakdownLevel, string> = {
	total: 'Totalausfall – sofort halten',
	limited: 'Eingeschränkt – in Sicherheit fahren',
};

export function statusColor(status: string | null | undefined): string {
	return STATUS_COLORS[status ?? 'planned'] ?? '#95a5a6';
}

export function statusLabel(status: string | null | undefined): string {
	return STATUS_LABELS[status ?? 'planned'] ?? (status ?? 'planned');
}

/** Human-readable sub-level label for a given status. */
export function levelLabel(status: string, level: string | null | undefined): string | null {
	if (!level) return null;
	if (status === 'technical_halt') return HALT_LEVEL_LABELS[level as HaltLevel] ?? level;
	if (status === 'breakdown') return BREAKDOWN_LEVEL_LABELS[level as BreakdownLevel] ?? level;
	return null;
}
