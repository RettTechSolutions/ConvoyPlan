# Plan: Native Tracking-App

Status: **Entwurf zur Abstimmung** · Stand: 2026-08-27 · Zielrepo: neues Repo `convoyplan-tracking-app`

Dieses Dokument plant eine **eigenständige native App**, die ausschließlich die
öffentliche Tracking-Schnittstelle (`/api/track/*` + `/api/ws/track/*`) einer
ConvoyPlan-Instanz spricht. Sie bildet die Tracking-Ansicht ab —
Fahrzeuginformationen, Statussystem und Zeitplan — und meldet sich beim Start
über den QR-Code des Tracking-Links an, mit oder ohne Passwort, lesend oder als
Fahrer, je nachdem wie der Link erstellt wurde.

---

## 1. Ausgangslage — was bereits steht

Die Backend-Seite ist im Wesentlichen fertig. Die App ist ein **zweiter Client**
auf eine bestehende, bereits produktiv genutzte API — keine neue Serverfunktion.

### Vorhandene Schnittstelle

| Endpunkt | Zweck |
|---|---|
| `GET /api/track/{slug}` | Liefert `TrackPublic` (voller Datensatz) **oder** `TrackGate` (`requires_password`, `convoy_name`), wenn der Link passwortgeschützt und noch kein gültiges Token vorhanden ist. Token per Header `X-Track-Token`. |
| `POST /api/track/{slug}/auth` | Passwort → JWT-Sessiontoken. Rate-Limit **5 Versuche / 300 s**, plus 0,5 s künstliche Verzögerung bei Fehlschlag. |
| `WS /api/ws/track/{slug}?token=…` | Live-Kanal. Schließt mit `4404` (Link unbekannt/widerrufen) bzw. `4001` (Token ungültig). |

Quellen: `backend/app/api/routes/track.py`, `backend/app/schemas/share_link.py`,
`backend/app/services/share_links.py`.

### Datenmodell `TrackPublic`

`name`, `organization`, `start_time`, `scope`, `waypoints[]` (Name, Typ, lat/lon,
`planned_arrival`, `planned_departure`, `halt_purpose`), `geojson` (Routenlinie),
`distance_m`, `kanalwechsel[]` (Leitstellen-Übergabepunkte mit km),
`vehicles[]` (id, Name, Funkrufname, Sonderfunktion, `vehicle_status`, Position)
und `positions[]` (letzte bekannte Koordinaten je Fahrzeug).

### WebSocket-Nachrichten

Vom Server: `position`, `status_update`, `alert`, `position_cleared`, `pong`.
Vom Client (**nur** bei `scope = "driver"`): Positions-Frames und
`{"type":"status", …}`. Bei `scope = "track"` werden eingehende Frames
serverseitig verworfen — die Leseberechtigung ist also nicht nur UI-seitig
durchgesetzt.

### Statussystem (`backend/app/services/vehicle_status.py`, `frontend/src/lib/tracking/status.ts`)

| Status | Unterstufen |
|---|---|
| `planned` · Geplant | — |
| `en_route` · Unterwegs | — |
| `arrived` · Angekommen | — |
| `technical_halt` · Techn. Halt | `standard`, `dringend`, `sehr_dringend` |
| `breakdown` · Ausfall/Störung | `total`, `limited` |

`technical_halt` und `breakdown` lösen zusätzlich ein `alert`-Broadcast aus.
Freitextnotiz optional, serverseitig auf 200 Zeichen gekürzt. Der Altwert
`delayed` wird auf „Unterwegs" abgebildet und muss in der App toleriert werden.

### Link-Erzeugung und QR-Code

`ShareLinkModal.svelte` erzeugt den QR-Code aus der fertigen URL
`{app_base_url}/track/{slug}` (`backend/app/api/routes/share_links.py:_build_url`).
Der Slug ist 8 Zeichen base62. Passwortmodus: `none` | `generate` | `set`,
Scope: `track` | `driver`.

**Konsequenz für die App:** Der QR-Code enthält bereits Host *und* Slug. Bei
einer selbst gehosteten Instanz ist das die einzige Stelle, an der die App
erfährt, mit welchem Server sie sprechen soll. Der QR-Code ist damit nicht nur
Login, sondern auch Instanzkonfiguration.

### Was heute schon als PWA existiert

Unter `/track` liegt eine installierbare Tracking-PWA (`tracking.webmanifest`,
`TrackingPwaHead.svelte`) mit ID-Eingabe, Passwort-Gate, Karte, Fahrzeugliste,
Zeitplan, Fahrer-Panel und Kachel-Vorwärmung. Die native App **ersetzt sie
nicht** — die PWA bleibt der Weg für Gelegenheitsbetrachter ohne Installation.
Die App zielt auf den wiederkehrenden Einsatzfall, in dem Hintergrund-GPS,
Offline-Karten und verlässliche Alarmierung zählen.

---

## 2. Technologieentscheidung

**Empfehlung: React Native (Expo mit Dev Client).**

Ausschlaggebend ist nicht die UI-Schicht, sondern die Rechenlogik. In
`frontend/src/lib/tracking/` liegen rund 290 Zeilen reines TypeScript ohne
DOM-Zugriff, die die Tracking-Ansicht überhaupt erst tragen:

- `eta.ts` — Projektion der Live-Position auf die Routenlinie, Verspätungs­schätzung
- `progress.ts` — Konvoi-Fortschritt (Front/Ende), Wegpunkte und Leitstellenwechsel als geordnete Streckenpunkte
- `status.ts` — Statusvokabular, Farben, Labels

Diese Funktionen bestimmen, welche Ankunftszeit im Zeitplan steht und wann ein
Leitstellenwechsel angekündigt wird. Weichen App und Web hier auseinander,
zeigen zwei Clients desselben Konvois unterschiedliche Zeiten — ein Fehler, der
im Betrieb erst auffällt, wenn er weh tut. React Native kann diese Dateien
**unverändert importieren**; Flutter erzwingt eine Dart-Portierung samt
dauerhafter Synchronisationspflicht.

| | React Native (Expo) | Flutter |
|---|---|---|
| Wiederverwendung `tracking/*` | vollständig, gleiche Quelle | Portierung + Pflege |
| Karte | `@maplibre/maplibre-react-native` (MapLibre Native) | `maplibre_gl` (MapLibre Native) |
| QR-Scanner | `expo-camera` (`CameraView`) | `mobile_scanner` |
| Hintergrund-GPS | `expo-location` + Foreground Service | `geolocator` / `flutter_background_geolocation` |
| Sicherer Speicher | `expo-secure-store` | `flutter_secure_storage` |
| Vertrautheit im Team | TypeScript wie Frontend | neue Sprache |

Beide Stacks lösen die Aufgabe. Flutter ist die bessere Wahl, falls das Team
Dart-Erfahrung hat und die Rechenlogik ohnehin neu geschnitten werden soll —
dann bitte Abschnitt 4 (Phase 0) entsprechend anpassen.

### Geteilte Logik

Phase 0 zieht `frontend/src/lib/tracking/{eta,progress,status}.ts` in ein Paket
`packages/tracking-core/` **in diesem Repo** um. Das Frontend importiert es über
den Workspace, die App über eine Git-Abhängigkeit auf ein Tag. Damit bleibt
ConvoyPlan die Quelle der Wahrheit, und ein Versionssprung in der App ist eine
bewusste Entscheidung statt eines stillen Drifts.

Der billigere Weg — Dateien kopieren und in CI auf Abweichung prüfen — ist
zulässig, wenn Phase 0 sonst zu lange blockiert; er verschiebt die Kosten aber
nur nach hinten.

---

## 3. Anwendungsfluss

### 3.1 Start und Anmeldung

```
App-Start
   │
   ├─ gespeicherte Sitzungen vorhanden? ──► Liste: Konvoiname + Instanz + Rolle
   │                                          └─ Antippen ──► direkt in die Ansicht
   │
   └─ Startbildschirm
         ├─ [QR-Code scannen]   ← Hauptweg
         └─ [Tracking-ID eingeben]  ← Rückfallweg (ID + Serveradresse)
```

**Scan → Auflösung.** Der Scanner akzeptiert alle Formen, in denen ein Link
auftauchen kann:

| Eingang | Ergebnis |
|---|---|
| `https://web.convoyplan.de/track/AbC123Xy` | Host + Slug |
| `https://kunde.example.de/track/AbC123Xy?x=1` | Host + Slug (Query verworfen) |
| `convoyplan://track/AbC123Xy?host=…` | eigenes Schema, optional |
| `AbC123Xy` (reiner Slug, getippt) | Slug — Host muss abgefragt werden |

Die Normalisierung übernimmt dieselbe Logik wie `normalizeId()` in
`frontend/src/routes/track/+page.svelte`: alles ab `/track/`, dann bei
`?`, `#` oder `/` abschneiden, Zeichensatz `[A-Za-z0-9]` erzwingen.

**Gate.** `GET /api/track/{slug}` liefert entweder direkt `TrackPublic` (kein
Passwort) oder `TrackGate`. Nur im zweiten Fall zeigt die App die
Passwortmaske; `convoy_name` aus dem Gate wird bereits als Überschrift
angezeigt, damit der Nutzer sieht, wofür er das Passwort eingibt.

**Passwort.** `POST /api/track/{slug}/auth` → Token. Das Rate-Limit (5 / 5 min)
muss die App sichtbar machen: bei `429` wird der Zeitpunkt aus `Retry-After`
angezeigt statt „Fehler". Token landet in `expo-secure-store` (Keychain /
Keystore), **nicht** in AsyncStorage.

**Rolle.** Erst die erfolgreiche `TrackPublic`-Antwort trägt `scope`. Die App
darf keine Fahrerfunktion anbieten, bevor dieser Wert vorliegt. Bei
`scope = "track"` wird das Fahrer-Panel nicht deaktiviert, sondern gar nicht
gerendert; die Statusliste bleibt vollständig sichtbar, nur eben lesend.

**Ablauf.** Das Sessiontoken lebt 24 Stunden
(`SESSION_TOKEN_TTL_HOURS`). Läuft es während eines Einsatzes ab, schließt der
WebSocket mit `4001`. Die App muss das von einem Netzwerkabbruch unterscheiden
und gezielt die Passwortmaske zeigen, statt endlos zu reconnecten.

### 3.2 Hauptansicht

Karte im Vollbild, darüber ein Bottom Sheet in drei Rastpunkten
(Griff / halb / voll):

- **Kopf** — Konvoiname, Organisation, Startzeit, Verbindungsanzeige (Live / Getrennt)
- **Tab „Fahrzeuge"** — je Fahrzeug: Statuspunkt in Statusfarbe, Name,
  Funkrufname, Sonderfunktion, `LIVE`-Marke bei aktueller Position, Statuslabel.
  Reihenfolge nach `position` (Marschordnung).
- **Tab „Zeitplan"** — Wegpunkte mit geplanter Ankunft/Abfahrt, `halt_purpose`,
  und der aus `eta.ts` berechneten Live-Verspätung. Tab nur einblenden, wenn
  mindestens ein Wegpunkt eine geplante Ankunft hat.
- **Tab „Fahrer"** — nur bei `scope = "driver"`, siehe 3.3.

Auf der Karte: Routenlinie aus `geojson`, Wegpunktmarker, Fahrzeugmarker in
Statusfarbe mit Ausrichtung nach `heading`, Ankündigungsbanner für den nächsten
Streckenpunkt (Wegpunkt oder Leitstellenwechsel) aus `progress.ts`.

### 3.3 Fahrerbetrieb

Nur bei `scope = "driver"`. Fahrzeug wählen → Übertragung starten. Die App
schickt Positions-Frames über den WebSocket; der Server schreibt sie fort und
hebt ein noch `planned`-Fahrzeug automatisch auf `en_route`.

Statusraster wie im Web: `planned` / `en_route` / `arrived` als Direktwahl,
`technical_halt` und `breakdown` mit Nachfrage nach Stufe und optionaler Notiz.

Der eigentliche Grund für die native App steht hier: **Hintergrund-GPS**. Als
Android-Foreground-Service mit dauerhafter Benachrichtigung und unter iOS mit
`UIBackgroundModes: location` läuft die Übertragung weiter, wenn das Display aus
ist oder der Fahrer die Navigation in den Vordergrund holt — genau das kann die
PWA nicht.

### 3.4 Alarme

Ein `alert`-Frame (Techn. Halt / Ausfall) erzeugt Vibration, Tonfolge und ein
Banner mit Fahrzeug, Stufe und Notiz — Verhalten wie `notify.ts`, aber ohne die
Autoplay-Beschränkungen des Browsers. Im Hintergrund wird eine lokale
Benachrichtigung ausgelöst, solange der WebSocket steht.

---

## 4. Phasenplan

### Phase 0 — Fundament (≈ 4–5 PT)

- Repo `convoyplan-tracking-app`, Expo + TypeScript, EAS-Build-Profile
- `packages/tracking-core` aus `frontend/src/lib/tracking/` extrahieren; Frontend auf das Paket umstellen (Verhalten unverändert)
- Typen aus `openapi.json` generieren, damit `TrackPublic` & Co. nicht abgetippt werden
- API-Client (`X-Track-Token`, Fehlerabbildung 401/404/429) und WS-Client mit exponentiellem Backoff, Ping/Pong und Unterscheidung `4001` / `4404` / Netzabbruch
- CI: Lint, Typecheck, Unit-Tests

*Fertig, wenn:* Ein Integrationstest gegen eine Demo-Instanz holt `TrackPublic`
und empfängt einen `position`-Frame.

### Phase 1 — Anmeldekette (≈ 5–6 PT)

- Startbildschirm, Sitzungsliste, ID-Eingabe als Rückfallweg
- QR-Scanner inkl. Kamera-Berechtigung, Taschenlampe, Fehlerbild bei fremdem QR-Code
- URL-Normalisierung (Host + Slug), Instanz-Ableitung
- Passwort-Gate inkl. `429`-Behandlung
- Token in `expo-secure-store`, Sitzung vergessen, Ablauf-Behandlung
- Scope-Auswertung: lesend vs. Fahrer

*Fertig, wenn:* Scan eines passwortgeschützten Lese-Links führt zur
Fahrzeugliste; ein Neustart der App überspringt Scan und Passwort.

### Phase 2 — Tracking-Ansicht (≈ 8–10 PT)

- MapLibre-Karte, Routenlinie, Wegpunkte, Fahrzeugmarker mit Status und Heading
- Bottom Sheet, Tabs Fahrzeuge / Zeitplan
- Live-Aktualisierung über `position`, `status_update`, `position_cleared`
- Zeitplan mit Verspätung aus `tracking-core`
- Streckenpunkt-Ankündigung (Wegpunkt / Leitstellenwechsel)
- Hell/Dunkel entsprechend Systemeinstellung

*Fertig, wenn:* Die App zeigt denselben Zustand wie `/track/{slug}` im Browser,
Seite an Seite geprüft.

### Phase 3 — Fahrerbetrieb (≈ 6–8 PT)

- Fahrzeugauswahl, Start/Stopp der Übertragung
- Foreground Service (Android) / Background Location (iOS), Display-Wachhalten
- Statusraster inkl. Stufen und Notiz
- Manuelle Positionssetzung per Kartentipp, wenn kein GPS-Fix
- Batterieverhalten: Sendeintervall, Genauigkeitsstufe, Verhalten im Funkloch (Puffer + Nachsenden)

*Fertig, wenn:* Eine simulierte Fahrt über 30 Minuten mit ausgeschaltetem
Display lückenlos im Web-Tracking ankommt.

### Phase 4 — Robustheit (≈ 5–7 PT)

- Offline-Kartenregion entlang des Routenkorridors (MapLibre Offline Region) — natives Gegenstück zu `tileCache.ts`
- Alarmierung: Ton, Vibration, lokale Benachrichtigung
- Wiederverbindung nach Netzwechsel, Zustand nach App-Neustart
- Barrierefreiheit: Kontraste, Schriftskalierung, Screenreader-Labels für Statusfarben (Farbe darf nie die einzige Information sein)

### Phase 5 — Veröffentlichung (≈ 4–6 PT)

- Signierung, App-Store- und Play-Store-Einträge, Datenschutzerklärung mit klarer Aussage zur Standorterhebung
- Datenschutz-Labels: Standortdaten, Zweckbindung, keine Weitergabe
- Beta über TestFlight und Play Internal Testing
- Kurzanleitung im Wiki (`wiki/Live-Tracking.md` ergänzen)

**Summe: ≈ 32–42 Personentage** für eine Person, ohne Store-Review-Wartezeiten.

---

## 5. Notwendige Änderungen im ConvoyPlan-Repo

Klein und rückwärtskompatibel — die App braucht keine neue Fachlogik.

1. **`scope` in `TrackGate` ergänzen** (`backend/app/schemas/share_link.py`).
   Heute erfährt der Client die Rolle erst *nach* der Passworteingabe. Für die
   Gate-Maske („Fahrer-Anmeldung für Konvoi X") ist das zu spät. Ein Feld,
   keine Sicherheitsauswirkung — der Scope ist ohnehin serverseitig durchgesetzt.

2. **App Links / Universal Links** — `.well-known/assetlinks.json` und
   `apple-app-site-association` über Caddy ausliefern (`caddy/`), damit ein mit
   der Systemkamera gescannter Link die App öffnet statt den Browser.
   *Einschränkung:* Bei selbst gehosteten Instanzen liegen diese Dateien nur
   vor, wenn der Betreiber die aktuelle Caddy-Konfiguration fährt. Deshalb
   bleibt der **In-App-Scanner der Hauptweg** und Universal Links eine
   Bequemlichkeit.

3. **Token-Erneuerung** — entweder ein `POST /api/track/{slug}/auth/refresh`
   oder eine per Konfiguration verlängerbare TTL für App-Sitzungen. Ohne das
   muss ein Fahrer das Passwort mitten im Einsatz erneut eingeben. Empfehlung:
   Erneuerung gegen ein noch gültiges Token, Kette begrenzt auf die Lebensdauer
   des Links.

4. **Optional, Phase 4+: Push-Zustellung.** Der WebSocket trägt Alarme nur,
   solange die App läuft. Für Alarme bei geschlossener App: Tabelle für
   Gerätetoken, `POST /api/track/{slug}/push`, Versand über FCM/APNs. Die
   Registrierung muss an den Link gebunden sein und beim Widerruf mitfallen.
   Bewusst als eigener Schritt — es ist der einzige Punkt, der neue
   personenbezogene Daten einführt.

5. **Optional: Mindestversion.** Ein Feld in `/api/version`, damit eine
   Instanz eine zu alte App zum Update auffordern kann.

---

## 6. Risiken

| Risiko | Wirkung | Umgang |
|---|---|---|
| **OSM-Kachelrichtlinie** | `tile.openstreetmap.org` ist für App-Verkehr in dieser Größenordnung nicht vorgesehen; die PWA deckelt heute schon auf 8000 Kacheln. Eine App mit Offline-Regionen überschreitet das deutlich. | Vor Phase 2 klären: eigener Kachelserver, Vektorkacheln aus dem vorhandenen GraphHopper-Datenbestand, oder ein kommerzieller Anbieter. **Das ist die einzige Entscheidung, die den Zeitplan kippen kann, wenn sie zu spät fällt.** |
| **Store-Prüfung Hintergrundstandort** | Beide Stores prüfen Background-Location streng; Ablehnung kostet Wochen. | Foreground Service mit sichtbarer Benachrichtigung, Erhebung nur bei aktiver Übertragung, Zweck im Store-Eintrag und im Berechtigungsdialog benennen. Früh einreichen (Phase 3, nicht Phase 5). |
| **Selbst gehostete Instanzen** | Private DNS, eigene Zertifikate, abweichende Basis-URL. | Basis-URL immer aus dem QR-Code ableiten, nie fest verdrahten. **Kein Certificate Pinning** — es würde legitime Selbsthoster aussperren. |
| **Auseinanderdriften von App und Web** | Zwei Clients zeigen verschiedene Ankunftszeiten. | `tracking-core` als gemeinsame Quelle (Phase 0). |
| **Slug als Zugangsmittel** | Wer den Link hat, kommt hinein; ein Fahrer-Link kann Positionen senden. | Token sicher speichern, Sitzung löschbar, gescannte QR-Bilder nicht persistieren, im Wiki auf Widerruf hinweisen. |
| **Doppelte Pflege gegenüber der PWA** | Jede Änderung an der Tracking-Ansicht fällt zweimal an. | Bewusst akzeptiert: Die PWA bleibt der schlanke Betrachterweg, die App deckt Fahrerbetrieb und Offline ab. Fachlogik geteilt, Darstellung getrennt. |

---

## 7. Prüfvorgehen

- **Unit** — `tracking-core` (Projektion, Verspätung, Streckenpunkte) mit den bestehenden Frontend-Testfällen
- **Vertrag** — Antworttypen gegen `openapi.json` prüfen, damit eine Schemaänderung im Backend die App-CI rot macht statt den Nutzer
- **Integration** — gegen eine Demo-Instanz: Lese-Link ohne Passwort, Lese-Link mit Passwort, Fahrer-Link, widerrufener Link, falsches Passwort bis ins Rate-Limit
- **Feld** — simulierte Fahrt mit GPX-Wiedergabe; Funkloch durch Flugmodus mitten in der Strecke; App-Neustart während laufender Übertragung
- **Seite-an-Seite** — App gegen `/track/{slug}` im Browser, gleicher Konvoi, gleicher Moment

---

## 8. Offene Punkte

1. **Kachelquelle** — blockiert Phase 2, siehe Risikotabelle. Zu entscheiden, bevor Phase 1 endet.
2. **Push ja/nein** — bestimmt, ob personenbezogene Gerätedaten ins Backend kommen; wirkt auf Datenschutzerklärung und Store-Labels.
3. **Store-Veröffentlichung oder interne Verteilung** — bei rein interner Nutzung (MDM, Play Internal, Ad-hoc) entfällt Phase 5 fast vollständig.
4. **Mindest-Betriebssystemversionen** — bestimmt, welche Geräte im Einsatz überhaupt in Frage kommen.
5. **Flutter statt React Native** — falls das Team es anders sieht, ändert das Phase 0 und die Aufwandsschätzung, nicht den Rest des Plans.
