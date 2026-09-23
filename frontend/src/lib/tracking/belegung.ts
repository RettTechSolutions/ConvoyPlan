// Belegung: ein Fahrzeug sendet von genau einem Gerät.
//
// Der Server hält fest, welches Gerät welches Fahrzeug gewählt hat
// (`backend/app/services/belegung.py`), und verwirft fremde Frames. Diese Datei
// ist die Gegenstelle im Browser, gemeinsam für den Fahrer-Link und das
// angemeldete Tracking — die Begleit-App spricht dasselbe Protokoll.
//
// Früher galt hier „ein Fahrzeug mit Position ist vergeben". Das war doppelt
// falsch: eine Position bleibt stehen, lange nachdem niemand mehr sendet (das
// Fahrzeug blieb für immer ausgegraut), und die App fragte gar nicht erst.
//
// Protokoll (Frames an den Server, nur mit `?client=<kennung>` wirksam):
//   { type: 'belegen',   vehicle_id }  beim Wählen und jede Minute
//   { type: 'freigeben', vehicle_id }  beim Abwählen und beim Verlassen
// Vom Server:
//   { type: 'belegungen', vehicle_ids }         nach jedem Verbindungsaufbau
//   { type: 'belegung', vehicle_id, belegt }    wenn ein Gerät wählt oder freigibt
//   { type: 'belegung_abgelehnt', vehicle_id }  nur an den, der zu spät kam

/** Keepalive. Der Server gibt nach fünf Minuten ohne Frame frei. */
export const BELEGUNG_KEEPALIVE_MS = 60_000;

const KENNUNG_KEY = 'cp-geraet';

/**
 * Die Kennung dieses Tabs. Im `sessionStorage`: ein Neuladen behält sie (die
 * Belegung bleibt), ein zweiter Tab ist ein zweites Gerät — genau der Fall, der
 * sonst doppelt sendet.
 */
export function geraeteKennung(): string {
	try {
		const vorhanden = sessionStorage.getItem(KENNUNG_KEY);
		if (vorhanden && /^[A-Za-z0-9_-]{8,64}$/.test(vorhanden)) return vorhanden;
		const neu = crypto.randomUUID();
		sessionStorage.setItem(KENNUNG_KEY, neu);
		return neu;
	} catch {
		// Kein Speicher (privates Fenster, gesperrt) — dann gilt die Kennung für
		// diese Seite, und ein Neuladen wählt neu.
		return crypto.randomUUID();
	}
}

export interface BelegungOptions {
	/** Schickt einen Frame. `false`, wenn der Kanal gerade nicht trägt. */
	send: (frame: { type: 'belegen' | 'freigeben'; vehicle_id: string }) => boolean;
	/** Fahrzeuge, die ein **anderes** Gerät hält. */
	onChange: (fremd: ReadonlySet<string>) => void;
	/** Das eigene Fahrzeug war schon vergeben — die Wahl ist zurückgenommen. */
	onAbgelehnt: (vehicleId: string) => void;
}

export interface Belegung {
	/** Das eigene Fahrzeug setzen oder (`null`/`''`) abwählen. */
	waehlen(vehicleId: string | null): void;
	/** Wertet eine Servernachricht aus. `true`, wenn sie zur Belegung gehörte. */
	handle(message: unknown): boolean;
	/** Freigeben und aufhören — beim Verlassen der Seite. */
	stop(): void;
}

export function createBelegung(options: BelegungOptions): Belegung {
	let eigen: string | null = null;
	let fremd = new Set<string>();
	let timer: ReturnType<typeof setInterval> | null = null;

	function belegen() {
		if (eigen) options.send({ type: 'belegen', vehicle_id: eigen });
	}

	function keepalive(an: boolean) {
		if (timer) { clearInterval(timer); timer = null; }
		if (an) timer = setInterval(belegen, BELEGUNG_KEEPALIVE_MS);
	}

	function setFremd(next: Set<string>) {
		fremd = next;
		options.onChange(fremd);
	}

	return {
		waehlen(vehicleId) {
			const neu = vehicleId || null;
			if (neu === eigen) return;
			if (eigen) options.send({ type: 'freigeben', vehicle_id: eigen });
			eigen = neu;
			belegen();
			keepalive(eigen !== null);
		},

		handle(message) {
			if (!message || typeof message !== 'object') return false;
			const msg = message as { type?: unknown; vehicle_id?: unknown; vehicle_ids?: unknown; belegt?: unknown };
			switch (msg.type) {
				case 'belegungen': {
					const ids = Array.isArray(msg.vehicle_ids)
						? msg.vehicle_ids.filter((v): v is string => typeof v === 'string')
						: [];
					setFremd(new Set(ids.filter((id) => id !== eigen)));
					// Kommt nach jedem Verbindungsaufbau: die Wahl von vorhin gilt
					// wieder — und nach einem Neustart des Servers muss sie neu belegt
					// werden, bevor jemand anderes zugreift.
					belegen();
					return true;
				}
				case 'belegung': {
					if (typeof msg.vehicle_id !== 'string') return true;
					// Die eigene Belegung ist keine fremde.
					if (msg.vehicle_id === eigen) return true;
					const next = new Set(fremd);
					if (msg.belegt === true) next.add(msg.vehicle_id);
					else next.delete(msg.vehicle_id);
					setFremd(next);
					return true;
				}
				case 'belegung_abgelehnt': {
					if (typeof msg.vehicle_id !== 'string') return true;
					const next = new Set(fremd);
					next.add(msg.vehicle_id);
					if (msg.vehicle_id === eigen) {
						eigen = null;
						keepalive(false);
						setFremd(next);
						options.onAbgelehnt(msg.vehicle_id);
					} else {
						setFremd(next);
					}
					return true;
				}
				default:
					return false;
			}
		},

		stop() {
			if (eigen) options.send({ type: 'freigeben', vehicle_id: eigen });
			eigen = null;
			keepalive(false);
		},
	};
}

/** Klartext, wenn das gewählte Fahrzeug schon von einem anderen Gerät gesendet wird. */
export const BELEGT_HINWEIS =
	'Dieses Fahrzeug sendet bereits von einem anderen Gerät. Bitte ein anderes wählen.';
