<script lang="ts">
	/**
	 * Öffentliche Aktionsseiten im Org-Admin: anlegen, ändern, Token erneuern,
	 * löschen, Vorschau.
	 *
	 * Die Seite selbst liefert der EventTracker aus (eigenes Repo). Er holt den
	 * Stand mit dem Abruf-Token ab — das Token steht hier **einmal**, direkt nach
	 * Anlegen oder Erneuern, zusammen mit dem fertigen Eintrag für dessen
	 * Konfiguration. Gespeichert ist nur der Hash; wer es verliert, erneuert es.
	 *
	 * Verzögerung, Vergröberung und die Liste der freigegebenen Felder regelt
	 * der Server (`services/aktionsseite.py`). Die Vorschau zeigt deshalb genau
	 * das, was hinausgeht — mit derselben Verzögerung.
	 */
	import { onMount } from 'svelte';
	import {
		aktionsseitenApi,
		convoysApi,
		type Aktionsseite,
		type AktionsseiteDaten,
		type AktionsseiteMitToken,
		type AktionsseiteVorschau,
		type AktionsseitenThema
	} from '$lib/api';

	const VERZOEGERUNGEN = [60, 90, 120, 180, 240, 360];
	const STATUS: Record<string, string> = {
		vor_abfahrt: 'noch nicht losgefahren',
		unterwegs: 'unterwegs',
		pause: 'Pause (Ort vergröbert)',
		angekommen: 'angekommen'
	};

	interface KonvoiWahl {
		gewaehlt: boolean;
		display_name: string;
		destination_label: string;
		color: string;
	}

	interface Formular {
		id: string | null;
		title: string;
		subtitle: string;
		facts: string;
		theme: AktionsseitenThema;
		delay_minutes: number;
		show_destination: boolean;
		valid_until: string;
		enabled: boolean;
		konvois: Record<string, KonvoiWahl>;
	}

	let seiten = $state<Aktionsseite[]>([]);
	let konvois = $state<{ id: string; name: string }[]>([]);
	let laden = $state(true);
	let fehler = $state('');
	let erfolg = $state('');
	let formular = $state<Formular | null>(null);
	let speichern = $state(false);
	let neu = $state<AktionsseiteMitToken | null>(null);
	let vorschau = $state<{ id: string; daten: AktionsseiteVorschau } | null>(null);
	let kopiert = $state(false);

	async function neuLaden() {
		laden = true;
		fehler = '';
		try {
			const [s, k] = await Promise.all([aktionsseitenApi.list(), convoysApi.list()]);
			seiten = s;
			konvois = k.map((c) => ({ id: c.id, name: c.name }));
		} catch (e) {
			fehler = e instanceof Error ? e.message : 'Laden fehlgeschlagen';
		} finally {
			laden = false;
		}
	}

	onMount(neuLaden);

	function leereWahl(): Record<string, KonvoiWahl> {
		return Object.fromEntries(
			konvois.map((k) => [k.id, { gewaehlt: false, display_name: '', destination_label: '', color: '' }])
		);
	}

	function zuLokal(iso: string | null): string {
		if (!iso) return '';
		const d = new Date(iso);
		const p = (n: number) => String(n).padStart(2, '0');
		return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}T${p(d.getHours())}:${p(d.getMinutes())}`;
	}

	function anlegen() {
		neu = null;
		formular = {
			id: null,
			title: '',
			subtitle: '',
			facts: '',
			theme: 'neutral',
			delay_minutes: 120,
			show_destination: false,
			valid_until: '',
			enabled: true,
			konvois: leereWahl()
		};
	}

	function bearbeiten(s: Aktionsseite) {
		neu = null;
		const wahl = leereWahl();
		for (const k of s.convoys) {
			wahl[k.convoy_id] = {
				gewaehlt: true,
				display_name: k.display_name,
				destination_label: k.destination_label ?? '',
				color: k.color ?? ''
			};
		}
		formular = {
			id: s.id,
			title: s.title,
			subtitle: s.subtitle ?? '',
			facts: s.facts ?? '',
			theme: s.theme,
			delay_minutes: s.delay_minutes,
			show_destination: s.show_destination,
			valid_until: zuLokal(s.valid_until),
			enabled: s.enabled,
			konvois: wahl
		};
	}

	const gewaehlte = $derived(
		formular ? konvois.filter((k) => formular!.konvois[k.id]?.gewaehlt) : []
	);
	const fehlenNamen = $derived(
		formular ? gewaehlte.some((k) => !formular!.konvois[k.id].display_name.trim()) : false
	);

	function daten(f: Formular): AktionsseiteDaten {
		const leer = (s: string) => (s.trim() ? s.trim() : null);
		return {
			title: f.title.trim(),
			subtitle: leer(f.subtitle),
			facts: leer(f.facts),
			theme: f.theme,
			delay_minutes: f.delay_minutes,
			show_destination: f.show_destination,
			valid_until: f.valid_until ? new Date(f.valid_until).toISOString() : null,
			enabled: f.enabled,
			convoys: gewaehlte.map((k) => {
				const w = f.konvois[k.id];
				return {
					convoy_id: k.id,
					display_name: w.display_name.trim(),
					destination_label: leer(w.destination_label),
					color: /^#[0-9a-fA-F]{6}$/.test(w.color) ? w.color : null
				};
			})
		};
	}

	async function absenden(e: SubmitEvent) {
		e.preventDefault();
		if (!formular || speichern) return;
		speichern = true;
		fehler = '';
		try {
			if (formular.id) {
				await aktionsseitenApi.update(formular.id, daten(formular));
				erfolg = 'Gespeichert.';
			} else {
				neu = await aktionsseitenApi.create(daten(formular));
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

	async function tokenErneuern(s: Aktionsseite) {
		if (
			!confirm(
				`Neues Abruf-Token für „${s.title}"?\n\nDas bisherige gilt sofort nicht mehr — der EventTracker zeigt die Seite erst wieder, wenn dort das neue eingetragen ist.`
			)
		)
			return;
		try {
			neu = await aktionsseitenApi.rotateToken(s.id);
			formular = null;
			erfolg = '';
		} catch (err) {
			fehler = err instanceof Error ? err.message : 'Erneuern fehlgeschlagen';
		}
	}

	async function loeschen(s: Aktionsseite) {
		if (!confirm(`Aktionsseite „${s.title}" löschen?\n\nDie öffentliche Seite zeigt danach nichts mehr.`)) return;
		try {
			await aktionsseitenApi.delete(s.id);
			if (neu?.id === s.id) neu = null;
			erfolg = 'Gelöscht.';
			await neuLaden();
		} catch (err) {
			fehler = err instanceof Error ? err.message : 'Löschen fehlgeschlagen';
		}
	}

	async function zeigeVorschau(s: Aktionsseite) {
		if (vorschau?.id === s.id) {
			vorschau = null;
			return;
		}
		try {
			vorschau = { id: s.id, daten: await aktionsseitenApi.preview(s.id) };
		} catch (err) {
			fehler = err instanceof Error ? err.message : 'Vorschau fehlgeschlagen';
		}
	}

	/** Pfad-Vorschlag für den EventTracker aus dem Titel. */
	function pfadVorschlag(titel: string): string {
		const p = titel
			.toLowerCase()
			.replace(/ä/g, 'ae')
			.replace(/ö/g, 'oe')
			.replace(/ü/g, 'ue')
			.replace(/ß/g, 'ss')
			.replace(/[^a-z0-9]+/g, '-')
			.replace(/^-+|-+$/g, '')
			.slice(0, 48);
		return p.length >= 3 ? p : 'aktion';
	}

	// Die Instanz steht mit im Eintrag: Der EventTracker nimmt sie von dort,
	// wenn CONVOYPLAN_URL fehlt — ein Eintrag, einmal kopieren.
	const instanz = $derived(neu ? new URL(neu.endpoint).origin : '');
	const eintrag = $derived(
		neu
			? JSON.stringify({
					pfad: pfadVorschlag(neu.title),
					slug: neu.slug,
					token: neu.fetch_token,
					convoyplan: instanz
				})
			: ''
	);

	async function kopieren() {
		try {
			await navigator.clipboard.writeText(eintrag);
			kopiert = true;
			setTimeout(() => (kopiert = false), 2000);
		} catch {
			/* Zwischenablage nicht erlaubt — der Text steht zum Markieren da */
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
</script>

{#if fehler}
	<div class="error-bar" role="alert">{fehler} <button onclick={() => (fehler = '')} aria-label="Schließen">✕</button></div>
{/if}
{#if erfolg}
	<div class="success-bar" role="status">{erfolg}</div>
{/if}

<div class="section">
	<div class="section-header">
		<strong>Öffentliche Aktionsseiten</strong>
		<div class="kopf-knoepfe">
			<button class="btn-small" onclick={neuLaden} aria-label="Neu laden">↺</button>
			{#if !formular}
				<button class="btn-small primary" onclick={anlegen} disabled={laden}>+ Neue Aktionsseite</button>
			{/if}
		</div>
	</div>
	<p class="hint">
		Konvois öffentlich zeigen — zum Teilen, für die Presse, auf einem Bildschirm. Was hinausgeht, ist
		<strong>mindestens eine Stunde verzögert</strong>, steht ein Konvoi, nur auf etwa zehn Kilometer
		genau, und enthält weder Fahrzeuge noch Rufnamen, Stärken oder interne Namen. Ausgeliefert wird
		die Seite vom EventTracker, nicht von dieser Instanz.
	</p>
</div>

{#if neu}
	<div class="section token-box" data-testid="neues-token">
		<div class="section-header"><strong>Abruf-Token für „{neu.title}"</strong></div>
		<p class="warnung">
			Das Token steht hier <strong>nur jetzt</strong>. Gespeichert ist es nicht — wer es verliert,
			erneuert es.
		</p>
		<p class="hint">
			Eintrag für den EventTracker — beim Installer einfügen oder als <code>EVENTS</code> eintragen.
			<code>pfad</code> ist die öffentliche Adresse und darf angepasst werden, <code>convoyplan</code>
			ist diese Instanz ({instanz}):
		</p>
		<pre class="eintrag">{eintrag}</pre>
		<div class="knoepfe">
			<button class="btn-small" onclick={kopieren}>{kopiert ? 'Kopiert ✓' : 'Kopieren'}</button>
			<button class="btn-small" onclick={() => (neu = null)}>Ich habe es übernommen</button>
		</div>
	</div>
{/if}

{#if formular}
	<form class="section formular" onsubmit={absenden} aria-label="Aktionsseite">
		<div class="section-header">
			<strong>{formular.id ? 'Aktionsseite bearbeiten' : 'Neue Aktionsseite'}</strong>
		</div>

		<label>
			Titel
			<input bind:value={formular.title} required maxlength="120" placeholder="Weihnachtskonvois 2026" />
		</label>
		<label>
			Untertitel <span class="optional">optional</span>
			<input bind:value={formular.subtitle} maxlength="300" placeholder="Päckchen auf dem Weg nach Südosteuropa" />
		</label>
		<label>
			Fakten <span class="optional">optional, Freitext</span>
			<input bind:value={formular.facts} maxlength="2000" placeholder="3 Konvois · 36 Lkw" />
		</label>

		<div class="zeile">
			<label>
				Verzögerung
				<select bind:value={formular.delay_minutes}>
					{#each VERZOEGERUNGEN as m (m)}
						<option value={m}>{m % 60 === 0 ? `${m / 60} Std.` : `${m} Min.`}</option>
					{/each}
				</select>
			</label>
			<label>
				Gestaltung
				<select bind:value={formular.theme}>
					<option value="neutral">Neutral</option>
					<option value="weihnachten">Weihnachten</option>
				</select>
			</label>
			<label>
				Sichtbar bis <span class="optional">optional</span>
				<input type="datetime-local" bind:value={formular.valid_until} />
			</label>
		</div>

		<label class="haken">
			<input type="checkbox" bind:checked={formular.show_destination} />
			<span>Zielort als Punkt auf der Karte zeigen (vergröbert) — sonst nur als Text</span>
		</label>
		<label class="haken">
			<input type="checkbox" bind:checked={formular.enabled} />
			<span>Eingeschaltet — ausgeschaltet zeigt die öffentliche Seite nichts</span>
		</label>

		<fieldset>
			<legend>Konvois</legend>
			<p class="hint">
				Der öffentliche Name ersetzt den internen — „Konvoi Bosnien" statt „KV 3 / Los B".
				Aufgezeichnet wird nur, solange ein Konvoi an einer eingeschalteten Seite hängt.
			</p>
			{#if konvois.length === 0}
				<p class="hint">Diese Organisation hat noch keine Konvois.</p>
			{/if}
			{#each konvois.filter((k) => formular?.konvois[k.id]) as k (k.id)}
				<div class="konvoi" class:gewaehlt={formular.konvois[k.id].gewaehlt}>
					<label class="haken">
						<input type="checkbox" bind:checked={formular.konvois[k.id].gewaehlt} />
						<span>{k.name}</span>
					</label>
					{#if formular.konvois[k.id].gewaehlt}
						<div class="konvoi-felder">
							<label>
								Öffentlicher Name
								<input bind:value={formular.konvois[k.id].display_name} required maxlength="100" placeholder="Konvoi Bosnien" />
							</label>
							<label>
								Ziel <span class="optional">optional</span>
								<input bind:value={formular.konvois[k.id].destination_label} maxlength="100" placeholder="Tuzla" />
							</label>
							<label class="farbe">
								Farbe
								<input type="color" value={formular.konvois[k.id].color || '#f4c542'} oninput={(e) => { if (formular) formular.konvois[k.id].color = e.currentTarget.value; }} />
							</label>
						</div>
					{/if}
				</div>
			{/each}
		</fieldset>

		<div class="knoepfe">
			<button class="btn-primary" type="submit" disabled={speichern || !formular.title.trim() || fehlenNamen}>
				{speichern ? 'Speichert…' : formular.id ? 'Speichern' : 'Anlegen'}
			</button>
			<button class="btn-secondary" type="button" onclick={() => (formular = null)}>Abbrechen</button>
		</div>
	</form>
{/if}

{#if laden}
	<div class="section"><p class="hint">Lade…</p></div>
{:else if seiten.length === 0 && !formular}
	<div class="section"><p class="hint">Noch keine Aktionsseite.</p></div>
{:else}
	{#each seiten as s (s.id)}
		<div class="section seite" data-testid="aktionsseite">
			<div class="section-header">
				<div>
					<strong>{s.title}</strong>
					<span class="marke" class:aus={!s.active}>{s.active ? 'aktiv' : s.enabled ? 'abgelaufen' : 'aus'}</span>
				</div>
				<div class="kopf-knoepfe">
					<button class="btn-small" onclick={() => zeigeVorschau(s)}>{vorschau?.id === s.id ? 'Vorschau schließen' : 'Vorschau'}</button>
					<button class="btn-small" onclick={() => bearbeiten(s)}>Bearbeiten</button>
					<button class="btn-small" onclick={() => tokenErneuern(s)}>Token erneuern</button>
					<button class="btn-small danger" onclick={() => loeschen(s)}>Löschen</button>
				</div>
			</div>
			<p class="hint">
				{s.delay_minutes / 60 >= 1 && s.delay_minutes % 60 === 0
					? `${s.delay_minutes / 60} Std.`
					: `${s.delay_minutes} Min.`} verzögert
				· {s.theme === 'weihnachten' ? 'Weihnachten' : 'Neutral'}
				{#if s.valid_until}· sichtbar bis {uhrzeit(s.valid_until)}{/if}
			</p>
			<ul class="konvoi-liste">
				{#each s.convoys as k (k.convoy_id)}
					<li>
						<span class="punkt" style:background={k.color ?? '#999'}></span>
						<strong>{k.display_name}</strong>
						{#if k.destination_label}→ {k.destination_label}{/if}
						<span class="intern">({k.convoy_name})</span>
					</li>
				{:else}
					<li class="hint">Noch keine Konvois zugeordnet.</li>
				{/each}
			</ul>
			<p class="hint endpunkt">Abruf: <code>{s.endpoint}</code></p>

			{#if vorschau?.id === s.id}
				<div class="vorschau" data-testid="vorschau">
					<p>
						<strong>So sieht es die Öffentlichkeit gerade:</strong> Stand {uhrzeit(vorschau.daten.as_of)}
						({vorschau.daten.delay_minutes} Min. verzögert)
					</p>
					<ul>
						{#each vorschau.daten.convoys as k (k.key)}
							<li>
								<strong>{k.name}</strong>: {STATUS[k.status] ?? k.status}
								{#if k.position}
									— {k.position.lat.toFixed(3)}, {k.position.lon.toFixed(3)}{#if k.position.coarse}&nbsp;<em>(vergröbert)</em>{/if}, gemeldet {uhrzeit(k.position.at)}
								{/if}
								{#if k.driven_km > 0}· {Math.round(k.driven_km)} km gefahren{/if}
							</li>
						{/each}
					</ul>
				</div>
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
	.formular input:not([type='checkbox']):not([type='color']), .formular select { padding: .5rem .75rem; border: 1px solid var(--border); border-radius: 6px; background: var(--surface-2); color: var(--text-1); font-size: var(--text-sm); font-weight: 400; }
	.formular input:focus, .formular select:focus { outline: none; border-color: var(--color-primary); }
	.optional { font-weight: 400; color: var(--text-muted); font-size: var(--text-xs); }
	.zeile { display: flex; gap: .75rem; flex-wrap: wrap; }
	.zeile label { flex: 1 1 10rem; }
	.formular label.haken { flex-direction: row; align-items: center; gap: .5rem; font-weight: 400; max-width: none; }
	fieldset { border: 1px solid var(--border); border-radius: 6px; padding: .5rem .75rem .75rem; margin: 0; }
	legend { font-size: var(--text-sm); font-weight: 600; color: var(--text-2); padding: 0 .25rem; }
	.konvoi { padding: .4rem 0; border-top: 1px solid var(--border); }
	.konvoi:first-of-type { border-top: none; }
	.konvoi-felder { display: flex; gap: .5rem; flex-wrap: wrap; margin: .4rem 0 0 1.6rem; }
	.konvoi-felder label { flex: 1 1 10rem; }
	.konvoi-felder label.farbe { flex: 0 0 auto; }
	.konvoi-felder input[type='color'] { width: 3rem; height: 2.1rem; padding: 0; border: 1px solid var(--border); border-radius: 6px; background: none; }

	.token-box { border-color: #d4a017; }
	.warnung { background: rgba(212,160,23,.12); border: 1px solid rgba(212,160,23,.45); color: var(--text-1); padding: .4rem .6rem; border-radius: 4px; font-size: var(--text-sm); }
	.eintrag { background: var(--surface-2); border: 1px solid var(--border); border-radius: 6px; padding: .5rem .75rem; font-size: var(--text-xs); white-space: pre-wrap; word-break: break-all; color: var(--text-1); user-select: all; }
	code { font-size: var(--text-xs); word-break: break-all; }

	.marke { margin-left: .5rem; font-size: var(--text-xs); padding: .1rem .45rem; border-radius: 999px; background: #2e7d32; color: #fff; font-weight: 600; }
	.marke.aus { background: var(--surface-2); color: var(--text-muted); border: 1px solid var(--border); }
	.konvoi-liste { list-style: none; margin: .5rem 0; padding: 0; font-size: var(--text-sm); color: var(--text-1); }
	.konvoi-liste li { display: flex; align-items: center; gap: .4rem; padding: .15rem 0; flex-wrap: wrap; }
	.punkt { width: .6rem; height: .6rem; border-radius: 50%; display: inline-block; }
	.intern { color: var(--text-muted); font-size: var(--text-xs); }
	.endpunkt { margin-top: .5rem; }
	.vorschau { margin-top: .75rem; background: var(--surface-2); border: 1px solid var(--border); border-radius: 6px; padding: .5rem .75rem; font-size: var(--text-sm); color: var(--text-1); }
	.vorschau ul { margin: .25rem 0 0; padding-left: 1.1rem; }
</style>
