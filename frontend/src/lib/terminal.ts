/**
 * Log-Terminals im Admin-Portal (Software-Update, Regionswechsel).
 *
 * Beide Ströme lesen beim Verbinden ab Byte 0, ein abgeschlossener Wechsel
 * schickt also beim Öffnen der Seite sein ganzes Log noch einmal — Hunderte
 * Zeilen GraphHopper-Ausgabe in einem Schwall. Bisher löste jede Zeile ein
 * eigenes Rendern und ein `scrollTop = scrollHeight` mit `scroll-behavior:
 * smooth` aus: Das Terminal spulte bei jedem Seitenaufruf sichtbar von oben
 * nach unten, und jede Zeile kopierte die ganze Liste (quadratisch).
 *
 * Deshalb zwei Teile: Zeilen werden je Bildaufbau gesammelt angehängt, und das
 * Terminal springt ohne Animation ans Ende — aber nur, wenn es dort schon
 * stand. Wer hochgescrollt hat, um eine Fehlermeldung zu lesen, wird nicht
 * bei jeder neuen Zeile wieder heruntergerissen.
 */

/** Abstand zum Ende in px, der noch als „steht am Ende" gilt. */
const AM_ENDE_PX = 24;

/**
 * Svelte-Action: hält das Element am unteren Ende, solange es dort steht.
 * Beobachtet den Inhalt selbst, die Aufrufer müssen nach dem Anhängen nichts
 * mehr tun.
 */
export function folgtDemEnde(node: HTMLElement) {
	let amEnde = true;
	const ansEnde = () => {
		node.scrollTop = node.scrollHeight;
	};
	const onScroll = () => {
		amEnde = node.scrollHeight - node.scrollTop - node.clientHeight <= AM_ENDE_PX;
	};
	const beobachter = new MutationObserver(() => {
		if (amEnde) ansEnde();
	});
	beobachter.observe(node, { childList: true, subtree: true, characterData: true });
	node.addEventListener('scroll', onScroll, { passive: true });
	ansEnde();
	return {
		destroy() {
			beobachter.disconnect();
			node.removeEventListener('scroll', onScroll);
		},
	};
}

/**
 * Sammelt eingehende Zeilen und reicht sie einmal je Bildaufbau weiter.
 * `verwerfen()` wirft noch nicht weitergereichte Zeilen weg — für einen Strom,
 * der inzwischen ersetzt wurde.
 */
export function zeilenSammler(anhaengen: (zeilen: string[]) => void) {
	let puffer: string[] = [];
	let geplant = 0;
	const ausgeben = () => {
		geplant = 0;
		const zeilen = puffer;
		puffer = [];
		if (zeilen.length) anhaengen(zeilen);
	};
	return {
		push(zeile: string) {
			puffer.push(zeile);
			if (!geplant) geplant = requestAnimationFrame(ausgeben);
		},
		/** Sofort weiterreichen, was noch wartet (z. B. vor dem Ende des Stroms). */
		leeren() {
			if (geplant) cancelAnimationFrame(geplant);
			ausgeben();
		},
		verwerfen() {
			if (geplant) cancelAnimationFrame(geplant);
			geplant = 0;
			puffer = [];
		},
	};
}
