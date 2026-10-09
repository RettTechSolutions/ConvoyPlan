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
	 * Seite schreibt Adresse, Code und optional eigene Wurzelzertifikate aufs Gerät, das
	 * Gerät löst den Code selbst über sein Mobilfunknetz ein. Der Browser sieht dabei nie
	 * ein Token.
	 */
	import { onMount } from 'svelte';
	import { geraeteApi, vehiclesApi, type Tracker, type TrackerDaten, type TrackerKanal, type TrackerMitCode } from '$lib/api';
	import {
		SCHRITTTEXT,
		TrackerUsb,
		WURZELN_MAX,
		instanzAdresse,
		webSerialVerfuegbar,
		wurzelnLesen,
		type GeraeteInfo
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
	let mitSerial = $state(false);
	let adresse = $state('');

	async function neuLaden() {
		laden = true;
		fehler = '';
		try {
			const [g, f] = await Promise.all([geraeteApi.list(), vehiclesApi.list()]);
			geraete = g;
			fahrzeuge = f.map((v) => ({ id: v.id, name: v.callsign ? `${v.name} (${v.callsign})` : v.name }));
		} catch (e) {
			fehler = e instanceof Error ? e.message : 'Laden fehlgeschlagen';
		} finally {
			laden = false;
		}
	}

	onMount(() => {
		mitSerial = webSerialVerfuegbar();
		adresse = instanzAdresse();
		neuLaden();
	});

	const wurzeln = $derived(wurzelnLesen(wurzelnText));

	async function usbEinrichten() {
		if (!neu || usb?.laeuft) return;
		const { code, name } = neu;
		if (wurzeln.length > WURZELN_MAX) {
			usb = { laeuft: false, fehler: true, info: null, text: `Höchstens ${WURZELN_MAX} Wurzelzertifikate.` };
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
			await geraet.einrichten(adresse, code, wurzeln, (s) => {
				if (usb) usb.text = SCHRITTTEXT[s];
			});
			usb = null;
			neu = null;
			wurzelnText = '';
			erfolg = `„${name}" ist eingerichtet — Gerät ${info.hardware_id}, Firmware ${info.firmware}.`;
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
		return { text: 'bereit', klasse: '' };
	}
</script>

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

		<div class="usb" data-testid="usb-einrichten">
			{#if mitSerial}
				<p class="hint">
					Oder direkt von hier: Tracker per USB an diesen Rechner, dann <strong>Per USB einrichten</strong>.
					Der Tracker meldet sich danach selbst über sein Mobilfunknetz bei
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
				<div class="knoepfe">
					<button class="btn-small primary" onclick={usbEinrichten} disabled={usb?.laeuft}>Per USB einrichten</button>
				</div>
				{#if usb}
					<p class={usb.fehler ? 'usb-fehler' : 'hint'} role={usb.fehler ? 'alert' : 'status'}>
						{#if usb.info}Gerät {usb.info.hardware_id}, Firmware {usb.info.firmware}{#if usb.info.instanz && usb.info.instanz !== adresse}, bisher eingerichtet für {usb.info.instanz}{/if}: {/if}{usb.text}
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
			{#if g.eingerichtet}
				<p class="hint">
					{#if g.zuletzt_gesehen}Zuletzt gemeldet {uhrzeit(g.zuletzt_gesehen)}{:else}Noch nie gemeldet{/if}
					{#if g.akku_prozent !== null}· Akku {g.akku_prozent} %{#if g.extern}&nbsp;(an Bordnetz){/if}{/if}
					{#if g.signal_dbm !== null}· Signal {g.signal_dbm} dBm{/if}
					{#if g.hardware_id}· Gerät {g.hardware_id}{/if}
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

<style>
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
	.usb summary { cursor: pointer; font-size: var(--text-sm); color: var(--text-2); margin: .25rem 0; }
	.usb-fehler { color: var(--color-primary); font-size: var(--text-sm); margin: .5rem 0 0; }
	.warnung { background: rgba(212,160,23,.12); border: 1px solid rgba(212,160,23,.45); color: var(--text-1); padding: .4rem .6rem; border-radius: 4px; font-size: var(--text-sm); }
	.code { background: var(--surface-2); border: 1px solid var(--border); border-radius: 6px; padding: .6rem .75rem; font-size: 1.6rem; letter-spacing: .15em; font-weight: 700; color: var(--text-1); user-select: all; margin: .5rem 0 0; }

	.marke { margin-left: .5rem; font-size: var(--text-xs); padding: .1rem .45rem; border-radius: 999px; background: #2e7d32; color: #fff; font-weight: 600; }
	.marke.aus { background: var(--surface-2); color: var(--text-muted); border: 1px solid var(--border); }
	.marke.warn { background: #d4a017; color: #1a1a1a; }
	.angebot { color: #1f6f8b; font-weight: 600; }
</style>
