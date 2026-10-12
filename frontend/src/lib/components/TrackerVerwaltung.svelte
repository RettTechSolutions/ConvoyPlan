<script lang="ts">
	/**
	 * Ortungsgeräte (Tracker) im Org-Admin: anlegen, mit einem Fahrzeug koppeln,
	 * Kanal wählen, sperren, neu einrichten, löschen.
	 *
	 * Ein Tracker sendet nur, solange sein Fahrzeug in einem laufenden Konvoi
	 * steht — das entscheidet der Server (`services/ortungsgeraet.py`), nicht das
	 * Gerät und nicht diese Seite. Der Einmal-Code zum Einrichten steht hier
	 * **einmal**, direkt nach Anlegen oder „Neu einrichten"; gespeichert ist nur
	 * sein Hash. Er gilt 24 Stunden.
	 *
	 * Einrichten geht per USB direkt von hier (Web Serial, `$lib/tracker/usb.ts`): Die
	 * Seite schreibt Adresse, Code und optional eigene Wurzelzertifikate, APN und Funknetz
	 * sowie WLAN-Netze aufs Gerät, das Gerät löst den Code selbst ein, über WLAN oder
	 * Mobilfunk. Der Browser sieht dabei nie ein Token. Die WLAN-Netze lassen sich später
	 * allein ändern („WLAN per USB"); ihre Passwörter gehen nur aufs Gerät, nie an die Instanz.
	 */
	import { onMount } from 'svelte';
	import TrackerZustand from '$lib/components/TrackerZustand.svelte';
	import { stoerung, STOERUNG_TEXT } from '$lib/tracking/trackerzustand';
	import {
		geraeteApi,
		vehiclesApi,
		type Tracker,
		type TrackerDaten,
		type TrackerKanal,
		type TrackerMitCode,
		type TrackerTakt
	} from '$lib/api';
	import {
		FUNKNETZE,
		SCHRITTTEXT,
		TrackerUsb,
		WLAN_MAX,
		WURZELN_MAX,
		apnGueltig,
		instanzAdresse,
		funknetzName,
		webSerialVerfuegbar,
		wlanBereinigen,
		wlanPruefen,
		wurzelnLesen,
		type GeraeteInfo,
		type Funknetz,
		type WlanNetz
	} from '$lib/tracker/usb';

	const KANAELE: { wert: TrackerKanal; name: string }[] = [
		{ wert: 'stable', name: 'Stabil' },
		{ wert: 'beta', name: 'Beta' },
		{ wert: 'nightly', name: 'Nightly' }
	];
	const ERGEBNIS: Record<string, string> = {
		bestaetigt: 'eingespielt',
		zurueckgerollt: 'zurückgerollt',
		fehler: 'fehlgeschlagen'
	};
	/** Danach gilt ein Tracker als nicht mehr erreichbar — nach dem Lebenszeichen alle 12 h. */
	const STUMM_AB_MS = 24 * 3600 * 1000;
	/** Ab hier wird „auf Akku" hervorgehoben: über Nacht vom Bordnetz ist normal, einen Tag nicht. */
	const AKKU_WARNUNG_MS = 24 * 3600 * 1000;

	interface Formular {
		id: string | null;
		name: string;
		vehicle_id: string;
		kanal: TrackerKanal;
		aktiv: boolean;
	}

	let geraete = $state<Tracker[]>([]);
	let fahrzeuge = $state<{ id: string; name: string }[]>([]);
	let laden = $state(true);
	let fehler = $state('');
	let erfolg = $state('');
	let formular = $state<Formular | null>(null);
	let speichern = $state(false);
	let neu = $state<TrackerMitCode | null>(null);
	let kopiert = $state(false);
	let usb = $state<{ laeuft: boolean; text: string; fehler: boolean; info: GeraeteInfo | null } | null>(null);
	let wurzelnText = $state('');
	/** WLAN-Netze fürs Einrichten. Nur im Browser und nur bis zum Senden ans Gerät. */
	let wlanNeu = $state<WlanNetz[]>([]);
	/** „WLAN per USB" an einem eingerichteten Tracker: nur die Netze, ohne neu einzurichten. */
	let wlanAendern = $state<{
		id: string;
		name: string;
		netze: WlanNetz[];
		laeuft: boolean;
		text: string;
		fehler: boolean;
	} | null>(null);
	/** Leer bzw. '': das Gerät behält seine bisherigen (ab Werk 1NCE, LTE-M). */
	let apn = $state('');
	let funknetz = $state<Funknetz | ''>('');
	let mitSerial = $state(false);
	let adresse = $state('');
	let takt = $state<TrackerTakt | null>(null);
	let taktGewaehlt = $state(0);
	let taktSpeichern = $state(false);
	/** Für das Rechenbeispiel; nur hier im Browser, gespeichert wird es nicht. */
	let fahrstunden = $state(20);
	let anzahl = $state(0);

	async function neuLaden() {
		laden = true;
		fehler = '';
		try {
			const [g, f] = await Promise.all([geraeteApi.list(), vehiclesApi.list()]);
			geraete = g;
			if (!anzahl) anzahl = Math.max(1, g.length);
			fahrzeuge = f.map((v) => ({ id: v.id, name: v.callsign ? `${v.name} (${v.callsign})` : v.name }));
		} catch (e) {
			fehler = e instanceof Error ? e.message : 'Laden fehlgeschlagen';
		} finally {
			laden = false;
		}
		// Getrennt: Ohne Sendetakt bleibt die Liste benutzbar, nur der Abschnitt fehlt.
		try {
			takt = await geraeteApi.takt();
			taktGewaehlt = takt.buendel_s;
		} catch {
			takt = null;
		}
	}

	onMount(() => {
		mitSerial = webSerialVerfuegbar();
		adresse = instanzAdresse();
		neuLaden();
	});

	const wurzeln = $derived(wurzelnLesen(wurzelnText));
	const apnFehler = $derived(apn.trim() !== '' && !apnGueltig(apn.trim()));

	async function usbEinrichten() {
		if (!neu || usb?.laeuft) return;
		const { code, name } = neu;
		if (wurzeln.length > WURZELN_MAX) {
			usb = { laeuft: false, fehler: true, info: null, text: `Höchstens ${WURZELN_MAX} Wurzelzertifikate.` };
			return;
		}
		if (apnFehler) {
			usb = { laeuft: false, fehler: true, info: null, text: 'Der APN darf nur Buchstaben, Ziffern, Punkt und Bindestrich enthalten.' };
			return;
		}
		const wlan = wlanBereinigen(wlanNeu);
		const wlanFehler = wlanPruefen(wlan);
		if (wlanFehler) {
			usb = { laeuft: false, fehler: true, info: null, text: wlanFehler };
			return;
		}
		let geraet: TrackerUsb | null = null;
		let info: GeraeteInfo | null = null;
		usb = { laeuft: true, fehler: false, info: null, text: 'Gerät wählen …' };
		try {
			geraet = await TrackerUsb.waehlen();
			usb.text = 'Gerät antwortet …';
			info = await geraet.info();
			usb = { laeuft: true, fehler: false, info, text: SCHRITTTEXT.netz };
			await geraet.einrichten(
				adresse,
				code,
				{ wurzeln, apn: apn.trim() || undefined, funknetz: funknetz || undefined, wlan },
				(s) => {
					if (usb) usb.text = SCHRITTTEXT[s];
				}
			);
			const funk = info.apn ? ` Mobilfunk: APN ${apn.trim() || info.apn}, ${funknetzName(funknetz || info.funknetz)}.` : '';
			usb = null;
			neu = null;
			wurzelnText = '';
			apn = '';
			funknetz = '';
			wlanNeu = [];
			erfolg = `„${name}" ist eingerichtet — Gerät ${info.hardware_id}, Firmware ${info.firmware}.${funk}`;
			await neuLaden();
		} catch (e) {
			// Auswahl abgebrochen: kein Fehler, nur nichts passiert.
			if (e instanceof DOMException && e.name === 'NotFoundError') {
				usb = null;
				return;
			}
			usb = { laeuft: false, fehler: true, info, text: e instanceof Error ? e.message : String(e) };
		} finally {
			await geraet?.schliessen();
		}
	}

	function wlanOeffnen(g: Tracker) {
		wlanAendern = { id: g.id, name: g.name, netze: [{ ssid: '', psk: '' }], laeuft: false, text: '', fehler: false };
	}

	/** Schreibt nur die WLAN-Netze aufs Gerät (`wlan`). Die Instanz erfährt davon nichts. */
	async function wlanSchreiben() {
		const a = wlanAendern;
		if (!a || a.laeuft) return;
		const netze = wlanBereinigen(a.netze);
		const pruefung = wlanPruefen(netze);
		if (pruefung) {
			a.fehler = true;
			a.text = pruefung;
			return;
		}
		if (netze.length === 0 && !confirm(`Alle WLAN-Netze von „${a.name}" löschen?\n\nDer Tracker sendet danach nur noch über Mobilfunk oder die Begleit-App.`))
			return;
		let geraet: TrackerUsb | null = null;
		a.laeuft = true;
		a.fehler = false;
		a.text = 'Gerät wählen …';
		try {
			geraet = await TrackerUsb.waehlen();
			a.text = 'Gerät antwortet …';
			const info = await geraet.info();
			const ssids = await geraet.wlanSetzen(netze);
			wlanAendern = null;
			erfolg = ssids.length
				? `WLAN auf Gerät ${info.hardware_id} gespeichert: ${ssids.join(', ')}. Ob es trägt, zeigt das Symbol beim nächsten Kontakt.`
				: `Auf Gerät ${info.hardware_id} ist kein WLAN mehr eingerichtet.`;
		} catch (e) {
			if (e instanceof DOMException && e.name === 'NotFoundError') {
				a.laeuft = false;
				a.text = '';
				return;
			}
			a.laeuft = false;
			a.fehler = true;
			a.text = e instanceof Error ? e.message : String(e);
		} finally {
			await geraet?.schliessen();
		}
	}

	/** Um wie viele Meter die Position bei 50 km/h zwischen zwei Versänden springt. */
	function sprungM(buendel_s: number): number {
		return Math.round((50 / 3.6) * buendel_s / 10) * 10;
	}

	/** KB je Stunde → MB im Monat für alle Tracker, gerundet für eine Schätzung. */
	function mbImMonat(kb_pro_stunde: number): string {
		const mb = (kb_pro_stunde * Math.max(0, fahrstunden) * Math.max(0, anzahl)) / 1000;
		return mb < 10 ? mb.toLocaleString('de-DE', { maximumFractionDigits: 1 }) : Math.round(mb).toLocaleString('de-DE');
	}

	const taktAktuell = $derived(takt?.wahl.find((w) => w.buendel_s === takt?.buendel_s) ?? null);

	async function taktSichern() {
		if (!takt || taktSpeichern || taktGewaehlt === takt.buendel_s) return;
		taktSpeichern = true;
		fehler = '';
		try {
			takt = await geraeteApi.taktSetzen(taktGewaehlt);
			erfolg = `Die Tracker senden in Fahrt jetzt alle ${takt.buendel_s} s — ab ihrem nächsten Kontakt.`;
		} catch (err) {
			fehler = err instanceof Error ? err.message : 'Speichern fehlgeschlagen';
		} finally {
			taktSpeichern = false;
		}
	}

	/** Fahrzeuge, an denen kein anderer Tracker hängt — plus das eigene. */
	const freieFahrzeuge = $derived(
		fahrzeuge.filter((f) => !geraete.some((g) => g.vehicle_id === f.id && g.id !== formular?.id))
	);

	function anlegen() {
		neu = null;
		formular = { id: null, name: '', vehicle_id: '', kanal: 'stable', aktiv: true };
	}

	function bearbeiten(g: Tracker) {
		neu = null;
		formular = { id: g.id, name: g.name, vehicle_id: g.vehicle_id ?? '', kanal: g.kanal, aktiv: g.aktiv };
	}

	function daten(f: Formular): TrackerDaten {
		return { name: f.name.trim(), vehicle_id: f.vehicle_id || null, kanal: f.kanal, aktiv: f.aktiv };
	}

	async function absenden(e: SubmitEvent) {
		e.preventDefault();
		if (!formular || speichern) return;
		speichern = true;
		fehler = '';
		try {
			if (formular.id) {
				await geraeteApi.update(formular.id, daten(formular));
				erfolg = 'Gespeichert.';
			} else {
				neu = await geraeteApi.create(daten(formular));
				erfolg = '';
			}
			formular = null;
			await neuLaden();
		} catch (err) {
			fehler = err instanceof Error ? err.message : 'Speichern fehlgeschlagen';
		} finally {
			speichern = false;
		}
	}

	async function neuEinrichten(g: Tracker) {
		if (
			!confirm(
				`„${g.name}" neu einrichten?\n\nDas Gerät verliert seinen Zugang sofort und sendet erst wieder, wenn es mit dem neuen Code eingerichtet ist.`
			)
		)
			return;
		try {
			neu = await geraeteApi.rotateCode(g.id);
			formular = null;
			erfolg = '';
			await neuLaden();
		} catch (err) {
			fehler = err instanceof Error ? err.message : 'Neu einrichten fehlgeschlagen';
		}
	}

	async function loeschen(g: Tracker) {
		if (!confirm(`Tracker „${g.name}" löschen?\n\nDas Gerät verliert seinen Zugang sofort.`)) return;
		try {
			await geraeteApi.delete(g.id);
			if (neu?.id === g.id) neu = null;
			erfolg = 'Gelöscht.';
			await neuLaden();
		} catch (err) {
			fehler = err instanceof Error ? err.message : 'Löschen fehlgeschlagen';
		}
	}

	async function kopieren(text: string) {
		try {
			await navigator.clipboard.writeText(text);
			kopiert = true;
			setTimeout(() => (kopiert = false), 2000);
		} catch {
			/* Zwischenablage nicht erlaubt — der Code steht zum Markieren da */
		}
	}

	/** „seit 40 min", „seit 5 h", „seit 3 Tagen" — gerundet nach unten, wie es die Instanz weiß. */
	function seit(iso: string, jetzt = Date.now()): string {
		const min = Math.max(0, Math.floor((jetzt - new Date(iso).getTime()) / 60000));
		if (min < 60) return `seit ${min} min`;
		const std = Math.floor(min / 60);
		if (std < 48) return `seit ${std} h`;
		return `seit ${Math.floor(std / 24)} Tagen`;
	}

	function akkuLange(iso: string): boolean {
		return Date.now() - new Date(iso).getTime() >= AKKU_WARNUNG_MS;
	}

	function uhrzeit(iso: string): string {
		return new Date(iso).toLocaleString('de-DE', {
			weekday: 'short',
			day: '2-digit',
			month: '2-digit',
			hour: '2-digit',
			minute: '2-digit'
		});
	}

	function zustand(g: Tracker): { text: string; klasse: string } {
		if (!g.aktiv) return { text: 'gesperrt', klasse: 'aus' };
		if (!g.eingerichtet) return g.code_offen ? { text: 'wartet auf Einrichtung', klasse: 'aus' } : { text: 'Code abgelaufen', klasse: 'aus' };
		if (!g.vehicle_id) return { text: 'ohne Fahrzeug', klasse: 'aus' };
		if (!g.zuletzt_gesehen || Date.now() - new Date(g.zuletzt_gesehen).getTime() > STUMM_AB_MS)
			return { text: 'nicht erreichbar', klasse: 'warn' };
		const s = stoerung(g, Date.now());
		if (s) return { text: STOERUNG_TEXT[s], klasse: 'warn' };
		if (g.akku_niedrig) return { text: 'Akku schwach', klasse: 'warn' };
		return { text: 'bereit', klasse: '' };
	}
</script>

{#snippet wlanFelder(netze: WlanNetz[], praefix: string)}
	<div class="wlan" data-testid="{praefix}-wlan">
		{#each netze as n, i (i)}
			<div class="wlan-zeile">
				<input
					bind:value={n.ssid}
					maxlength="32"
					autocomplete="off"
					aria-label="WLAN {i + 1}: Name (SSID)"
					placeholder="Name (SSID)"
				/>
				<input
					bind:value={n.psk}
					type="password"
					maxlength="63"
					autocomplete="new-password"
					aria-label="WLAN {i + 1}: Passwort"
					placeholder="Passwort"
				/>
				<button class="btn-small" type="button" aria-label="WLAN {i + 1} entfernen" onclick={() => netze.splice(i, 1)}>✕</button>
			</div>
		{/each}
		{#if netze.length < WLAN_MAX}
			<button class="btn-small" type="button" onclick={() => netze.push({ ssid: '', psk: '' })}>+ WLAN</button>
		{/if}
		<p class="hint">
			Höchstens {WLAN_MAX} Netze, WPA2/WPA3 mit Passwort. Das Passwort geht <strong>nur aufs Gerät</strong> —
			nicht an diese Instanz, und das Gerät gibt es nicht wieder heraus.
		</p>
	</div>
{/snippet}

{#if fehler}
	<div class="error-bar" role="alert">{fehler} <button onclick={() => (fehler = '')} aria-label="Schließen">✕</button></div>
{/if}
{#if erfolg}
	<div class="success-bar" role="status">{erfolg}</div>
{/if}

<div class="section">
	<div class="section-header">
		<strong>Tracker</strong>
		<div class="kopf-knoepfe">
			<button class="btn-small" onclick={neuLaden} aria-label="Neu laden">↺</button>
			{#if !formular}
				<button class="btn-small primary" onclick={anlegen} disabled={laden}>+ Neuer Tracker</button>
			{/if}
		</div>
	</div>
	<p class="hint">
		Feste Ortungsgeräte im Fahrzeug. Ein Tracker ist mit <strong>einem</strong> Fahrzeug gekoppelt und
		sendet dessen Position von selbst — aber nur, solange das Fahrzeug in einem laufenden Konvoi
		eingeplant ist. Die Besatzung muss nichts tun. Einrichten: Tracker anlegen, Gerät per USB an den
		Rechner, <strong>Per USB einrichten</strong>.
	</p>
</div>

{#if neu}
	<div class="section code-box" data-testid="neuer-code">
		<div class="section-header"><strong>Einmal-Code für „{neu.name}"</strong></div>
		<p class="warnung">
			Der Code steht hier <strong>nur jetzt</strong> und gilt bis {uhrzeit(neu.code_expires_at)}. Gespeichert
			ist er nicht — wer ihn verliert, richtet den Tracker neu ein.
		</p>
		<pre class="code">{neu.code}</pre>
		<div class="knoepfe">
			<button class="btn-small" onclick={() => kopieren(neu!.code)}>{kopiert ? 'Kopiert ✓' : 'Kopieren'}</button>
			<button class="btn-small" onclick={() => (neu = null)}>Ich habe ihn eingegeben</button>
		</div>

		{#if takt && taktAktuell}
			<p class="hint" data-testid="takt-hinweis">
				In Fahrt sendet der Tracker alle <strong>{takt.buendel_s} s</strong>, geschätzt
				<strong>{taktAktuell.kb_pro_stunde} KB</strong> je Fahrstunde (bis {taktAktuell.kb_pro_stunde_ohne_keepalive} KB,
				wenn das Netz die Verbindung zwischendurch schließt). Den Takt und ein Rechenbeispiel für den
				SIM-Tarif gibt es unten unter <strong>Sendetakt</strong>.
			</p>
		{/if}

		<div class="usb" data-testid="usb-einrichten">
			{#if mitSerial}
				<p class="hint">
					Oder direkt von hier: Tracker per USB an diesen Rechner, dann <strong>Per USB einrichten</strong>.
					Der Tracker meldet sich danach selbst über WLAN oder Mobilfunk bei
					<code>{adresse}</code> an.
				</p>
				{#if !adresse.startsWith('https://')}
					<p class="warnung">
						Diese Seite läuft nicht über HTTPS. Ein Tracker meldet sich nur bei einer HTTPS-Adresse an.
					</p>
				{/if}
				<details>
					<summary>Eigene Zertifizierungsstelle</summary>
					<p class="hint">
						Nur nötig, wenn das Zertifikat dieser Instanz nicht von einer öffentlichen Stelle wie Let's Encrypt
						stammt. Das Wurzelzertifikat (PEM) hier einfügen, höchstens {WURZELN_MAX}.
					</p>
					<textarea
						bind:value={wurzelnText}
						rows="4"
						aria-label="Wurzelzertifikate"
						placeholder="-----BEGIN CERTIFICATE-----"
					></textarea>
					{#if wurzelnText.trim()}
						<p class="hint">{wurzeln.length} Zertifikat{wurzeln.length === 1 ? '' : 'e'} erkannt.</p>
					{/if}
				</details>
				<details>
					<summary>WLAN</summary>
					<p class="hint">
						Optional: Netze, über die der Tracker vor dem Mobilfunk sendet — das WLAN im Fahrzeug oder das der
						Wache. Kein Datenvolumen, und Updates kommen schneller.
					</p>
					{@render wlanFelder(wlanNeu, 'einrichten')}
				</details>
				<details data-testid="usb-mobilfunk">
					<summary>Mobilfunk (SIM)</summary>
					<p class="hint">
						Nur nötig, wenn die SIM nicht von 1NCE ist oder das Netz am Standort nur NB-IoT kann. Leer gelassen behält
						der Tracker seine bisherigen Einstellungen. Er übernimmt sie erst, wenn er sich damit bei dieser Instanz
						anmelden konnte — ein Tippfehler im APN lässt die alten stehen.
					</p>
					<div class="zeile">
						<label>
							APN
							<input
								bind:value={apn}
								maxlength="63"
								placeholder="iot.1nce.net"
								autocomplete="off"
								spellcheck="false"
								aria-invalid={apnFehler}
							/>
						</label>
						<label>
							Funknetz
							<select bind:value={funknetz}>
								<option value="">— unverändert —</option>
								{#each FUNKNETZE as n (n.wert)}
									<option value={n.wert}>{n.name}</option>
								{/each}
							</select>
						</label>
					</div>
					{#if apnFehler}
						<p class="usb-fehler">Nur Buchstaben, Ziffern, Punkt und Bindestrich, höchstens 63 Zeichen.</p>
					{/if}
				</details>
				<div class="knoepfe">
					<button class="btn-small primary" onclick={usbEinrichten} disabled={usb?.laeuft || apnFehler}>Per USB einrichten</button>
				</div>
				{#if usb}
					<p class={usb.fehler ? 'usb-fehler' : 'hint'} role={usb.fehler ? 'alert' : 'status'}>
						{#if usb.info}Gerät {usb.info.hardware_id}, Firmware {usb.info.firmware}{#if usb.info.apn}, APN {usb.info.apn} ({funknetzName(usb.info.funknetz)}){/if}{#if usb.info.instanz && usb.info.instanz !== adresse}, bisher eingerichtet für {usb.info.instanz}{/if}: {/if}{usb.text}
					</p>
				{/if}
			{:else}
				<p class="hint">
					Einrichten per USB direkt aus dieser Seite geht in Chrome oder Edge am Rechner. In diesem Browser: Code
					am Gerät eingeben, wie es beim Gerät beschrieben ist.
				</p>
			{/if}
		</div>
	</div>
{/if}

{#if formular}
	<form class="section formular" onsubmit={absenden} aria-label="Tracker">
		<div class="section-header">
			<strong>{formular.id ? 'Tracker bearbeiten' : 'Neuer Tracker'}</strong>
		</div>

		<label>
			Name
			<input bind:value={formular.name} required maxlength="120" placeholder="Tracker HLF 20" />
		</label>
		<div class="zeile">
			<label>
				Fahrzeug
				<select bind:value={formular.vehicle_id}>
					<option value="">— kein Fahrzeug, sendet nicht —</option>
					{#each freieFahrzeuge as f (f.id)}
						<option value={f.id}>{f.name}</option>
					{/each}
				</select>
			</label>
			<label>
				Update-Kanal
				<select bind:value={formular.kanal}>
					{#each KANAELE as k (k.wert)}
						<option value={k.wert}>{k.name}</option>
					{/each}
				</select>
			</label>
		</div>
		{#if formular.id}
			<label class="haken">
				<input type="checkbox" bind:checked={formular.aktiv} />
				<span>Freigegeben — gesperrt verliert das Gerät seinen Zugang sofort</span>
			</label>
		{/if}

		<div class="knoepfe">
			<button class="btn-primary" type="submit" disabled={speichern || !formular.name.trim()}>
				{speichern ? 'Speichert…' : formular.id ? 'Speichern' : 'Anlegen'}
			</button>
			<button class="btn-secondary" type="button" onclick={() => (formular = null)}>Abbrechen</button>
		</div>
	</form>
{/if}

{#if laden}
	<div class="section"><p class="hint">Lade…</p></div>
{:else if geraete.length === 0 && !formular}
	<div class="section"><p class="hint">Noch kein Tracker.</p></div>
{:else}
	{#each geraete as g (g.id)}
		{@const z = zustand(g)}
		<div class="section geraet" data-testid="tracker">
			<div class="section-header">
				<div>
					<strong>{g.name}</strong>
					<span class="marke" class:aus={z.klasse === 'aus'} class:warn={z.klasse === 'warn'}>{z.text}</span>
				</div>
				<div class="kopf-knoepfe">
					<button class="btn-small" onclick={() => bearbeiten(g)}>Bearbeiten</button>
					{#if mitSerial && g.eingerichtet}
						<button class="btn-small" onclick={() => wlanOeffnen(g)}>WLAN per USB</button>
					{/if}
					<button class="btn-small" onclick={() => neuEinrichten(g)}>Neu einrichten</button>
					<button class="btn-small danger" onclick={() => loeschen(g)}>Löschen</button>
				</div>
			</div>
			<p class="hint">
				{#if g.vehicle_name}Fahrzeug <strong>{g.vehicle_name}</strong>{:else}Kein Fahrzeug gekoppelt{/if}
				· Kanal {KANAELE.find((k) => k.wert === g.kanal)?.name ?? g.kanal}
				{#if g.firmware}· Firmware {g.firmware}{/if}
				{#if g.angebot_version}· <span class="angebot" title="Das Gerät holt sich das Update, sobald es steht und der Akku reicht.">Update {g.angebot_version} bereit</span>{/if}
			</p>
			{#if wlanAendern?.id === g.id}
				<div class="usb" data-testid="wlan-aendern">
					<p class="hint">
						Ersetzt die WLAN-Netze auf dem Gerät, ohne es neu einzurichten. Tracker per USB an diesen Rechner,
						Netze eintragen, dann <strong>Per USB übertragen</strong>. Ohne Eintrag werden alle gelöscht.
					</p>
					{@render wlanFelder(wlanAendern.netze, 'aendern')}
					<div class="knoepfe">
						<button class="btn-small primary" onclick={wlanSchreiben} disabled={wlanAendern.laeuft}>Per USB übertragen</button>
						<button class="btn-small" onclick={() => (wlanAendern = null)} disabled={wlanAendern.laeuft}>Abbrechen</button>
					</div>
					{#if wlanAendern.text}
						<p class={wlanAendern.fehler ? 'usb-fehler' : 'hint'} role={wlanAendern.fehler ? 'alert' : 'status'}>
							{wlanAendern.text}
						</p>
					{/if}
				</div>
			{/if}
			{#if g.eingerichtet}
				<p class="hint">
					<TrackerZustand zustand={g} /> ·
					{#if g.zuletzt_gesehen}Zuletzt gemeldet {uhrzeit(g.zuletzt_gesehen)}{:else}Noch nie gemeldet{/if}
					{#if g.extern === false && g.akku_seit}
						· <span class={akkuLange(g.akku_seit) ? 'akku-lange' : ''} title="Seit der ersten Meldung ohne Bordnetz, frühestens {uhrzeit(g.akku_seit)}">auf Akku {seit(g.akku_seit)}</span>
					{/if}
					{#if g.hardware_id}· Gerät {g.hardware_id}{/if}
					{#if g.wurzeln_aktuell === false}
						· <span class="wurzeln-alt" title="Die Instanz verteilt neue Wurzelzertifikate. Das Gerät übernimmt sie beim nächsten Kontakt, sobald eine Verbindung damit gelingt.">Zertifikate noch nicht übernommen</span>
					{/if}
				</p>
				{#if g.update_version}
					<p class="hint">
						Letztes Update {g.update_version}: {ERGEBNIS[g.update_ergebnis ?? ''] ?? g.update_ergebnis}{#if g.update_meldung}&nbsp;— {g.update_meldung}{/if}{#if g.update_at}, {uhrzeit(g.update_at)}{/if}
					</p>
				{/if}
			{/if}
		</div>
	{/each}
{/if}

{#if takt}
	<div class="section formular" data-testid="sendetakt">
		<div class="section-header"><strong>Sendetakt</strong></div>
		<p class="hint">
			Wie oft die Tracker <strong>während der Fahrt</strong> ihre Position senden. Öfter heißt: Die Karte ist
			aktueller, aber Datenvolumen und Strom steigen. Die Position messen die Tracker davon unabhängig alle
			{takt.intervall_s} s; jeder Versand bringt alle Messungen seit dem letzten mit, der Verlauf bleibt also
			gleich dicht. Gilt für alle Tracker dieser Organisation, ab ihrem nächsten Kontakt.
		</p>

		<div class="takt-rahmen">
		<table class="takt">
			<thead>
				<tr>
					<th></th>
					<th>Senden alle</th>
					<th>Sprung auf der Karte bei 50 km/h</th>
					<th>je Tracker und Fahrstunde</th>
					<th>{anzahl} Tracker, {fahrstunden} Fahrstunden im Monat</th>
				</tr>
			</thead>
			<tbody>
				{#each takt.wahl as w (w.buendel_s)}
					<tr class:gewaehlt={w.buendel_s === taktGewaehlt}>
						<td>
							<input
								type="radio"
								name="buendel"
								value={w.buendel_s}
								bind:group={taktGewaehlt}
								aria-label="alle {w.buendel_s} s"
							/>
						</td>
						<td>
							{w.buendel_s} s{#if w.buendel_s === takt.standard_s}&nbsp;<span class="marke aus">Standard</span>{/if}
						</td>
						<td>ca. {sprungM(w.buendel_s)} m</td>
						<td>ca. {w.kb_pro_stunde} KB <span class="leise">(bis {w.kb_pro_stunde_ohne_keepalive} KB)</span></td>
						<td>ca. {mbImMonat(w.kb_pro_stunde)} MB <span class="leise">(bis {mbImMonat(w.kb_pro_stunde_ohne_keepalive)} MB)</span></td>
					</tr>
				{/each}
			</tbody>
		</table>
		</div>

		<div class="zeile">
			<label>
				Tracker
				<input type="number" min="1" max="999" bind:value={anzahl} />
			</label>
			<label>
				Fahrstunden je Tracker im Monat
				<input type="number" min="0" max="744" bind:value={fahrstunden} />
			</label>
		</div>
		<p class="hint">
			Rechenbeispiel, keine Messung. Gezählt ist nur die Fahrt in einem laufenden Konvoi. Steht das Fahrzeug,
			misst der Tracker einmal pro Minute; ohne laufenden Konvoi meldet er sich nur alle 12 Stunden mit einem
			Lebenszeichen. Beides fällt kaum ins Gewicht. Der höhere Wert gilt, wenn das Mobilfunknetz die
			Verbindung zwischen zwei Versänden schließt und jeder Versand neu verbinden muss. Wer knapp
			kalkuliert, plant mit dem höheren Wert.
		</p>

		<div class="knoepfe">
			<button class="btn-primary" type="button" onclick={taktSichern} disabled={taktSpeichern || taktGewaehlt === takt.buendel_s}>
				{taktSpeichern ? 'Speichert…' : 'Sendetakt speichern'}
			</button>
		</div>
	</div>
{/if}

<style>
	.takt-rahmen { overflow-x: auto; max-width: 100%; }
	.takt { border-collapse: collapse; font-size: var(--text-sm); color: var(--text-1); width: 100%; max-width: 48rem; }
	.takt th, .takt td { text-align: left; padding: .3rem .5rem; border-bottom: 1px solid var(--border); }
	.takt th { font-weight: 600; color: var(--text-2); font-size: var(--text-xs); }
	.takt tr.gewaehlt td { background: var(--surface-2); }
	.leise { color: var(--text-muted); font-size: var(--text-xs); }
	.section { background: var(--surface-1); border: 1px solid var(--border); border-radius: 8px; padding: 1rem; margin-bottom: 1rem; box-shadow: var(--shadow); }
	.section-header { display: flex; justify-content: space-between; align-items: center; gap: .5rem; flex-wrap: wrap; margin-bottom: .75rem; font-size: var(--text-sm); font-weight: 500; color: var(--text-1); }
	.kopf-knoepfe, .knoepfe { display: flex; gap: .4rem; flex-wrap: wrap; }
	.knoepfe { margin-top: .75rem; }
	.hint { color: var(--text-muted); font-size: var(--text-sm); margin: .25rem 0; }
	.error-bar { background: var(--color-primary-hover); color: white; padding: .4rem .75rem; border-radius: 4px; margin-bottom: 1rem; display: flex; justify-content: space-between; }
	.error-bar button { background: none; border: none; color: white; cursor: pointer; }
	.success-bar { background: rgba(107,127,77,.15); border: 1px solid rgba(107,127,77,.4); color: #a8c070; padding: .4rem .75rem; border-radius: 4px; margin-bottom: 1rem; font-size: var(--text-sm); }
	.btn-small { padding: .2rem .5rem; font-size: var(--text-xs); border-radius: 3px; border: 1px solid var(--border); background: var(--surface-2); color: var(--text-2); cursor: pointer; }
	.btn-small:hover { background: var(--surface-1); }
	.btn-small:disabled { opacity: .5; cursor: not-allowed; }
	.btn-small.danger { border-color: var(--color-primary); color: var(--color-primary); }
	.btn-small.primary { background: #2563eb; color: #fff; border-color: #2563eb; }
	.btn-primary { padding: .5rem 1rem; background: var(--color-primary); color: white; border: none; border-radius: 6px; font-weight: 600; cursor: pointer; font-size: var(--text-sm); }
	.btn-primary:disabled { opacity: .5; cursor: not-allowed; }
	.btn-primary:hover:not(:disabled) { background: var(--color-primary-hover); }
	.btn-secondary { padding: .5rem 1rem; background: transparent; color: var(--text-2); border: 1px solid var(--border); border-radius: 6px; font-weight: 600; cursor: pointer; font-size: var(--text-sm); }
	.btn-secondary:hover { background: var(--surface-2); }

	.formular { display: flex; flex-direction: column; gap: .75rem; }
	.formular label { display: flex; flex-direction: column; gap: .3rem; font-size: var(--text-sm); font-weight: 600; color: var(--text-2); max-width: var(--admin-field, 34rem); }
	.formular input:not([type='checkbox']), .formular select { padding: .5rem .75rem; border: 1px solid var(--border); border-radius: 6px; background: var(--surface-2); color: var(--text-1); font-size: var(--text-sm); font-weight: 400; }
	.formular input:focus, .formular select:focus { outline: none; border-color: var(--color-primary); }
	.zeile { display: flex; gap: .75rem; flex-wrap: wrap; }
	.zeile label { flex: 1 1 10rem; }
	.formular label.haken { flex-direction: row; align-items: center; gap: .5rem; font-weight: 400; max-width: none; }

	.code-box { border-color: #d4a017; }
	.usb { margin-top: 1rem; border-top: 1px solid var(--border); padding-top: .75rem; }
	.usb textarea { width: 100%; max-width: var(--admin-field, 34rem); font-family: monospace; font-size: var(--text-xs); background: var(--surface-2); color: var(--text-1); border: 1px solid var(--border); border-radius: 6px; padding: .4rem; }
	.usb .zeile { max-width: var(--admin-field, 34rem); margin-top: .4rem; }
	.usb label { display: flex; flex-direction: column; gap: .3rem; font-size: var(--text-sm); font-weight: 600; color: var(--text-2); }
	.usb input, .usb select { padding: .4rem .6rem; border: 1px solid var(--border); border-radius: 6px; background: var(--surface-2); color: var(--text-1); font-size: var(--text-sm); font-weight: 400; }
	.usb input[aria-invalid='true'] { border-color: var(--color-primary); }
	.wlan { display: flex; flex-direction: column; gap: .4rem; align-items: flex-start; }
	.wlan-zeile { display: flex; gap: .4rem; flex-wrap: wrap; width: 100%; max-width: var(--admin-field, 34rem); }
	.wlan-zeile input { flex: 1 1 9rem; min-width: 0; padding: .35rem .5rem; border: 1px solid var(--border); border-radius: 6px; background: var(--surface-2); color: var(--text-1); font-size: var(--text-sm); }
	.usb summary { cursor: pointer; font-size: var(--text-sm); color: var(--text-2); margin: .25rem 0; }
	.usb-fehler { color: var(--color-primary); font-size: var(--text-sm); margin: .5rem 0 0; }
	.warnung { background: rgba(212,160,23,.12); border: 1px solid rgba(212,160,23,.45); color: var(--text-1); padding: .4rem .6rem; border-radius: 4px; font-size: var(--text-sm); }
	.code { background: var(--surface-2); border: 1px solid var(--border); border-radius: 6px; padding: .6rem .75rem; font-size: 1.6rem; letter-spacing: .15em; font-weight: 700; color: var(--text-1); user-select: all; margin: .5rem 0 0; }

	.marke { margin-left: .5rem; font-size: var(--text-xs); padding: .1rem .45rem; border-radius: 999px; background: #2e7d32; color: #fff; font-weight: 600; }
	.marke.aus { background: var(--surface-2); color: var(--text-muted); border: 1px solid var(--border); }
	.marke.warn { background: #d4a017; color: #1a1a1a; }
	.angebot { color: #1f6f8b; font-weight: 600; }
	.akku-lange { color: #b26a00; font-weight: 600; }
	.wurzeln-alt { color: #b26a00; }
</style>
