import { ApiError } from '$lib/api/client';

/** Angezeigt, wenn das Backend keine verwertbare Begründung geliefert hat. */
const GENERIC = 'Demo konnte nicht gestartet werden. Bitte später nochmal versuchen.';

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
