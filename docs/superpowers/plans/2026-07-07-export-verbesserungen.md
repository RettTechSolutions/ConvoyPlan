# Export-Verbesserungen (Marschbefehl-PDF, GPX, JSON) — Review & Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Die drei Export-Funktionen (Marschbefehl-PDF, GPX, JSON) korrekt, vollständig und einsatztauglich machen: Zeitzonen-Fehler beheben, Datenverlust durch harte Textkürzung beseitigen, fehlende Inhalte (Marschzeiten, Betriebsstoff-Analyse) ergänzen, GPX/JSON-Exporte navigationsgeräte- bzw. backup-tauglich machen — und das Ganze erstmals mit Tests absichern.

**Architecture:** Alle Änderungen bleiben in den bestehenden Service-Modulen (`backend/app/services/pdf.py`, `export.py`) und dem Routing-Router. Zeitzonen-Behandlung wird zentral über eine neue Config-Option `display_timezone` (Default `Europe/Berlin`, via `zoneinfo`) gelöst. Kein neues Modell, eine kleine Ergänzung im Frontend-Modal.

**Tech Stack:** Python/FastAPI, fpdf2, gpxpy, zoneinfo, Svelte 5 runes

---

## Teil 1 — Befund (Review)

### Ist-Zustand

| Export | Endpoint | Service | Frontend |
|---|---|---|---|
| Marschbefehl-PDF | `GET /convoys/{id}/export/pdf` (`routing.py:493`) | `pdf.generate_marschbefehl` | Export-Tab → Modal „Marschbefehl“ → „Speichern & PDF“ |
| GPX | `GET /convoys/{id}/export/gpx` (`routing.py:438`) | `export.build_gpx` | Export-Tab, Button |
| JSON | `GET /convoys/{id}/export/json` (`routing.py:465`) | `export.build_json_export` | Export-Tab, Button |

Testabdeckung: **keine** — es gibt weder `test_export.py` noch `test_pdf.py` (nur `test_import.py` für die Gegenrichtung).

### Fehler (Korrektheit)

**F1 — Zeitzonen: Alle Uhrzeiten im PDF sind UTC statt lokal.**
`_fmt_time` / `_fmt_time_short` (`pdf.py:97–112`) parsen TZ-aware ISO-Strings, formatieren aber ohne Umrechnung — Ablaufzeit, Durchlaufzeiten und die Kopfzeile (`issued_at.strftime`, `pdf.py:152–156`) erscheinen 1–2 h falsch (MEZ/MESZ). Der Footer nutzt `datetime.now()` (Container-Zeit = UTC).

**F2 — Zeitzonen im Frontend-Modal:** `+page.svelte:904` befüllt das `datetime-local`-Feld mit `new Date(...).toISOString().slice(0,16)` — das ist UTC-Wandzeit im Lokalzeit-Feld. Beim Speichern geht der String ohne TZ-Suffix ans Backend. Ergebnis: Jede Öffnen/Speichern-Runde verschiebt die Ablaufzeit um den UTC-Offset.

**F3 — Harte Textkürzung mit Datenverlust:** Tabellenzellen im PDF schneiden per Slice ab (`[:22]`, `[:18]`, `[:28]`, `[:35]`, `pdf.py:212–215, 267–269, 289–291, 318–323`). Lange Funkrufnamen, Ortsnamen und Anmerkungen werden stillschweigend abgeschnitten; Zeichenanzahl ≠ Zellbreite, Überlauf ist trotzdem möglich.

**F4 — Tabellen brechen unkontrolliert über Seiten:** Auto-Page-Break mitten in Tabellen, Kopfzeile wird auf der Folgeseite nicht wiederholt (alle Tabellen in `generate_marschbefehl`). Bei Verbänden mit >20 Fahrzeugen wird das Dokument unleserlich.

**F5 — Englisches Zahlenformat:** `f'{v["weight_kg"]:,} kg'` (`pdf.py:322`) ergibt „3,500 kg“ — im Deutschen als 3,5 kg lesbar. Erwartet: „3.500 kg“.

**F6 — Ausstellungsdatum falsch belegt:** `issued_at = convoy.start_time or datetime.now()` (`pdf.py:152`) — der Marschbeginn wird als Ausstellungsdatum/-zeit des Befehls in den Kopf gedruckt. Das sind fachlich zwei verschiedene Angaben.

**F7 — Durchlaufpunkte-Filter zu breit:** `type in ("checkpoint", "waypoint")` (`pdf.py:256`) listet auch Start und Ziel als Durchlaufpunkte. `_build_marschweg` (`pdf.py:124`) nimmt zudem alle Wegpunkte inkl. Halten in den Marschweg auf.

**F8 — GPX: Koordinaten-Check per Falsy:** `if wp.get("lat") and wp.get("lon")` (`export.py:22`) verwirft Koordinate 0.0. Theoretisch, aber trivial zu fixen (`is not None`).

**F9 — Frontend überschreibt Dateinamen:** `a.download = \`${selected.name}.${format}\`` (`+page.svelte:974`) ignoriert den server-seitig bereinigten `Content-Disposition`-Namen — der `Marschbefehl_`-Präfix geht verloren, unsichere Zeichen aus dem Verbandsnamen landen im Dateinamen.

**F10 — Inkonsistentes 404-Verhalten:** GPX-Export bricht ohne berechnete Route mit 404 ab, PDF-Export läuft mit „-“-Werten durch. Gewollt ist vermutlich: PDF geht immer (Befehl auch ohne Route sinnvoll), GPX braucht die Route — dann sollte die PDF-Antwort ohne Route aber keinen leeren „Marschstrecke: -“-Torso liefern, sondern die Strecke sauber weglassen.

### Lücken (Inhalt)

**L1 — Keine Marschzeiten-Übersicht im PDF:** `route.duration_s` existiert, aber weder Gesamtdauer, geplante Ankunft am Ziel noch Abmarschzeit stehen im Dokument — nur Kilometer. Für einen Marschbefehl ist die Zeitplanung der Kern.

**L2 — Betriebsstoff-Analyse fehlt im PDF:** `fuel_svc.analyse_fuel` (Reichweite, Tankstopp nötig/km) wird bei jeder Routenberechnung erzeugt (`routing.py:419`), aber nie persistiert und nicht an `generate_marschbefehl` übergeben. Gehört in Abschnitt 4 (Versorgung).

**L3 — GPX ohne Metadaten und Zeiten:** Kein `creator`, keine Wegpunkt-Symbole/-Typen (`sym`/`type`), keine geplanten Zeiten (`time`-Elemente) — Navigationsgeräte zeigen nur nackte Punkte.

**L4 — JSON-Export ist lückenhaft und nicht rückimportierbar:** `build_json_export` (`export.py:34`) exportiert weder Marschbefehl-Felder (lage, auftrag, marschform, ablauf*, versorgung, funkgruppe, anlagen) noch spacing_*, road_preference, Wegpunkt-Typ/halt_purpose/hold_duration, Fahrzeug-Sonderfunktion/-Abmessungen noch die Routen-Geometrie. Es gibt keinen JSON-Import — als Backup/Duplikat-Format damit wertlos.

**L5 — Kein Audit-Log für Exporte:** Der Audit-Service existiert und das PDF enthält personenbezogene Daten (Mobilnummern) — Exporte sollten wie andere sensible Zugriffe geloggt werden (vgl. `docs/iso-t5-retention-plan.md`).

**L6 — Kein Branding:** Organisations-Logo/-Name aus dem Branding-Service erscheinen nicht im PDF-Kopf.

**L7 — Keine Kartenskizze:** Eine Routen-Übersicht (statisches Kartenbild) fehlt im PDF. Aufwendig (Tile-Rendering server-seitig) — bewusst als optionale letzte Ausbaustufe.

---

## Teil 2 — Implementation Plan

## File Map

**Create:**
- `backend/tests/test_export.py` — GPX/JSON-Service- und Endpoint-Tests
- `backend/tests/test_pdf.py` — Marschbefehl-Generierung (Smoke + Inhalts-Checks via pypdf-Textextraktion)

**Modify:**
- `backend/app/config.py` — `display_timezone: str = "Europe/Berlin"`
- `backend/app/services/pdf.py` — TZ-Umrechnung, Tabellen-Refactoring (multi_cell + Header-Wiederholung), Zahlenformat, Marschzeiten-Block, Betriebsstoff-Abschnitt, Filter-Fixes, Ausstellungsdatum
- `backend/app/services/export.py` — GPX-Metadaten/Symbole/Zeiten, vollständiger versionierter JSON-Export, Koordinaten-Check
- `backend/app/api/routes/routing.py` — fuel_analysis an PDF durchreichen, Audit-Log, 404-Verhalten
- `frontend/src/routes/o/[slug]/plan/+page.svelte` — datetime-local-TZ-Fix, Dateiname aus Content-Disposition

---

### Phase 1 — Korrektheit (F1–F10)

#### Task 1: Zeitzonen-Behandlung zentralisieren (F1, F2, F6)

**Files:** `backend/app/config.py`, `backend/app/services/pdf.py`, `frontend/src/routes/o/[slug]/plan/+page.svelte`, `backend/tests/test_pdf.py`

- [ ] **Step 1: Failing Test** — `test_pdf.py`: Convoy mit `ablaufzeit = 2026-07-07T10:00:00+00:00` erzeugen, PDF-Text extrahieren, `"12:00"` erwarten (MESZ), nicht `"10:00"`.
- [ ] **Step 2:** `config.py`: `display_timezone: str = "Europe/Berlin"`. In `pdf.py` Helper `_to_local(dt) -> datetime` via `zoneinfo.ZoneInfo(settings.display_timezone)`; `_fmt_time`, `_fmt_time_short`, Kopfzeile und Footer (`datetime.now(tz=...)`) darüber leiten. Naive Datetimes als UTC annehmen.
- [ ] **Step 3:** Kopfzeile: Ausstellungsdatum = `datetime.now(local_tz)` („Stand“), Marschbeginn separat als eigene Zeile `Marschbeginn: <start_time>` (nur wenn gesetzt) — nicht mehr `start_time` als Ausstellungsdatum missbrauchen.
- [ ] **Step 4:** Frontend `+page.svelte:904`: Helfer `toLocalDatetimeInput(iso)` (analog `nowLocalDatetime` mit `getTimezoneOffset`) statt `toISOString().slice(0,16)`; beim Speichern `new Date(befehlForm.ablaufzeit).toISOString()` senden (explizit UTC mit `Z`).
- [ ] **Step 5:** Tests laufen lassen, committen.

#### Task 2: PDF-Tabellen robust machen (F3, F4, F5)

**Files:** `backend/app/services/pdf.py`, `backend/tests/test_pdf.py`

- [ ] **Step 1: Failing Test** — Convoy mit 40 Fahrzeugen und 40-Zeichen-Funkrufnamen: PDF > 1 Seite, extrahierter Text enthält den vollen Rufnamen und auf Seite 2 erneut die Spaltenüberschrift „Funkrufname“.
- [ ] **Step 2:** Gemeinsamen Helper `_table(pdf, cols, rows)` einführen: Zeilen mit `multi_cell`-basiertem Umbruch (fpdf2 `pdf.multi_cell(..., max_line_height=...)` je Zelle, Zeilenhöhe = max der Zellen) statt Slice-Kürzung; vor jeder Zeile `will_page_break(row_h)` prüfen und bei Umbruch `_table_header` wiederholen. Alle fünf Tabellen (Marschfolge, Durchlaufpunkte, Marschpausen, Fahrzeuge, Kanalwechsel) darauf umstellen.
- [ ] **Step 3:** Zahlenformat deutsch: `f"{v['weight_kg']:,}".replace(",", ".")` bzw. kleiner Helper `_fmt_int_de`; ebenso km-Angaben mit Komma (`f"{dist_km:.1f}".replace(".", ",")`).
- [ ] **Step 4:** Tests, Commit.

#### Task 3: Filter- und Kleinkram-Fixes (F7, F8, F10)

**Files:** `backend/app/services/pdf.py`, `backend/app/services/export.py`, `backend/app/api/routes/routing.py`, Tests

- [ ] **Step 1: Failing Tests** — (a) Durchlaufpunkte enthalten Start/Ziel nicht; (b) `build_gpx` übernimmt Waypoint mit `lat=0.0`; (c) PDF ohne Route enthält keine Zeile „Marschstrecke“.
- [ ] **Step 2:** `pdf.py`: Durchlaufpunkte = `type in ("checkpoint", "waypoint")` **ohne** erstes/letztes Element der sortierten Liste; `_build_marschweg` nur aus Start, `checkpoint`/`waypoint`-Zwischenpunkten und Ziel (Halte raus).
- [ ] **Step 3:** `export.py:22`: `if wp.get("lat") is not None and wp.get("lon") is not None`.
- [ ] **Step 4:** `pdf.py`: `Marschstrecke`-Zeile nur ausgeben, wenn `route` vorhanden — kein „-“-Torso.
- [ ] **Step 5:** Tests, Commit.

#### Task 4: Frontend-Download-Fix (F9)

**Files:** `frontend/src/routes/o/[slug]/plan/+page.svelte`

- [ ] **Step 1:** In `downloadExport` den Dateinamen aus dem `Content-Disposition`-Header parsen (`res.headers.get('content-disposition')`, Regex `filename="([^"]+)"`), Fallback auf bisherigen Namen.
- [ ] **Step 2:** `npm run check` grün, Commit.

### Phase 2 — Inhaltliche Vervollständigung (L1–L5)

#### Task 5: Marschzeiten-Block im PDF (L1)

**Files:** `backend/app/services/pdf.py`, `backend/tests/test_pdf.py`

- [ ] **Step 1: Failing Test** — PDF mit Route (`duration_s=7200`, `start_time` gesetzt) enthält „Marschdauer“ und die berechnete Ankunftszeit.
- [ ] **Step 2:** In „Marschbewegung“ ergänzen: `Abmarsch:` (start_time, lokal), `Marschdauer:` (`duration_s` als „X Std. Y Min.“ inkl. Haltezeiten aus `hold_duration_min`), `Voraussichtliche Ankunft:` (Abmarsch + Dauer + Halte). Nur ausgeben, was berechenbar ist.
- [ ] **Step 3:** Tests, Commit.

#### Task 6: Betriebsstoff-Analyse in Abschnitt 4 (L2)

**Files:** `backend/app/api/routes/routing.py`, `backend/app/services/pdf.py`, Tests

- [ ] **Step 1: Failing Test** — `generate_marschbefehl(..., fuel_analysis={"fuel_stop_needed": True, "fuel_stop_km": 210.0, ...})` → PDF enthält „Tankstopp“ und „210“.
- [ ] **Step 2:** `generate_marschbefehl` erhält Parameter `fuel_analysis: dict | None = None`; in Abschnitt 4 (Versorgung) kompakter Block: kritischste Reichweite, Tankstopp nötig ja/nein + km-Marke.
- [ ] **Step 3:** `export_pdf` (`routing.py:493`): `fuel_svc.analyse_fuel(...)` wie in `get_route` berechnen (Route + Fahrzeuge liegen vor) und durchreichen.
- [ ] **Step 4:** Tests, Commit.

#### Task 7: GPX aufwerten (L3)

**Files:** `backend/app/services/export.py`, `backend/app/api/routes/routing.py`, `backend/tests/test_export.py`

- [ ] **Step 1: Failing Test** — GPX-Output enthält `creator="ConvoyPlan"`, für einen `technical_stop`-Waypoint `<sym>` + `<type>`, für einen Waypoint mit `planned_arrival` ein `<time>`-Element (UTC).
- [ ] **Step 2:** `build_gpx`: `gpx.creator = "ConvoyPlan"`; Mapping type→`sym`/`type` (checkpoint→Flag, stop/technical_stop→Parking Area, waypoint→Waypoint); `planned_arrival` als `time` übernehmen. Endpoint übergibt `type` und `planned_arrival` mit (`routing.py:452`).
- [ ] **Step 3:** Tests, Commit.

#### Task 8: JSON-Export vollständig + versioniert (L4)

**Files:** `backend/app/services/export.py`, `backend/app/api/routes/routing.py`, `backend/tests/test_export.py`

- [ ] **Step 1: Failing Test** — Export enthält `"format_version": 1`, alle Marschbefehl-Felder, `spacing_urban_m`, Wegpunkt `type`/`hold_duration_min`/`order_index`, Fahrzeug `sonderfunktion`, und (falls Route vorhanden) `route.geojson` + `route.kanalwechsel`.
- [ ] **Step 2:** `build_json_export(convoy, waypoints, vehicles, route=None)` erweitern: `format_version`, `exported_at` (UTC-ISO), alle Convoy-Felder (lage, auftrag, marschform, ablaufpunkt, ablaufzeit, ablaufführer, versorgung, funkgruppe, anlagen, spacing_*, road_preference, status), vollständige Waypoint-/Vehicle-Dicts, optional Route-Geometrie + Kanalwechsel. Endpoint reicht `route` durch.
- [ ] **Step 3:** Tests, Commit. *(JSON-Re-Import als eigenes Folgevorhaben — Format ist mit `format_version` dafür vorbereitet.)*

#### Task 9: Audit-Log für Exporte (L5)

**Files:** `backend/app/api/routes/routing.py`, `backend/tests/test_audit.py`

- [ ] **Step 1: Failing Test** — nach `GET /convoys/{id}/export/pdf` existiert Audit-Eintrag `convoy.export` mit Format im Detail-Feld.
- [ ] **Step 2:** In allen drei Export-Endpoints den bestehenden Audit-Service aufrufen (Muster aus anderen Routen übernehmen, Action `convoy.export`, Detail `{"format": "pdf"|"gpx"|"json"}`).
- [ ] **Step 3:** Tests, Commit.

### Phase 3 — Ausbau (optional, separat priorisieren)

#### Task 10: Branding im PDF-Kopf (L6)

- [ ] Org-Name + Logo (falls im Branding-Service hinterlegt, Bild-Bytes via fpdf2 `image()`) in `_PDF.header()`; Fallback auf bisherigen Text-Header. Test: PDF-Erzeugung mit und ohne Logo.

#### Task 11: Routen-Skizze im PDF (L7)

- [ ] Statisches Kartenbild (z. B. `staticmaps`-Rendering aus Route-GeoJSON, offline aus vorhandenen Tiles) als „Anlage A: Marschweg-Übersicht“ auf eigener Seite. Vorher klären: Tile-Quelle/Lizenz im Offline-Betrieb. Bewusst letzte Priorität.

---

## Verifikation (gesamt)

```bash
cd backend && python -m pytest tests/test_export.py tests/test_pdf.py tests/test_audit.py -v
cd frontend && npm run check
```

Manuell: Verband mit 40 Fahrzeugen, langen Rufnamen, Ablaufzeit 10:00 lokal anlegen → PDF: Zeiten lokal, Tabellen mit wiederholten Headern, deutsches Zahlenformat, Marschdauer/Ankunft, Tankstopp-Hinweis; GPX in Garmin/OsmAnd laden (Symbole + Zeiten sichtbar); JSON auf Vollständigkeit prüfen.
