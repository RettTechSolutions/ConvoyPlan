import { ApiError } from '$lib/api/client';

/** Angezeigt, wenn das Backend keine verwertbare Begründung geliefert hat. */
const GENERIC = 'Demo konnte nicht gestartet werden. Bitte später nochmal versuchen.';

export interface DemoFailure {
	/** Begründung im Klartext — direkt anzeigbar. */
	message: string;
	/** Zeitpunkt, ab dem wieder eine Demo möglich ist (nur bei der IP-Karenzzeit). */
	retryAt: Date | null;
}

/**
 * Warum der Demo-Start fehlgeschlagen ist — in der Sprache des Besuchers.
 *
 * Das Backend begründet die Ablehnung bereits im Klartext (Demo abgeschaltet,
 * IP-Karenzzeit noch nicht abgelaufen, zu viele Versuche), diese Begründung
 * wurde bislang aber verschluckt und durch „bitte später nochmal versuchen"
 * ersetzt — ein Ratschlag, der bei einer 24-Stunden-Karenzzeit ins Leere läuft.
 * Nur Texte, die tatsächlich aus einer Antwort des Backends stammen, werden
 * durchgereicht; ein Netzwerk- oder Parserfehler landet beim Standardtext.
 */
export function demoFailureReason(err: unknown): string {
	return err instanceof ApiError && err.detail ? err.detail : GENERIC;
}

/**
 * Dasselbe, zusätzlich mit dem Zeitpunkt der Wiederfreigabe: Das Backend
 * schickt bei der IP-Karenzzeit ein ISO-Datum mit, damit der Browser es in der
 * Zeitzone des Besuchers anzeigen kann — „in 24 Stunden" lässt offen, wann
 * genau das ist.
 */
export function demoFailure(err: unknown): DemoFailure {
	const raw = err instanceof ApiError ? err.data?.retry_at : null;
	const parsed = typeof raw === 'string' ? new Date(raw) : null;
	return {
		message: demoFailureReason(err),
		retryAt: parsed && !Number.isNaN(parsed.getTime()) ? parsed : null,
	};
}

/** „Donnerstag, 14.08.2026 um 09:35 Uhr" — in der Zeitzone des Besuchers. */
export function formatRetryAt(moment: Date): string {
	const day = moment.toLocaleDateString('de-DE', {
		weekday: 'long',
		day: '2-digit',
		month: '2-digit',
		year: 'numeric',
	});
	const time = moment.toLocaleTimeString('de-DE', { hour: '2-digit', minute: '2-digit' });
	return `${day} um ${time} Uhr`;
}
