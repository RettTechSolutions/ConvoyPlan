/**
 * Bildschirmfotos für den Melde-Dialog — aufnehmen, einfügen, verkleinern.
 *
 * Drei Wege, absichtlich nebeneinander:
 *
 * - **Aufnehmen** über `getDisplayMedia`. Der Browser fragt selbst, was geteilt
 *   wird; ohne diese Zustimmung bekommt die Seite kein Bild. Das ist der
 *   bequemste Weg und der einzige, den es auf dem Telefon nicht gibt.
 * - **Einfügen** aus der Zwischenablage (Strg+V, Druck-Taste davor). Der Weg,
 *   den Windows-Anwender ohnehin kennen.
 * - **Datei wählen** — der Rückfall, der überall funktioniert.
 *
 * Keine Fremdbibliothek. `html2canvas` & Co. zeichnen das DOM *nach*, und was
 * dabei herauskommt, ist gerade bei dem, worüber sich jemand beschwert — Karte,
 * Schriftarten, überlagerte Ebenen — nicht das, was auf dem Schirm stand. Ein
 * Bildschirmfoto, das etwas anderes zeigt als der Bildschirm, ist schlimmer als
 * keines.
 */

/** Die längste Kante, auf die verkleinert wird. Ein 4K-Schirm ergäbe sonst 8 MB. */
const MAX_KANTE = 1920;

/**
 * Obergrenze in Bytes für das fertige Bild. Muss unter der Grenze des Backends
 * (`MAX_SCREENSHOT_BYTES`, 4 MB) liegen — mit Luft, weil die Umrechnung aus der
 * Base64-Länge nur ungefähr ist.
 */
const MAX_BYTES = 3_500_000;

/** Die JPEG-Qualitätsstufen, in dieser Reihenfolge, bis es passt. */
const STUFEN = [0.85, 0.7, 0.55];

/** Ungefähre Bytezahl hinter einer Data-URL, ohne sie zu dekodieren. */
export function bytesEinerDataUrl(dataUrl: string): number {
	const komma = dataUrl.indexOf(',');
	if (komma < 0) return 0;
	const nutzdaten = dataUrl.length - komma - 1;
	const fuellzeichen = dataUrl.endsWith('==') ? 2 : dataUrl.endsWith('=') ? 1 : 0;
	return Math.max(0, Math.floor((nutzdaten * 3) / 4) - fuellzeichen);
}

/** Ob der Browser eine Bildschirmaufnahme anbietet (Desktop ja, Telefon nein). */
export function aufnahmeMoeglich(): boolean {
	return (
		typeof navigator !== 'undefined' &&
		typeof navigator.mediaDevices?.getDisplayMedia === 'function'
	);
}

function bildLaden(dataUrl: string): Promise<HTMLImageElement> {
	return new Promise((erfuellen, ablehnen) => {
		const bild = new Image();
		bild.onload = () => erfuellen(bild);
		bild.onerror = () => ablehnen(new Error('Das Bild ließ sich nicht lesen.'));
		bild.src = dataUrl;
	});
}

/**
 * Auf `MAX_KANTE` und `MAX_BYTES` bringen.
 *
 * PNG zuerst, weil ein Bildschirmfoto aus Text und Flächen besteht und darin
 * verlustfrei *kleiner* ist als JPEG. Erst wenn das nicht reicht — Karte,
 * Luftbild —, wird auf JPEG umgestellt, und zwar stufenweise: lieber ein
 * sichtbar komprimiertes Bild als gar keines.
 */
export async function verkleinern(dataUrl: string): Promise<string> {
	const bild = await bildLaden(dataUrl);
	const faktor = Math.min(1, MAX_KANTE / Math.max(bild.width, bild.height));
	const passt = faktor === 1 && bytesEinerDataUrl(dataUrl) <= MAX_BYTES;
	if (passt) return dataUrl;

	const canvas = document.createElement('canvas');
	canvas.width = Math.max(1, Math.round(bild.width * faktor));
	canvas.height = Math.max(1, Math.round(bild.height * faktor));
	const ctx = canvas.getContext('2d');
	if (!ctx) throw new Error('Der Browser stellt keine Zeichenfläche bereit.');
	ctx.drawImage(bild, 0, 0, canvas.width, canvas.height);

	const alsPng = canvas.toDataURL('image/png');
	if (bytesEinerDataUrl(alsPng) <= MAX_BYTES) return alsPng;

	for (const stufe of STUFEN) {
		const alsJpeg = canvas.toDataURL('image/jpeg', stufe);
		if (bytesEinerDataUrl(alsJpeg) <= MAX_BYTES) return alsJpeg;
	}
	throw new Error('Das Bild bleibt auch verkleinert zu groß.');
}

/** Wird geworfen, wenn der Anwender die Freigabe abbricht — kein Fehler. */
export class AufnahmeAbgebrochen extends Error {}

/**
 * Ein Bildschirmfoto über die Freigabe des Browsers aufnehmen.
 *
 * Der Aufrufer blendet den Melde-Dialog vorher aus — sonst zeigt das Bild den
 * Dialog und nicht das, worum es geht.
 */
export async function bildschirmAufnehmen(): Promise<string> {
	if (!aufnahmeMoeglich()) {
		throw new Error('Dieser Browser kann keine Bildschirmaufnahme starten.');
	}
	let stream: MediaStream;
	try {
		stream = await navigator.mediaDevices.getDisplayMedia({
			// `preferCurrentTab` ist Chrome-eigen und stellt den aktuellen Tab
			// voran; wo es fehlt, ändert es nichts.
			video: { displaySurface: 'browser' },
			audio: false,
			preferCurrentTab: true,
		} as DisplayMediaStreamOptions);
	} catch (e) {
		// `NotAllowedError` heißt hier fast immer: im Auswahldialog abgebrochen.
		if ((e as DOMException)?.name === 'NotAllowedError') {
			throw new AufnahmeAbgebrochen('Aufnahme abgebrochen.');
		}
		throw e;
	}

	try {
		const video = document.createElement('video');
		video.srcObject = stream;
		video.muted = true;
		video.playsInline = true;
		await video.play();
		// Zwei Frames abwarten: nach `play()` steht oft noch ein schwarzes Bild
		// im Puffer, und ein schwarzer Screenshot sieht aus wie ein Fehler der
		// Anwendung.
		await new Promise<void>((r) =>
			requestAnimationFrame(() => requestAnimationFrame(() => r()))
		);

		const canvas = document.createElement('canvas');
		canvas.width = video.videoWidth;
		canvas.height = video.videoHeight;
		if (!canvas.width || !canvas.height) {
			throw new Error('Die Aufnahme lieferte kein Bild.');
		}
		const ctx = canvas.getContext('2d');
		if (!ctx) throw new Error('Der Browser stellt keine Zeichenfläche bereit.');
		ctx.drawImage(video, 0, 0);
		video.srcObject = null;
		return await verkleinern(canvas.toDataURL('image/png'));
	} finally {
		// Immer: ein laufender Stream lässt die Freigabeleiste des Browsers
		// stehen, auch wenn die Aufnahme längst scheiterte.
		for (const track of stream.getTracks()) track.stop();
	}
}

/** Die erlaubten Bildformate — dieselben wie im Backend, ohne SVG. */
const ERLAUBTE_TYPEN = ['image/png', 'image/jpeg', 'image/webp'];

function alsDataUrl(blob: Blob): Promise<string> {
	return new Promise((erfuellen, ablehnen) => {
		const leser = new FileReader();
		leser.onload = () => erfuellen(String(leser.result));
		leser.onerror = () => ablehnen(new Error('Die Datei ließ sich nicht lesen.'));
		leser.readAsDataURL(blob);
	});
}

/** Eine gewählte oder hereingezogene Datei übernehmen. */
export async function dateiUebernehmen(datei: File | Blob): Promise<string> {
	if (!ERLAUBTE_TYPEN.includes(datei.type)) {
		throw new Error('Nur PNG, JPEG oder WebP.');
	}
	return verkleinern(await alsDataUrl(datei));
}

/**
 * Ein Bild aus einem Einfüge-Ereignis, oder `null`, wenn keines dabei war.
 *
 * Kein `throw` bei „nichts dabei": Strg+V in einem Textfeld ist der Normalfall
 * und keine Fehlbedienung.
 */
export function bildAusZwischenablage(event: ClipboardEvent): File | null {
	for (const eintrag of Array.from(event.clipboardData?.items ?? [])) {
		if (eintrag.kind !== 'file') continue;
		const datei = eintrag.getAsFile();
		if (datei && ERLAUBTE_TYPEN.includes(datei.type)) return datei;
	}
	return null;
}
