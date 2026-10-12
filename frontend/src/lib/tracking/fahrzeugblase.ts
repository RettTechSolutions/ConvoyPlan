/**
 * Was die Blase an einem Fahrzeug auf der Karte zeigt.
 *
 * Dieselben Angaben wie die Fahrzeugzeile in der Seitenleiste — Status, Stärke,
 * Betriebsstoff, Tracker — und den nächsten Wegpunkt, aber dort, wo man hinsieht, wenn man auf der Karte
 * ein Fahrzeug sucht. Die Zeile kürzt, weil sie in die Leiste passen muss; die
 * Blase darf etwas mehr sagen (Soll, Reichweite, Akku und Empfang in Worten).
 *
 * Reine Funktion: Tracking-Ansicht und Fahrer-Link geben ihre Live-Werte hinein,
 * `MapView` setzt die Zeilen per `textContent` (Fahrzeugnamen kommen vom
 * Anwender, und der Fahrer-Link ist öffentlich).
 */
import { betriebsstoffKurz, istKnapp, reichweiteKm, type Betriebsstoff } from './betriebsstoff';
import { formatStaerke, weichtAb, type Staerke } from './staerke';
import { akkuTitel, empfangTitel, type TrackerAnzeige } from './trackerzustand';
import { naechsterHaltText, type NaechsterHalt } from './naechsterhalt';

export interface BlasenZeile {
	text: string;
	/** Verdient Aufmerksamkeit (Halt/Ausfall, Abweichung vom Soll, knapp, Akku schwach). */
	warnung?: boolean;
}

export interface FahrzeugAngaben {
	/** Fahrzeugname, wenn die Marke den Funkrufnamen trägt — sonst leer. */
	name?: string | null;
	status: string;
	statusText: string;
	/** Bemerkung zum Status — gezeigt nur bei Halt oder Ausfall, dort ist sie der Grund. */
	bemerkung?: string | null;
	soll: Staerke | null;
	ist: Staerke | null;
	betriebsstoff: Betriebsstoff | null;
	tracker?: TrackerAnzeige | null;
	/** Nächster Wegpunkt samt Ankunft (`naechsterhalt.ts`), null ohne Position auf der Route. */
	naechster?: NaechsterHalt | null;
}

const ALARM = new Set(['technical_halt', 'breakdown']);

export function fahrzeugBlase(a: FahrzeugAngaben, jetzt: number): BlasenZeile[] {
	const zeilen: BlasenZeile[] = [];
	if (a.name) zeilen.push({ text: a.name });
	zeilen.push({ text: a.statusText, warnung: ALARM.has(a.status) });
	const bemerkung = a.bemerkung?.trim();
	if (bemerkung && ALARM.has(a.status)) zeilen.push({ text: `„${bemerkung}“`, warnung: true });

	if (a.naechster) zeilen.push(naechsterHaltText(a.naechster));

	// Wie die Zeile: fehlende Meldung ist keine Abweichung.
	if (a.ist) {
		const soll = a.soll ? ` (Soll ${formatStaerke(a.soll)})` : '';
		zeilen.push({ text: `Stärke ${formatStaerke(a.ist)}${soll}`, warnung: weichtAb(a.soll, a.ist) });
	} else {
		zeilen.push({ text: 'Stärke: keine Meldung' });
	}

	// Ohne Meldung keine Zeile — wie in der Leiste ist das der Normalfall.
	if (a.betriebsstoff) {
		const b = a.betriebsstoff;
		const km = reichweiteKm(b);
		// Kurzform wie in der Zeile; die Reichweite nur, wenn die nicht schon sie ist.
		const reichweite = b.fuellstand !== null && km !== null ? ` · Reichweite etwa ${Math.round(km)} km` : '';
		zeilen.push({
			text: `${b.elektrisch ? 'Ladestand' : 'Betriebsstoff'} ${betriebsstoffKurz(b)}${reichweite}`,
			warnung: istKnapp(b),
		});
	}

	if (a.tracker) {
		zeilen.push({ text: `Tracker: ${akkuTitel(a.tracker, jetzt)}`, warnung: a.tracker.akku_niedrig });
		zeilen.push({ text: empfangTitel(a.tracker, jetzt) });
	}
	return zeilen;
}

/** „50 km/h · Stand 14:32:05" — die Zeile, die `MapView` aus der Position selbst baut. */
export function positionsZeile(
	pos: { speed_kmh: number | null; recorded_at: string; quelle?: 'tracker' | null },
): string {
	const tempo = pos.speed_kmh == null ? '– km/h' : `${pos.speed_kmh.toFixed(0)} km/h`;
	const zeit = new Date(pos.recorded_at);
	const stand = Number.isNaN(zeit.getTime())
		? ''
		: ` · Stand ${zeit.toLocaleTimeString('de-DE', { hour: '2-digit', minute: '2-digit', second: '2-digit' })}`;
	return `${tempo}${stand}${pos.quelle === 'tracker' ? ' · Tracker' : ''}`;
}
