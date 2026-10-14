import { onMount } from 'svelte';

/**
 * Den gewählten Reiter über ein Neuladen hinweg behalten.
 *
 * Im `sessionStorage`, nicht in der Adresse: ein `#tab` oder `?tab` landete in
 * geteilten Links und QR-Codes (Fahrer-Link), und ein zweiter Browser-Tab mit
 * derselben Seite soll seinen eigenen Reiter behalten. Der Schlüssel ist der
 * Pfad — zwei Organisationen oder Konvois setzen sich nicht gegenseitig.
 *
 * Wiederhergestellt wird in `onMount`, nicht beim Anlegen des Zustands: Admin-
 * Portal und Fahrer-Link rendern auf dem Server, und ein Reiter, den es dort
 * nicht gab, ergäbe beim Hydrieren eine andere Seite als die ausgelieferte.
 * Deshalb vor dem `onMount` der Seite aufrufen — dann sieht deren Laden schon
 * den gemerkten Reiter.
 *
 * Gelesen wird nur, was die Seite als Reiter kennt; ein umbenannter oder
 * entfernter Reiter fällt still auf den Standard zurück.
 */
export function reiterMerken<T extends string>(
	erlaubt: readonly T[],
	lesen: () => T,
	setzen: (reiter: T) => void,
): void {
	let bereit = false;
	const schluessel = () => `convoyplan.reiter:${location.pathname}`;

	onMount(() => {
		try {
			const wert = sessionStorage.getItem(schluessel());
			if (wert !== null && (erlaubt as readonly string[]).includes(wert)) setzen(wert as T);
		} catch { /* privater Modus, gesperrter Speicher: dann eben der Standard */ }
		bereit = true;
	});

	$effect(() => {
		const reiter = lesen();
		if (!bereit) return;
		try { sessionStorage.setItem(schluessel(), reiter); } catch { /* ignore */ }
	});
}
