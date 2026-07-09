# Changelog

All notable changes to ConvoyPlan are documented here.

## Versionierung

Ab `2026.1.1` nutzt ConvoyPlan das kalenderbasierte Schema **`YYYY.MASTER.FIX`**
(z. B. `2026.1.1`):

- **`YYYY`** – Jahreszahl des Releases (z. B. `2026`).
- **`MASTER`** – Master-Release: größere Feature-Veröffentlichung innerhalb des
  Jahres; beginnt bei jedem Jahreswechsel wieder bei `1`.
- **`FIX`** – Fix-/Beta-Release: Bugfixes, Sicherheits-Patches und
  Dependabot-Wellen auf einem Master-Release.

Zuvor galt die semantische Versionierung (`MAJOR.MINOR.PATCH`); das Schema
wurde nach `1.0.2` umgestellt. Alle älteren Einträge unterhalb behalten ihre
ursprünglichen SemVer-Nummern.

---

## [Unreleased]

### Fixed

- **Sperrdaten werden jetzt entlang der gesamten Route abgefragt.** Bisher wurden Sperrungen/Baustellen nur in einem festen Radius um den Startpunkt (bzw. die Kartenmitte) abgefragt — Sperrungen weiter entlang der Route wurden nie gefunden. Der neue Endpunkt `POST /api/overpass/closures/route` fragt stattdessen einen 2-km-Korridor entlang der gesamten Routen-Geometrie ab (die Route wird serverseitig auf max. ~150 Stützpunkte ausgedünnt, damit die Anfrage kompakt bleibt); ohne berechnete Route greift weiterhin Punkt+Radius als Fallback. Zusätzlich gibt es jetzt einen Fallback auf Overpass-Mirrors (`kumi.systems`, `private.coffee`), falls der primäre Server (`overpass-api.de`) überlastet ist.
- **Marschbefehl-Modal-Layout repariert.** Das generische Modal-Stylesheet (max. 420px breit, 2rem Padding, Label-Spalten-Layout) stand später im CSS und überschrieb die Befehl-Modal-Styles: Das Modal wurde auf 420px gequetscht, der Pflichtfeld-Stern rutschte in eine eigene Zeile, und der Hinweistext war auf hellem Grund unsichtbar (falsche Theme-Variable). Behoben durch eigene, höher priorisierte Selektoren für das Befehl-Modal (720px breit) sowie einen überarbeiteten Footer (Abbrechen links, Aktionen rechts; unter 560px gestapelte Buttons in voller Breite).
- **Schwarze/weiße Streifen auf Mobile-Browsern beseitigt.** iOS Safari füllt die Flächen hinter Statusleiste und Toolbar mit der Hintergrundfarbe von `html`/`body` — die war bisher nicht gesetzt, wodurch auf Login-, Demo- und Setup-Seiten je nach Theme schwarze bzw. weiße Streifen oben und unten erschienen. Hintergrundfarbe und die `theme-color`-Meta folgen jetzt dem aktiven Theme; zentrierte Vollhöhen-Seiten nutzen `100dvh` (mit `100vh`-Fallback) plus Safe-Area-Insets als Padding.
- **Kanalwechsel zeigen jetzt korrekte An- und Abmeldepunkte je Leitstelle.** Bisher erzeugte jeder Schnittpunkt der Route mit einer Leitstellen-Grenze einen eigenen Eintrag — pendelte die Route an einer Gebietsgrenze hin und her (z. B. Autobahn entlang einer Landkreisgrenze), erschienen im Zeitplan und Marschbefehl viele doppelte „Wechsel" mit identischen Kilometerangaben. Die Berechnung ermittelt jetzt je Leitstelle die tatsächlich durchfahrenen Routenabschnitte und bildet daraus eine sequenzielle Übergabekette: Der Verband ist immer bei genau einer Leitstelle angemeldet — bei jedem Wechsel wird **erst bei der alten Leitstelle abgemeldet, dann bei der neuen angemeldet**; überlappen sich Gebiete (Grenz-Pendelei), liegt der Übergabepunkt in der Mitte des gemeinsamen Korridors. Der erste Eintrag der Kette ist die **„Convoy Anmeldung"** bei der Start-Leitstelle (km 0) mit ihrer Anrufgruppe. Zeitplan, Marschbefehl-Formular und PDF-Export zeigen die neue Spalte „Aktion" (Convoy Anmeldung/Anmelden/Abmelden).

- **Kein automatisches Downgrade beim Wechsel von Beta zurück auf Stable.** Eine Instanz, die im Beta-Kanal lief, ist neuer als das letzte Release — die Statusanzeige meldete dann im Stable-Kanal fälschlich „Update verfügbar", und der Auto-Updater hätte ein Downgrade aufs ältere Release gefahren (riskant bei bereits angewendeten DB-Migrationen). Jetzt prüfen Backend und Updater die Ancestry (GitHub-Compare bzw. `git merge-base`): Ist der installierte Stand gleich oder neuer als das Release, zeigt die UI „Neuer als letztes Release (Beta-Stand) ✓" und der Updater wartet, bis ein neueres Release den Stand überholt. Der manuelle „Jetzt updaten"-Knopf setzt weiterhin bewusst auf das Release zurück (Rollback-Weg).
- **Beta-Kanal funktioniert jetzt auch bei image-basierten Installationen.** Der Update-Kanal „Beta" versprach „jeder Commit auf `main` wird installiert" — bei Standard-Installationen (`install.sh`, image-basierter Updater) wurden aber immer nur die `:latest`-Images gezogen, die ausschließlich beim Release-Tag gebaut werden. Ergebnis: Status dauerhaft „Update verfügbar", aber „Jetzt updaten" installierte nichts Neues. Jetzt baut der neue Workflow `beta-images.yml` bei jedem Push auf `main` zusätzlich `:beta`-Images (durch die Merge Queue ist jeder `main`-Commit getestet), und der Updater zieht im Beta-Kanal diese Images und folgt dem `main`-HEAD. Ein Kanalwechsel im Admin-Panel löst beim nächsten Check (≤ `UPDATE_INTERVAL`) automatisch ein Update auf das jeweilige Kanal-Ziel aus — auch zurück auf Stable. Als Beta-Ziel gilt dabei der Commit des **letzten erfolgreichen Beta-Image-Builds** (nicht der `main`-HEAD): Direkt nach einem Merge — solange die Images noch gebaut werden — zeigt der Admin-Bereich also kein verfrühtes „Update verfügbar" mehr an, und der Updater zieht keine veralteten Images.
- **Auto-Updater installiert neue Releases jetzt wirklich automatisch.** Der image-basierte Updater (`update-images.sh`, Standard bei Installationen über `install.sh`) reagierte bisher nur auf den manuellen „Jetzt aktualisieren"-Trigger aus dem Admin-Bereich — die UI zeigte zwar „Update verfügbar", installiert wurde von selbst aber nie. Der Updater prüft jetzt alle `UPDATE_INTERVAL` Sekunden (Standard: 300) das neueste veröffentlichte GitHub-Release und zieht bei einem neuen Tag automatisch die Images und startet die Dienste neu. Zusätzlich startet sich der Updater-Container nur noch dann selbst neu, wenn sich sein Image oder die Stack-Datei tatsächlich geändert hat (vorher: nach jedem Update).
- **Updater-Absturz bei GitHub-Ausfall behoben.** War die GitHub-API nicht erreichbar (oder existierte noch kein Release), beendete ein Pipeline-Fehler unter `set -euo pipefail` das komplette Updater-Skript — der Container geriet in eine Restart-Schleife. Betroffen waren beide Varianten (`update.sh` und `update-images.sh`); die Release-Abfrage schlägt jetzt sauber fehl und versucht es im nächsten Intervall erneut.

### Changed

- **Versionsschema auf `YYYY.MASTER.FIX` (CalVer) umgestellt.** ConvoyPlan nutzt statt der semantischen Versionierung (`MAJOR.MINOR.PATCH`) jetzt ein kalenderbasiertes Schema: `YYYY` (Jahreszahl) . `MASTER` (Master-Release des Jahres) . `FIX` (Fix-/Beta-Release). Der Wechsel erfolgt nach `1.0.2`; das erste Release im neuen Schema ist `2026.1.1`. Die „Update verfügbar"-Erkennung vergleicht die Versionskomponenten weiterhin rein numerisch, sodass die Reihenfolge über den Wechsel hinweg erhalten bleibt (`2026.1.1` liegt über `1.0.2`). `auto-release.yml` erhöht bei Dependabot-Wellen automatisch die `FIX`-Komponente; Jahr und Master-Release werden bewusst manuell beim Schneiden eines Master-Releases gesetzt.
- **Dependabot-PRs laufen jetzt durch eine Merge Queue und lösen automatisch ein Patch-Release aus.** Bisher blockierten sich gleichzeitige Dependabot-PRs gegenseitig: Nach jedem Merge war der nächste PR „behind" und musste von Hand aktualisiert werden. Das Ruleset erzwingt jetzt GitHubs native Merge Queue — PRs werden seriell von unten nach oben abgearbeitet (temporärer Merge-Branch mit aktuellem `main` → Checks → Squash-Merge → nächster PR), ganz ohne manuelles „Update branch". Sobald die Welle abgearbeitet ist, erstellt der neue Workflow `auto-release.yml` automatisch den nächsten Patch-Tag und stößt den Release-Build an (nur bei Dependabot-Merges; menschliche Merges bleiben Tag-getrieben). Einmalige Admin-Aktion nötig: Ruleset aus `.github/rulesets/main.json` neu importieren (siehe `.github/repo-setup-checklist.md`).

### Added

- **Vor- und Nachname bei der Benutzeranlage.** Benutzer bekommen optionale Felder für Vor- und Nachname: im Admin-Panel (und Org-Admin-Panel analog) beim Anlegen und im Bearbeiten-Modal editierbar, als eigene Spalte in der Benutzertabelle sichtbar und Teil des DSGVO-Datenexports. Einladungs- und Passwort-E-Mails nutzen den Namen jetzt in der Anrede (vorher immer leer).
- **Geführte Onboarding-Tour als Spotlight direkt in der UI.** Die Tour erklärt die App nicht mehr über einen zentrierten Modal-Dialog, sondern führt direkt durch die Bedienoberfläche: Pro Schritt wird das echte Element (Verband-Auswahl, Karten-Buttons, Route berechnen, Tabs, Admin-Link, …) per Spotlight hervorgehoben, die Erklärkarte dockt daneben an und folgt dem Ziel auch bei Tab-Wechsel, Scrollen, Resize und einfahrender mobiler Seitenleiste. Ohne passendes Zielelement (z. B. Willkommensschritt) erscheint weiterhin der zentrierte Fallback.
- **Verkehrsdaten-Konfiguration im Docker-Compose durchgereicht.** Damit die neuen Einstellungen über die `.env` tatsächlich im Backend-Container ankommen, reicht `docker-compose.yml` sie jetzt explizit durch (`HERE_TRAFFIC_API_KEY`, `TOMTOM_TRAFFIC_API_KEY`, `TRAFFIC_FLOW_PROVIDER`, `OPENDATA_TRAFFIC_ENABLED`, `OPENDATA_TRAFFIC_FEEDS` mit BW+Berlin als Default, `OPENDATA_TRAFFIC_CLIENT_CERT`, `OPENDATA_TRAFFIC_CA_CERT`). Zusätzlich wird der Host-Ordner `./secrets` read-only nach `/secrets` gemountet — dort liegen mobilithek-Client-Zertifikat und CA-Kette (per `.gitignore` vom Repo ausgeschlossen).
- **DATEX-II-Unterstützung für bundesweite Baustellendaten (mobilithek).** Der Open-Data-Dienst kann jetzt zusätzlich Feeds im europäischen **DATEX II v2**-Standard einlesen (Format `datex2`) — damit lassen sich die Länder-Feeds aus der **mobilithek** anbinden, die abseits der Autobahn bundesweit Baustellen und Sperrungen abdecken. Der Parser wandelt DATEX-II-`SituationRecords` (Construction-/Maintenance-Works, Straßensperrungen) in Kartenobjekte: Geometrie aus `gmlLineString`/`posList` (sonst `locationForDisplay`-Punkt), Titel/Beschreibung aus den Meldungstexten, Sperrungserkennung über `roadOrCarriagewayOrLaneManagementType` (`roadClosed`/`carriagewayClosures`), Gültigkeit über `overallEndTime` (Abgelaufenes wird ausgeblendet). Große Feeds werden speicherschonend per Streaming geparst. Ist ein Feed per **mTLS** geschützt (mobilithek-Broker), lässt sich über `OPENDATA_TRAFFIC_CLIENT_CERT` das eigene Client-Zertifikat (PEM) und über `OPENDATA_TRAFFIC_CA_CERT` die private Broker-CA-Kette (mobilithek-M2M, `prod-mdp.m2m.de`) zum Verifizieren des Servers hinterlegen. Konfiguration wie gehabt über `OPENDATA_TRAFFIC_FEEDS` als `datex2|<url>`.
- **Offene Baustellenfeeds um Berlin erweitert (Multi-Format-Framework).** Die Open-Data-Quelle liest jetzt Feeds in mehreren Schemata: neben **MobiData BW** (Baden-Württemberg, CIFS-Stil) auch die **Berliner Verkehrsinformationszentrale (VIZ)** — beide standardmäßig aktiv und ohne API-Key/Registrierung. Da jede Region ihr eigenes GeoJSON-Schema nutzt, gibt es pro Format einen kleinen Adapter (`mobidata_bw`, `berlin_viz`); Berlins GeometryCollections werden in einzelne Linien/Punkte zerlegt, abweichende Zeit-/Sperrungsfelder normalisiert. Weitere Regionen lassen sich über `OPENDATA_TRAFFIC_FEEDS` als `format|url` ergänzen. Für eine wirklich bundesweite Abdeckung abseits der Autobahn bleibt die mobilithek (DATEX II) die offizielle Aggregation — deren maschineller Zugang erfordert allerdings Registrierung und Client-Zertifikat.
- **HERE-/TomTom-Keys im Superadmin-Bereich hinterlegbar.** Die API-Keys für die Live-Verkehrslage müssen nicht mehr per Umgebungsvariable gesetzt werden: Unter Admin → „Live-Verkehrslage (Stau)" können Superadmins den HERE- bzw. TomTom-Key direkt eintragen, den bevorzugten Anbieter wählen und den Status sehen (gesetzt via Datenbank/Umgebungsvariable, aktiver Anbieter). Die Werte liegen in `system_settings` und **überschreiben** die ENV-Konfiguration; das Feld zeigt nie den gespeicherten Key im Klartext. Sobald ein Key hinterlegt ist, ist die Verkehrslage **bundesweit** verfügbar (HERE/TomTom decken ganz Deutschland ab — anders als die regionalen Open-Data-Baustellenfeeds). Neue Endpunkte `GET`/`PUT /api/admin/settings/traffic-keys`.
- **Live-Verkehrslage (Stau) optional über HERE/TomTom — vorbereitet eingebunden.** Die App kann jetzt die Echtzeit-Verkehrslage (Fließgeschwindigkeit/Stau, grün→gelb→rot) entlang der Route anzeigen — wie man es von Google Maps kennt. Da es dafür keine kostenlose offene Quelle mit Stadtabdeckung gibt, ist die Anbindung an die kommerziellen Anbieter **HERE** und **TomTom** vollständig verdrahtet, aber **standardmäßig inaktiv**: Erst wenn eine Installation ihren eigenen API-Key hinterlegt (`HERE_TRAFFIC_API_KEY` bzw. `TOMTOM_TRAFFIC_API_KEY`, beide mit kostenlosem Kontingent), erscheint im Export-Tab der Schalter „Verkehrslage laden" und die Ebene wird über die Karte gelegt. Ohne Key bleibt alles unverändert (kein Schalter, keine Anfragen). Die Verkehrsdaten werden als JSON abgerufen und **selbst als farbige Linien gerendert** (keine fremden Kartenkacheln); die Quelle ist per `TRAFFIC_FLOW_PROVIDER` wählbar (Standard: HERE bevorzugt). Neue Endpunkte `GET /api/traffic/flow/status`, `GET /api/traffic/flow`, `POST /api/traffic/flow/route`. Hinweis: Die Anzeige von HERE-/TomTom-Verkehrsdaten auf der OSM-Basiskarte kann lizenzpflichtig sein — die Nutzungsbedingungen des Anbieters sind vor Produktivbetrieb zu prüfen (Verantwortung der jeweiligen Installation).
- **Dritte Verkehrsdatenquelle: offene regionale Baustellen-/Sperrungs-Feeds (Open Data).** Neben Overpass und der Autobahn-API werden jetzt auch lizenzfreie, offene GeoJSON-Feeds im MobiData-BW-/CIFS-Stil eingelesen und in dieselbe Kartenebene gemischt — damit werden Baustellen/Sperrungen auch abseits der Autobahn (Bundes-, Landes-, Kreisstraßen) erfasst, sofern eine Region ihre Daten offen bereitstellt. Vorkonfiguriert ist **MobiData BW** (Baden-Württemberg). Die Feed-Liste ist über `OPENDATA_TRAFFIC_FEEDS` (kommaseparierte URLs) **pro Installation** erweiterbar, ohne Code-Änderung; abgelaufene Ereignisse werden anhand ihres Endzeitpunkts ausgeblendet, aktive/künftige auf Routenkorridor bzw. Radius gefiltert und für 5 Minuten gecacht. Die Quelle ist optional und ausfalltolerant (kein Key, kein harter Fehler bei Nichterreichbarkeit); per `OPENDATA_TRAFFIC_ENABLED=false` abschaltbar.
- **Zweite Verkehrsdatenquelle: Autobahn-API (bund.dev) zusätzlich zu Overpass.** Baustellen, Sperrungen und Hindernisse wurden bisher nur aus OpenStreetMap/Overpass geladen — kurzfristige Sperrungen, Unfälle und Hindernisse auf Bundesautobahnen fehlten dort häufig. Ab sofort werden die Daten aus **Overpass und der offiziellen Autobahn-API** (`autobahn.api.bund.dev`: `roadworks`, `warning`, `closure`) zusammengeführt und in einer gemeinsamen Kartenebene angezeigt („in einen Topf"). Der bundesweite Autobahn-Datensatz wird gebündelt geholt, für 5 Minuten gecacht und lokal auf den Routenkorridor bzw. Radius gefiltert; doppelte Meldungen (dieselbe Baustelle an mehreren Autobahnkreuzen) werden entfernt. Fällt eine Quelle aus, liefert die andere weiterhin Ergebnisse — nur wenn beide scheitern, gibt es einen Fehler. Auf der Karte werden die Sperrungen jetzt nach Schweregrad eingefärbt (rot = Voll-/Sperrung, gelb = Verkehrswarnung/Hindernis, orange = Baustelle), und die Statusanzeige zeigt einen eigenen Punkt für die Erreichbarkeit der Autobahn-API.
- **Zusatzkanäle der Leitstellen direkt im Kanalwechsel-Plan.** Die bei einer Leitstelle hinterlegten weiteren Funkgruppen (z. B. Führungskanal) werden jetzt mit den Kanalwechseln mitgeliefert: In Zeitplan und Marschbefehl-Formular lässt sich jede Anmelde-Zeile per Tipp/Klick aufklappen (funktioniert damit auch am Smartphone, wo es kein Hover gibt); das Marschbefehl-PDF listet die Zusatzkanäle als Zusatzzeile unter der jeweiligen Leitstelle.
- **Live-Tracking meldet Wegpunkte und Leitstellenwechsel anhand der Konvoi-Position.** Die Tracking-Ansicht (intern und über Tracking-Links, inkl. Fahrer-Links) projiziert alle sendenden Fahrzeuge auf die Route und kennt damit Spitze und Schluss des Verbands. Oben auf der Karte zeigt eine Leiste den nächsten Punkt voraus („In 2,4 km: Leitstellenwechsel → ILS FFB"); erreicht die Spitze einen Übergabepunkt oder Wegpunkt, erscheint eine Meldung mit Ton und Vibration — bei Leitstellenwechseln inklusive Abmelde-/Anmelde-Info und Anrufgruppe. Solange der Verband den Punkt passiert, zählt die Meldung mit („3/5 Fahrzeuge passiert") und bestätigt grün, sobald auch das letzte Fahrzeug durch ist.
- **Optionale E-Mail nach automatischen Updates.** Im Update-Modus „Automatisch" lässt sich unter Admin → Software-Update jetzt zusätzlich ankreuzen, dass alle aktiven Superadmins per E-Mail informiert werden, **nachdem** ein Update automatisch installiert wurde (erkannt am Wechsel der installierten Version; genau eine Mail pro Stand, SMTP-Konfiguration erforderlich). Standardmäßig aus; gespeichert in `system_settings` (`update.notify_on_auto`), vorkonfigurierbar per `UPDATE_NOTIFY_ON_AUTO`.
- **Update-Modus „Automatisch" / „Benachrichtigen" im Admin-Bereich.** Neben dem Update-Kanal lässt sich unter Admin → Software-Update jetzt der Update-Modus wählen. **Automatisch** (Standard) installiert verfügbare Updates im gewählten Kanal ohne weiteres Zutun. **Benachrichtigen** deaktiviert die automatische Installation: Sobald im gewählten Kanal ein Update verfügbar ist, erhalten alle aktiven Superadmins einmalig eine E-Mail (pro Update-Ziel; SMTP-Konfiguration erforderlich) und installieren dann bewusst über „Jetzt updaten". Der Modus wird in `system_settings` (`update.mode`) gespeichert, an den Updater-Container gereicht (`/update_status/mode`) und ist per `UPDATE_MODE` als Fallback vorkonfigurierbar (neue Endpunkte `GET`/`PUT /api/admin/settings/update-mode`, Prüfintervall via `UPDATE_NOTIFY_INTERVAL`).

- **Update-Kanal „Stable" / „Beta" im Admin-Bereich.** Unter Admin → Software-Update lässt sich jetzt der Update-Kanal umschalten. **Stable** (Standard) meldet und installiert nur **veröffentlichte GitHub-Releases** – ein einzelner Commit auf `main` löst kein Update mehr aus und wird auch nicht mehr fälschlich als „Update verfügbar" angezeigt. **Beta** verfolgt weiterhin jeden Commit auf `main` (für Tests/Vorab-Versionen, v. a. bei quellbasierten Installationen). Die Statusanzeige vergleicht im Stable-Kanal gegen das neueste Release (Tag + Commit) statt gegen die Spitze von `main`; gibt es noch kein Release, wird das sauber als „noch kein Release veröffentlicht" ausgewiesen. Der gewählte Kanal wird in `system_settings` (`update.channel`) gespeichert, an den Updater-Container gereicht und ist per `UPDATE_CHANNEL` als Fallback vorkonfigurierbar (neue Endpunkte `GET`/`PUT /api/admin/settings/update-channel`).
- **Changelog-Hinweis nach Versionswechsel.** Nach einem Update auf eine neue Version wird den Nutzern einmalig ein „Neue Version"-Dialog mit den Release-Notes angezeigt – live aus dem GitHub-Release der laufenden Version geladen (neuer öffentlicher Endpunkt `GET /api/version/changelog`, gecacht). Ausschlaggebend ist ausschließlich der Wechsel der **Version** (x.y.z), nicht des Commits: Build-Metadaten (`+sha`) und `git describe`-Suffixe werden ignoriert, und die zuletzt gesehene Version wird pro Gerät gemerkt. Beim allerersten Start wird der aktuelle Stand still vermerkt, ohne den Dialog anzuzeigen.
- **Adress-Eingabe direkt bei „Punkt setzen".** In der Routen-Erstellung kann der aktive Punkt (Start, Ziel oder Wegpunkt) jetzt nicht nur per Kartenklick, sondern auch oben in der Hinweis-Leiste direkt per Adress-Suche gesetzt werden.

### Changed

- **Offline-Erkennung im Live-Tracking deutlich schneller.** Die Tracking-Verbindung nutzt jetzt einen Anwendungs-Heartbeat (Ping/Pong über die WebSocket): Bricht das Mobilfunknetz weg, bleibt der TCP-Socket oft minutenlang scheinbar „offen" – der Heartbeat erkennt den toten Link nun innerhalb weniger Sekunden, zeigt die „Du bist offline"-Meldung sofort an und stößt automatisch einen Reconnect an.
- **Karten-Tiles der Route werden zuverlässiger vorgeladen.** Die Offline-Vorbereitung schreibt die Tiles des Routen-Korridors jetzt direkt in den Tile-Cache (statt nur auf die Service-Worker-Interception zu setzen) – das funktioniert auch beim ersten Aufruf, bevor der Service Worker die Seite kontrolliert. Zusätzlich werden auch die Nah-Zoomstufe (Zoom 16) abgedeckt und das Cache-Budget erhöht, sodass die Route auch ohne Netz sichtbar bleibt.
- **Querformat auf Smartphones: größere, besser lesbare Karten-Bedienelemente.** Im kurzen Querformat werden die Karten-Knöpfe (Route, Norden, Fahrtrichtung, …) nicht mehr stark verkleinert, sondern in einer umbrechenden Reihe mit fingerfreundlicher Größe angeordnet.

- **Live-Tracking: überarbeitete Fahrzeug-Stati & eigener „Status"-Reiter.** Die Kurz-Stati zur Kommunikation zwischen Fahrzeugen und Konvoiführung liegen jetzt in einem eigenen Reiter „Status" (neben „Fahrzeuge" und „Zeitplan"). Neue Statuswerte mit fester Farbcodierung: **Geplant** (grau, Standard), **Unterwegs** (blau – wird automatisch gesetzt, sobald ein Fahrzeug gewählt wird bzw. sendet), **Angekommen** (grün – automatisch beim Eintreffen im Zielradius oder manuell), **Technischer Halt** (gelb – mit Dringlichkeit Standard/Dringend/Sehr dringend) und **Ausfall/Technische Störung** (rot – Stufen „Totalausfall, sofort halten" und „eingeschränkt, in Sicherheit fahren"). Die Fahrzeug-Kennzeichnung in der Liste bleibt erhalten, spiegelt aber die neuen Status-Farben wider; auch die Kartenmarker färben sich entsprechend. Migration `0025`.
- **In-App-Alarm bei Technischem Halt & Ausfall.** Fordert ein Fahrzeug einen technischen Halt an oder meldet einen Ausfall, erhalten alle verbundenen Tracking-Clients (insb. die Konvoiführung) sofort einen Alarm-Banner mit Fahrzeug, Dringlichkeit/Schweregrad und optionalem Grund – inklusive Signalton und Vibration. Im „Status"-Reiter werden die Meldungen gesammelt und können quittiert werden.
- **Drehbare Karte & Fahrtrichtungs-Pfeile.** Die Karte lässt sich frei drehen; ein „Norden"-Knopf richtet sie wieder nach Norden aus, „Fahrtrichtung" dreht die Karte beim Verfolgen des eigenen Fahrzeugs in Fahrtrichtung (Heading-up). Die Fahrzeug-Pfeile zeigen jetzt die echte Fahrtrichtung – auch bei gedrehter Karte – statt fest an einer Himmelsrichtung zu kleben.
- **Zeitplan mit Verspätungs-Prognose.** Der Zeitplan-Reiter schätzt aus der Position des vordersten Fahrzeugs entlang der Route die aktuelle Verspätung des Konvois und zeigt je Wegpunkt eine Live-Prognose (pünktlich / +X Min / Vorsprung).
- **Querformat & einklappbares Seitenmenü.** Auf Handys und Tablets greift der einklappbare Menü-Modus jetzt auch im Querformat; zusätzlich lässt sich das Seitenmenü auf Desktop/Tablet zu einer schmalen Leiste einklappen, um die Karte zu maximieren.
- **Fahrer-Freigabe-Links (ohne Login Position senden).** Beim Teilen lässt sich jetzt wählen, ob ein Tracking-Link **„Nur ansehen" (Viewer)** oder **„Fahrer"** ist. Über einen Fahrer-Link können Empfänger ohne Anmeldung ein Fahrzeug auswählen und dessen GPS-Position sowie Status (inkl. Technischer Halt / Ausfall mit Alarm an die Konvoiführung) senden – ideal für Fahrer ohne eigenen Account. Die Position wird per WebSocket übertragen (Fallback: Position per Karten-Tippen), ein gewähltes Fahrzeug springt automatisch auf „Unterwegs". Fahrer-Links sind über den Slug autorisiert; ein Passwortschutz wird empfohlen und ist im Teilen-Dialog wählbar. Die Link-Liste zeigt Typ (Viewer/Fahrer) je Link.

---

## [1.0.0] – 2026-06-09

Erste stabile Veröffentlichung für die breite Verteilung. Diese Version bündelt
die seit 0.8.5 hinzugekommene Sicherheits- und Datenschutz-Härtung
(Audit-Log, Brute-Force-Schutz, Passwort-Policy mit Breach-Check,
JWT-Revocation, MFA-Verschlüsselung at-rest, CSP, Security-Header,
CORS-Lockdown), das org-fähige Leitstellen- und Vorschlags-System, die
DSGVO-Funktionen (Datenexport/-löschung, Retention-Container,
Backup/Restore-Skripte) sowie zahlreiche Updater- und Stabilitäts-Fixes zu
einem produktionsreifen Stand.

### Fixed

- **Updater – Selbst-Neustart-Race-Condition behoben.** Der Updater rief intern `docker compose up -d updater` auf, um sich nach jedem Update neu zu erstellen — der orchestrierende Compose-Client wurde dabei beim eigenen Stopp gekillt, sodass der neue Container in `Created` hängen blieb (`<hex>_<project>-updater-1`). Stattdessen startet jetzt ein detachter Helper-Container (`docker:24-cli`) den Recreate, der den Tod des alten Updaters überlebt.
- **Updater – Stack-Datei wird wieder zurückgeschrieben.** `_update_stack_file` nutzte `docker cp $self:/tmp/foo $HOST_PATH`, was im CLIENT-Dateisystem (= im Updater-Container) endete, wo der Host-Pfad nicht existiert; Schreibversuch verlief still im Sand. Schreibt jetzt direkt zum Bind-Mount `/stack/docker-compose.yml`, mit Sidecar-Container als Fallback. Der `:ro`-Flag auf dem Bind-Mount in `docker-compose.yml` wurde entfernt.
- **Updater – pullt sich jetzt selbst.** Bisher wurden alle Service-Images außer dem Updater gepullt — neue Updater-Image-Versionen kamen so nie an. `do_update` pullt jetzt alle Services inkl. Updater; nur das Recreate des Updaters bleibt dem Helper überlassen. Damit verteilen sich zukünftige Updater-Bugfixes automatisch.
- **Updater-Image auf aktuelles `docker:cli` gehoben.** Das Basis-Image war auf dem EOL-Stand `docker:24-cli` gepinnt, dessen mitgeliefertes Docker-CLI-Binary mit einer alten Go-Runtime gebaut war und fixbare HIGH/CRITICAL-Go-CVEs enthielt — der neue Trivy-Container-Scan (T10) blockierte dadurch `main`. `FROM docker:cli` zieht das aktuelle, mit gepatchtem Go gebaute Image.

### Added

- **Audit-Log erweitert (Konvoi & Share-Links).** Das Security-Audit-Log erfasst jetzt zusätzlich **Konvoi-/Marschbefehl-Änderungen** (Anlegen, Ändern – inkl. Liste der geänderten Felder –, Löschen, auch Teilverbände) sowie **Share-Link-Erstellung und -Widerruf** (Slug, Scope, ob passwortgeschützt; ohne das Passwort selbst). Damit sind operative Planungsänderungen lückenlos nachvollziehbar (ISO 27001 A.8.15, T1).
- **Container-Image-Scanning (Trivy).** Neuer blockierender CI-Job `container-scan` prüft die gebauten Backend-, Frontend- und Updater-Images mit Trivy auf HIGH/CRITICAL-Schwachstellen mit verfügbarem Fix (`--ignore-unfixed`). Zusammen mit dem bereits blockierenden `dependency-audit` (`pip-audit`/`npm audit`) und einem in `SECURITY.md` dokumentierten **Patch-SLA** je Schweregrad schließt das ISO-27001-Control A.8.8 (T10).
- **Leitstellen-Tabelle: Suche, Sortierung & Bundesland-Gruppierung.** Über der Leitstellen-Tabelle (beide Portale) gibt es jetzt ein Suchfeld (Name/Anrufgruppe/Organisation/Status/Bundesland) und sortierbare Spaltenköpfe. Standardmäßig sind die Einträge nach **Bundesland** gruppiert (ein-/ausklappbar) — abgeleitet aus den Kreisschlüsseln (AGS) der Leitstelle —, damit die Liste auch bei vielen Leitstellen übersichtlich bleibt. Umgesetzt als wiederverwendbare Komponente `LeitstellenTable`.
- **Org-eigene Leitstellen & Vorschlags-Workflow.** Leitstellen sind jetzt org-fähig: Vom Superadmin angelegte Leitstellen sind **global** für alle Organisationen sichtbar; Organisationen (Org-Admins) können zusätzlich **eigene** Leitstellen anlegen, die zunächst nur für die eigene Organisation sichtbar sind und in deren Routen/Kanalwechsel einfließen. Über einen **„Senden"**-Button reicht ein Org-Admin eine Leitstelle als Vorschlag ein; der Superadmin sieht offene Vorschläge im Leitstellen-Reiter und kann sie **freigeben** (wird global & superadmin-verwaltet, Herkunft bleibt gespeichert), **ablehnen** (mit optionalem Grund, bleibt org-lokal) oder **bearbeiten**. Neue org-scoped API unter `/api/org/leitstellen`, Status-Workflow (`global`/`local`/`pending`/`rejected`) und Migration `0022`. Die Kanalwechsel-Berechnung berücksichtigt pro Route nur globale plus die org-eigenen Leitstellen.
- **Leitstellen-Übersichtskarte.** Im Leitstellen-Reiter (Superadmin- und Org-Portal) zeigt eine Übersichtskarte alle sichtbaren Leitstellengebiete (blau = global, rot = org-eigen) mit Hover-Infos zu Name/Anrufgruppe.
- **Bereits vergebene Landkreise markiert.** In der Landkreis-Auswahl werden Kreise, die schon einer anderen Leitstelle zugeordnet sind, grau markiert (Tooltip „bereits vergeben an …"); sie bleiben anklickbar. Die ausgewählten Kreis-Schlüssel werden je Leitstelle gespeichert.
- **Leitstellen-Gebiet per Landkreis-Klick.** Im Dialog „Neue Leitstelle / Leitstelle bearbeiten" lässt sich das Zuständigkeitsgebiet jetzt zusätzlich zum freien Polygon-Zeichnen auch durch Anklicken ganzer Landkreise/kreisfreier Städte definieren (Button „🗺 Landkreis wählen"). Mehrere Kreise können kombiniert werden und werden serverseitig zu einem zusammenhängenden Gebiet verschmolzen (innere Grenzen verschwinden — wichtig für die Kanalwechsel-Berechnung). Die Kreisgrenzen werden offline aus einer gebündelten, vereinfachten GeoJSON-Datei geladen (`frontend/static/geo/landkreise.geojson`, Daten © GeoBasis-DE / BKG, dl-de/by-2-0). Der GeoJSON-/KML-Import dissolviert nun ebenfalls mehrere Polygone in einer Datei.
- **Backup-/Restore-Skripte.** `scripts/backup.sh` (PostgreSQL-Dump + Upload-/TLS-Volumes + Prüfsummen + Retention) und `scripts/restore.sh`; dokumentiert in `docs/backup-restore.md` inkl. Verschlüsselung-at-rest-Leitfaden (LUKS/Cloud-Volumes, Backup-Verschlüsselung, Schlüsselverwaltung).
- **Content-Security-Policy.** MapLibre-/OpenStreetMap-taugliche CSP in beiden Caddyfile-Quellen (Env-Modus + Setup-Wizard), zusätzlich zu den bestehenden Security-Headern. Standardmäßig **Report-Only** (bricht die Karten-UI nicht); per `CSP_ENFORCE=true` erzwingbar.
- **Security-Audit-Log.** Append-only Protokoll sicherheitsrelevanter Ereignisse (Login-Erfolg/-Fehlschlag, MFA-Aktivierung/-Deaktivierung, Passwortänderung/-Reset, Benutzer-/Org-Anlage und -Löschung, Lizenzaktivierung) inkl. Akteur, Ziel, IP und User-Agent. Einsehbar für Superadmins unter `GET /api/admin/audit-log` (Filter nach Aktion). Neue Migration `0018`.
- **Brute-Force-Schutz.** In-Process-Rate-Limiting auf `/api/auth/login`, `/api/auth/mfa/verify` und `/api/auth/password-reset` (HTTP 429 mit `Retry-After`). Login/MFA zählen nur Fehlversuche, sodass erfolgreiche Logins nicht bestraft werden.
- **Einheitliche Passwort-Policy + Breach-Check.** Mindestens 10 Zeichen sowie Buchstaben und Ziffern; zusätzlich Abgleich gegen die Have-Ich-Been-Pwned-Range-API (k-Anonymity, fail-open bei fehlender Netzanbindung). Konsistent in Registrierung, Passwortänderung und Admin-Benutzerverwaltung. Abschaltbar über `PASSWORD_BREACH_CHECK_ENABLED=false`.
- **Dependency-Scanning.** `.github/dependabot.yml` (pip/npm/GitHub-Actions/Docker) sowie ein CI-Job `dependency-audit` (`pip-audit` + `npm audit`), zunächst advisory.
- **Datenaufbewahrung (Retention).** Neuer `retention`-Container purgt periodisch Live-Positionen (>24 h), Audit-Log-Einträge (>365 Tage) und widerrufene Share-Links (>30 Tage); Fristen über `RETENTION_*` konfigurierbar, jeder Lauf wird im Audit-Log vermerkt (`services/retention.py`, `app.jobs.retention`).
- **Betroffenenrechte (DSGVO Art. 15/17).** `GET /api/admin/users/{id}/export` liefert alle personenbezogenen Daten als JSON (ohne Geheimnisse); `DELETE /api/admin/users/{id}/data` löscht den Benutzer samt abhängiger Daten und **pseudonymisiert** den Audit-Trail (statt ihn zu löschen). Im Admin-Portal (Benutzer bearbeiten → „Datenschutz") als Buttons **Daten exportieren** / **Daten löschen** verfügbar.
- **Detailplan Retention & Betroffenenrechte.** `docs/iso-t5-retention-plan.md` (T5/T5b).
- **Security-Header (Caddy).** `Strict-Transport-Security`, `X-Content-Type-Options`, `X-Frame-Options`, `Referrer-Policy` und `Permissions-Policy` werden ausgeliefert; `Server`-Header entfernt.
- **`security.txt` & `SECURITY.md`.** Vulnerability-Disclosure-Kontakt unter `/.well-known/security.txt`.
- **ISO-Zertifizierungs-Bewertung.** `docs/iso-certifications-review.md` mit Normen-Priorisierung und code-gestützter Gap-Analyse.
- **Host-Watchdog (systemd-Timer).** `scripts/install.sh` installiert einen `convoyplan-updater-watchdog.timer`, der alle 2 Minuten verwaiste Updater-Container aufräumt und einen fehlenden/abgestürzten Updater neu startet. Defense-in-Depth gegen zukünftige Self-Restart-Probleme. Wird auf Systemen ohne systemd übersprungen.

### Changed

- **Superadmin-Login in `/admin` integriert.** Die separate Route `/login` wurde entfernt; `/admin` ist jetzt self-gated: nicht angemeldete Aufrufe zeigen direkt die Anmeldemaske (inkl. MFA und Passwort-vergessen) und leiten nach erfolgreichem Login ohne Umweg ins Portal durch. Im Superadmin-Portal gibt es jetzt einen **Abmelden**-Button.

### Security

- **JWT-Revocation (Sitzungsentzug).** Tokens tragen eine `token_version`, die gegen den DB-Stand geprüft wird. Bei Passwortänderung, Passwort-Reset (Self & Admin) und MFA-Reset wird die Version erhöht — alle bestehenden Tokens der betroffenen Person werden dadurch ungültig. Die Selbstbedienungs-Passwortänderung erhält automatisch ein frisches Token, bleibt also eingeloggt.
- **MFA-Secret verschlüsselt at-rest.** TOTP-Secrets werden mit Fernet verschlüsselt gespeichert (Schlüssel aus `MFA_ENCRYPTION_KEY` oder aus `JWT_SECRET` abgeleitet). Bestehende Klartext-Secrets bleiben lesbar und werden bei der nächsten MFA-Einrichtung verschlüsselt.
- **Fail-Closed bei unsicherem `JWT_SECRET`.** Im Produktionsmodus (`APP_ENV=production`, Default) verweigert das Backend den Start, wenn `JWT_SECRET` leer, der Platzhalter-Default oder kürzer als 32 Zeichen ist. Für lokale Entwicklung mit `APP_ENV=development` deaktivierbar. Von den Installern generierte Secrets (`openssl rand -hex 32`) erfüllen die Anforderung bereits.
- **CORS-Lockdown in Produktion.** Statt `*` fällt CORS in Produktion auf die eigene App-Origin (`APP_BASE_URL`) zurück; eine explizite Allowlist ist über `CORS_ORIGINS` setzbar. `*` nur in Entwicklung bzw. bei expliziter Konfiguration (mit Warnung).

### Migration

Bestehende Installationen mit alter, kaputter Updater-Version können sich nicht selbst auf die fixe Version aktualisieren (der kaputte Code ist der Code, der das Update macht). Einmalig zur Recovery auf dem Host ausführen:

```bash
curl -fsSL https://convoyplan.de/install.sh | bash
```

Das ruft den Update-Modus auf: räumt verwaiste Updater-Container auf, zieht alle Images (inkl. Updater), recreatet den Stack mit der neuen Compose-Datei und installiert den systemd-Watchdog. Danach läuft alles automatisch.

---

## [0.8.5] – 2026-05-28

### Added

- **Multi-Tenancy / Org-System** – vollständige Mandantenfähigkeit: jede Organisation erhält einen kurzen HiOrg-Code (4–8 Zeichen) als URL-Slug (`/[org-code]/`); Org-Guard-Layout schützt alle org-spezifischen Routen; org-spezifische Login-Seite mit eigenem Branding; `orgStore` mit persistentem Slug und org-bewusstem API-Client.
- **Superadmin: Org anlegen** – Superadmins können direkt im Admin-Panel neue Organisationen erstellen und Benutzer Organisationen zuweisen; Org-Zuordnung im Benutzer-Bearbeiten-Modal.
- **Org-Admin-Panel** – neuer Bereich `/[org-code]/admin/` mit Mitglieder-Tab (Rollen verwalten, Mitglieder einladen) und Export-Tab in der Hauptnavigation.
- **MFA (TOTP)** – Zwei-Faktor-Authentifizierung per TOTP (z. B. Google Authenticator); Einrichtung und Verwaltung im Org-Admin-Panel; SSE-Reconnect mit exponentialem Backoff.
- **SMTP-Service & Passwort per E-Mail** – integrierter SMTP-Dienst; Passwörter können direkt per E-Mail an Benutzer versandt werden; separate Schaltflächen „Passwort generieren" und „E-Mail senden" pro Benutzer im Admin-Panel.
- **GitHub-Token im Superadmin-Panel** – `GITHUB_TOKEN` für authentifizierten Update-Fetch direkt in der Admin-UI konfigurierbar, kein Neustart erforderlich.
- **Live-Update-Log-Terminal** – Echtzeit-Ausgabe des Updater-Prozesses im Browser via SSE; sofortiges Feedback nach Update-Trigger; SSE-Endpoint mit Caddy `flush_interval -1` für verlustfreies Streaming.
- **GIT_SHA im Backend** – der aktuell installierte Commit-SHA wird beim Build eingebettet und in der Updater-Statusanzeige angezeigt.

### Changed

- Plan-Routen und Admin-Routen vollständig unter den Org-Scope verschoben (`/[org-code]/plan/…`, `/[org-code]/admin/`); alte Pfade `/plan` und `/admin` leiten automatisch um.
- Startseite (`/`) ist jetzt öffentlich zugänglich; zeigt einen Org-Code-Hinweis für bestehende Benutzer.
- Setup-Wizard Schritt „Erste Organisation" legt slug-basierte Org beim Erststart an.
- Fahrzeug-Datenbankmodell direkt über `org_id`-Spalte an Org gebunden statt über Benutzer-Join (schnellere Queries, korrekte Isolation).
- Org-Login-Seite und Org-Code-Startseite verwenden das jeweilige Org-Branding.

### Fixed

- **Updater – `STACK_FILE_PATH` nie in `.env` geschrieben** – der Updater konnte den Stack nicht neu starten, weil die Variable fehlte; wird jetzt beim Start via Docker-Labels exportiert und korrekt in die Umgebung übergeben.
- **Updater – Self-Healing** – der Updater erkennt fehlgeschlagene Starts und fährt den Stack kontrolliert neu hoch; Installer unterstützt jetzt auch Update-Mode für bestehende Installs.
- **install.ps1** – falsche Image-Namen und fehlende Updater-Umgebungsvariablen korrigiert; Updater-Image in Release-Workflow und CI-Build-Check aufgenommen.
- **SSE-Streaming hinter Caddy** – `flush_interval -1` am Update-Log-Endpoint gesetzt; Terminal gibt innerhalb von 10 Sekunden nach Trigger erstes Feedback.
- **Org-Isolation bei Fahrzeugen** – Cross-Org-Vehicle-Assignment durch Rollen-Enum-Validierung verhindert; Single-Query-Isolation wiederhergestellt.
- **Superadmin-Panel** – `/admin` nach Multi-Tenancy-Merge wieder erreichbar; Login-Redirect-Logik korrigiert.
- **SSR-Guards** – `orgStore` localStorage-Methoden mit SSR-Guards abgesichert.
- Migration 0013 mit Guards gegen Teilausführung und korrigierter Revision-ID.
- Tabellenlayout im Admin-Panel nach Spaltenänderungen korrigiert.
- Doppelter Tagline auf der Login-Seite entfernt.

---

## [0.5.3] – 2026-05-26

### Fixed

- **Lizenzvalidierung schlug immer fehl** – der Lizenzmanager kodiert das Ablaufdatum als `"exp"` (JWT-Konvention); das Backend las nur `"expires"` → leerer String → Lizenz galt immer als abgelaufen. Beide Feldnamen werden jetzt akzeptiert; Fallback auf Unix-Timestamp (integer) ergänzt.

---

## [0.5.2] – 2026-05-26

### Fixed

- **Leitstellen konnten nicht geladen werden** – `GET /api/leitstellen` (ohne Trailing Slash) löste einen FastAPI-307-Redirect aus; hinter Caddy enthielt der `Location`-Header `http://` statt `https://`, was der Browser als Mixed Content blockierte. Frontend-API-Calls auf `/api/leitstellen/` und `/api/leitstellen/` (POST) korrigiert.

---

## [0.5.1] – 2026-05-24

### Added

- **Demo-Modus** – ohne gültigen Lizenzschlüssel startet die App im Demo-Modus: Lesezugriffe (GET) sind uneingeschränkt möglich, schreibende Operationen (POST/PUT/PATCH/DELETE) werden mit HTTP 402 abgewiesen.
- **Lizenzaktivierung über Admin-UI** – neuer Abschnitt im Admin-Tab „System": zeigt die Instanz-UUID (mit Kopieren-Button) und ein Eingabefeld für den Lizenzschlüssel; nach erfolgreicher Aktivierung wird der Middleware-Cache ohne Serverneustart zurückgesetzt.
- **Lizenzschlüssel-Persistenz in DB** – der eingegebene Schlüssel wird in `system_settings` (`license.key`) gespeichert und überlebt Neustarts; Auflösung in der Reihenfolge: Env-Variable `LICENSE_KEY` → DB-Eintrag.
- **`POST /api/license/activate`** – neuer Superadmin-Endpoint: validiert, speichert und setzt den Middleware-Cache atomar.
- **`GET /api/license/status`** – gibt jetzt zusätzlich `demo_mode` und `key_source` zurück.

### Added (continued)

- **Installer-Scripts** – interaktive One-liner-Installatoren für Linux (`install.sh`) und Windows (`install.ps1`); prüfen Voraussetzungen, fragen Domain/E-Mail/Datenbankpasswort/OSM-Region, generieren `JWT_SECRET` automatisch und starten den Stack.
- **Lizenzmodell (AGPL-3.0 + Dual-Lizenz)** – Demo-Modus und eine Produktivinstallation dauerhaft kostenlos; `COMMERCIAL_LICENSE.md` und `CLA.md` dokumentieren kommerzielle Optionen und Contributor-Bedingungen.
- **CLAUDE.md** – Cross-Repo-Sync-Anweisungen für Installer-Scripts zwischen App- und Website-Repo.

### Fixed

- Backend- und Frontend-Versionsstring auf `0.5.0` korrigiert (war irrtümlich auf `0.4.0` bzw. `0.0.1` geblieben).
- CI-Lizenzschlüssel-Abhängigkeit entkoppelt: `conftest.py` setzt den Middleware-Cache vor Testbeginn, damit Tests nach Keypair-Rotation nicht fehlschlagen.

---

## [0.5.0] – 2026-05-18

### Added

- **Organisations-Rollenmodell** – feingranulare Zugriffskontrolle auf Konvoi- und Fahrzeugendpoints (`get_convoy_access`, `get_vehicle_access`). Lesen ab Beobachter-Rolle, Schreiben ab Fahrer- bzw. Planer-Rolle; WebSocket-Handler prüft Konvoi-Zugehörigkeit und Fahrer-Rolle für Positionsschreibzugriff.
- **GPX/GeoJSON-Import** – Parser-Service für GPX-Tracks und GeoJSON-FeatureCollections; REST-Endpunkte `POST /api/convoys/{id}/import/gpx` und `.../geojson`; Import-UI im Export-Tab der Planungsseite mit Datei-Upload und Reset.
- **Leitstellen** – vollständiges CRUD-Datenmodell (`Leitstelle`, GeoJSON/KML-Grenzimport); Admin-Tab mit Polygon-Zeichnung direkt auf der Karte; automatische Berechnung von Kanalwechseln beim Routingdurchlauf; Anzeige im Zeitplan-Tab, Marschbefehl-Modal und PDF-Export.
- **Branding-System** – CSS Custom Properties für alle Markenfarben; Branding-API (`GET/PUT /api/admin/branding`) mit Logo-Upload und persistentem `BrandingConfig`-JSON; Branding-Tab im Admin-Panel mit Live-Vorschau; Branding-Schritt (Schritt 3) im Setup-Wizard.
- **Design-Token-System und Dark/Light-Theme** – vollständiges Token-Set (Farben, Typografie, Abstände, Radien, Schatten) mit CSS-Variablen; `ThemeStore` mit `localStorage`-Persistenz und SSR-Guard; Theme-Toggle in der Seitenleiste; Token-Migration für Plan-, Admin-, Tracking-, Login- und Share-Seiten.
- **Auto-Updater** – separater Docker-Container `updater` mit Git-Poll-Schleife (5-Minuten-Intervall); authentifizierter Fetch via `GITHUB_TOKEN`; `git reset --hard` für saubere Deploys; schreibt `status.json` auf gemeinsames Volume; reagiert auf manuelles Trigger-Flag.
- **Update-Status-Admin-UI** – neuer Tab "System" im Admin-Panel zeigt letzten Check-Zeitstempel, aktuellen und verfügbaren Commit-SHA sowie Update-Status; Schaltfläche zum manuellen Auslösen eines Updates via `POST /api/admin/trigger-update`.
- **Konvoi-Einstellungen bearbeiten** – bestehende Konvois können nach der Erstellung vollständig editiert werden (Name, Beschreibung, Start-/Endzeit, Geschwindigkeitsprofile).

### Changed

- Fahrzeugliste zeigt alle Org-Mitglieder (nicht nur Owner); Lese- und Schreibzugriff durch Rollen-Guards gesteuert.
- Seitenleiste der Planungsseite komplett auf Design-Tokens umgestellt; theme-bewusste Hintergrundfarbe.
- Tracking-Ansicht auto-zoomt beim Laden auf die berechnete Route.
- `docker-compose.yml`: `updater`-Service mit `update_status`-Volume; `GITHUB_TOKEN` wird an Backend weitergegeben.
- Backend-Version auf `0.5.0` erhöht.

### Fixed

- Backend-Bind-Mount entfernt; Code läuft im Produktionsbetrieb ausschließlich aus dem gebauten Image.
- `toggleTheme` mit SSR-Guard für `localStorage`-Zugriff abgesichert.
- Kanalwechsel-Geometrie-Binding und MultiPolygon-Handling korrigiert.
- Branding-Response-Typ korrekt gecastet.
- `mapMode` in MapView-Click-Handler via `get()` für Svelte-5-Kompatibilität gelesen.
- CSS-Variablen beim Tab-Wechsel wiederhergestellt; Branding-Formular nach Speichern synchronisiert.
- Expliziten Compose-Projektnamen gesetzt, um Workspace/marschplan-Namenskonflikt zu vermeiden.
- `git safe.directory` für gemounteten Workspace im Updater-Container gesetzt.
- Updater-Skript gegen Self-Kill bei laufendem Compose-Neustart abgesichert.

---

## [0.4.0] – 2026-05-07

### Added

- **First-run Setup Wizard** – browser-based wizard at `/setup` creates the superadmin account, configures the server domain and SSL mode (Let's Encrypt, custom certificate, or internal self-signed) in three steps. Setup is only accessible before any superadmin exists; the app redirects automatically on first start.
- **Caddy reverse proxy** – Caddy 2 replaces plain HTTP serving. Handles TLS termination, automatic Let's Encrypt certificates, and WebSocket proxying. Admin API at `:2019` enables live config reload without container restarts.
- **SSL certificate upload** – custom PEM certificates can be uploaded directly in the setup wizard via file picker; stored on a named Docker volume shared with Caddy.
- **Live Caddy reload** – `POST /api/setup` writes the Caddyfile and reloads Caddy via its admin API immediately, no container restart required. Config persists across restarts via the shared volume.
- **Admin API** – `GET/PATCH /api/admin/users` for superadmin user management including activation, deactivation, and role changes.
- **Self-demotion guard** – superadmins cannot remove their own superadmin status or deactivate themselves.
- **Setup atomicity** – PostgreSQL advisory lock prevents concurrent setup requests from creating duplicate superadmins.
- **Three-tier RBAC** – superadmin / org-admin / user roles with consistent `_get_org_admin` helper used across all organisation endpoints.
- **`system_settings` table** – migration `0008_settings` stores domain, TLS mode, and ACME email from the setup wizard.
- **`stack.yml`** – production Compose file with all services including Caddy and shared certificate volume.
- **`.env.example`** – complete reference for all production environment variables.

### Changed

- Superadmin account is now created via the setup wizard instead of environment variables (`SUPERADMIN_EMAIL` / `SUPERADMIN_PASSWORD` removed).
- WebSocket URL in tracking store uses `window.location.host` instead of hardcoded `:8000`, routing correctly through Caddy in production.
- `docker-compose.yml`: `cert_uploads` named volume replaces `${CERT_DIR}` bind-mount for Caddy; `caddy` service added with environment-variable-based Caddyfile generation as fallback on first start.
- Layout redirect sequences setup-status check before auth redirect, eliminating flash of `/login` on fresh installs.
- Backend version bumped to `0.4.0`.

### Fixed

- Organisation invite form initialisation: `orgInviteForm` initialised in `toggleOrgExpand` instead of inline assignment-as-expression in `bind:value`.
- Invite error cleared on successful invite submission.
- `organizations.py` `invite_member` now uses `_get_org_admin` for consistent owner-level check.
- `key.pem` written with `chmod 0o600` for correct file permissions.
- Caddy `adapt` response correctly unwraps `{"result": ..., "warnings": [...]}` envelope before posting to `/load`.
- `SystemSetting.value` uses `server_default=""` (not `default=""`) for correct DB-level default.

---

## [0.3.0] – 2026-05-06

### Added

- **Dashboard overlays** – weather widget, Overpass road-closure overlay, and status bar shown directly on the planning map.
- **Responsive layout** – mobile-first sidebar and map layout with collapsible panels.
- **Routing improvements** – via-point reordering via drag-and-drop, route recalculation on waypoint changes.
- **Waypoint management** – full CRUD for waypoints including stop type, dwell time, and notes; reorderable list.

### Changed

- Convoy planning page reorganised into a tabbed sidebar layout.

---

## [0.2.0] – 2026-05-05

### Added

- **Convoy wizard** – step-by-step wizard for creating a new convoy: name, vehicles, start/end points, waypoints, speed settings.
- **Rebrand to MarschPlan / ConvoyPlan** – updated branding, logo, and colour scheme across frontend and documentation.
- **Sub-convoy support** – convoys can have a parent convoy for multi-echelon march planning.
- **Share tokens** – read-only public link for convoy routes without login.

---

## [0.1.0] – initial

### Added

- FastAPI backend with SQLAlchemy async + Alembic migrations (PostgreSQL 15 + PostGIS).
- SvelteKit frontend with Svelte 5 runes (`$state`, `$effect`, `$derived`).
- JWT authentication (register, login, token refresh).
- Vehicle CRUD with callsign, plate, dimensions, weight, fuel type.
- Convoy CRUD with vehicle assignment.
- GraphHopper routing engine (self-hosted, OSM-based).
- Waypoint types: start, stop, checkpoint, fuel stop.
- Automatic schedule calculation (departure/arrival times, speed-dependent).
- Route export: GPX, JSON, PDF (march order).
- Live tracking via WebSocket + browser Geolocation API.
- Vehicle status: planned, en route, arrived, delayed.
- GeoJSON Lage layers (upload, display, manage).
- Weather integration (Open-Meteo, no API key required).
- Overpass API integration for road closures and construction.
- Organisation / tenancy model with role-based membership.
- PWA manifest + Workbox service worker for offline tile caching.
- Capacitor configuration for Android/iOS native wrapper.
- Docker Compose setup with GraphHopper OSM pre-download.

[Unreleased]: https://github.com/RettTechSolutions/ConvoyPlan/compare/v1.0.0...HEAD
[1.0.0]: https://github.com/RettTechSolutions/ConvoyPlan/compare/v0.8.5...v1.0.0
[0.8.5]: https://github.com/RettTechSolutions/ConvoyPlan/compare/v0.5.3...v0.8.5
[0.5.3]: https://github.com/RettTechSolutions/ConvoyPlan/compare/v0.5.2...v0.5.3
[0.5.2]: https://github.com/RettTechSolutions/ConvoyPlan/compare/v0.5.1...v0.5.2
[0.5.1]: https://github.com/RettTechSolutions/ConvoyPlan/compare/v0.5.0...v0.5.1
[0.5.0]: https://github.com/RettTechSolutions/ConvoyPlan/compare/v0.4.0...v0.5.0
[0.4.0]: https://github.com/RettTechSolutions/ConvoyPlan/compare/v0.3.0...v0.4.0
[0.3.0]: https://github.com/RettTechSolutions/ConvoyPlan/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/RettTechSolutions/ConvoyPlan/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/RettTechSolutions/ConvoyPlan/releases/tag/v0.1.0
