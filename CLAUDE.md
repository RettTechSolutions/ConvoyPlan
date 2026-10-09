# ConvoyPlan — Claude Instructions

## Repos

| Repo | Zweck |
|---|---|
| **ConvoyPlan** (dieses Repo) — https://github.com/RettTechSolutions/ConvoyPlan | App (Backend, Frontend, Docker) |
| **convoyplan-website** — https://github.com/RettTechSolutions/convoyplan-website | Marketingsite (Astro) |

Weitere, nicht-öffentliche Repos und die Zuordnung lokaler Arbeitskopien stehen
in `CLAUDE.local.md` (nicht eingecheckt, siehe `.gitignore`).

## Installer-Scripts

`scripts/install.sh` (Linux) und `scripts/install.ps1` (Windows) sind die Quelle
der Wahrheit für die Installation. `https://convoyplan.de/install.sh` und
`https://convoyplan.de/install.ps1` sind Weiterleitungen auf die Raw-Dateien aus
diesem Repo — eine Änderung hier ist nach dem Push auf `main` sofort wirksam,
ein Sync in ein anderes Repo ist nicht nötig.

Die Weiterleitungen selbst liegen im Website-Repo; ihre Einrichtung ist in
`.github/repo-setup-checklist.md` beschrieben und nur für Maintainer relevant.

## Deployment

Die Produktivinstanz läuft über Docker Compose (`docker-compose.yml`); der
Updater in `docker/updater/` rollt neue Images aus. Die Marketingsite wird aus
dem Website-Repo heraus als statisches Astro-Build deployt.

### Images werden nur gebaut, wenn es einen Grund gibt

`graphhopper`, `updater` und `osmium` hängen nicht am Anwendungscode. Gebaut
wurden sie trotzdem bei jedem Lauf — und jeder Bau erzeugt einen neuen Digest,
weil `metadata-action` Commit-SHA und Zeitstempel als Label in die
Image-Konfiguration schreibt und die zum Digest gehört. Der Updater vergleicht
Image-IDs, sieht eine neue und tauscht den Container: bei GraphHopper mit
minutenlangem Routing-Ausfall für das erneute Laden des Graphen, im
Nightly-Kanal mehrmals täglich, ohne dass sich ein Byte geändert hätte.

`.github/actions/build-or-reuse/` entscheidet deshalb vor jedem dieser drei
Bauten. Gebaut wird bei geändertem Quelltext (Tree-Hash des Verzeichnisses,
liegt als `de.convoyplan.source-tree` im Image), bei bewegtem Base-Image
(Digest der letzten `FROM`-Zeile, `de.convoyplan.base-digest`) oder wenn das
veröffentlichte Image älter als `max-age-days` ist — das Auffangnetz für
Paketupdates, die den Base-Digest nicht bewegen. Sonst bleibt der bewegliche
Tag (`latest`/`beta`/`nightly`) stehen, wo er steht, und genau das ist der
Punkt: nur er wird auf den Installationen gezogen.

Zwei Folgen, die man kennen muss. Ein weiterverwendetes Image bekommt in einem
Release **keine** Versionstags — es zieht sie niemand, `_apply_channel_images`
in `update-images.sh` schreibt jede Angabe auf den Kanaltag um. Und es wird
nicht erneut signiert, weil `cosign` den Digest signiert und der unverändert
ist. Die Entscheidung selbst steht in `decide.sh`, getrennt von der
Registry-Abfrage, und wird von `tests/test_image_wiederverwendung.sh` ohne
Docker und ohne Registry geprüft.

### Der Routing-Graph und der Deploy

Zwei Dateien entscheiden hier, und man muss sie auseinanderhalten.
`.graph_fingerprint` (Region + Encoded Values + Abbiegeverbote) schreibt `graphhopper/
entrypoint.sh` **vor** dem Import — er sagt, *wofür* ein Graph gebaut wurde, und
belegt **nicht**, dass er fertig ist. `edges` legt GraphHopper erst bei einem
vollständigen Graphen an; das ist der Vollständigkeitsbeleg, und alle drei
Stellen benutzen inzwischen ihn.

Am 2026-09-19 fehlte diese Unterscheidung und das Routing war weg: Ein
Auto-Deploy (nightly, mehrmals täglich) traf einen laufenden Import und ließ
einen Torso zurück — Bruchstücke plus den `location_index` eines anderen
Graphen, dazu einen passenden Fingerprint. Der Entrypoint sah „Fingerprint
stimmt", ließ alles liegen, GraphHopper importierte 13 Minuten neu, las den
fremden Index und starb an `location index was opened with incorrect graph`.
`restart: unless-stopped` fing von vorn an.

Drei Stellen, jede mit eigenem Test:

- **`graphhopper/entrypoint.sh`** wirft ein Verzeichnis ohne `edges` weg und baut
  neu (`tests/test_entrypoint_graph_zustand.sh`). Der Wipe ist weiter
  `rm -rf "$GRAPH_DIR"/*` und fasst damit Punktdateien **nicht** an — auf
  `.staging`/`.old` verlässt sich der Regionswechsel; wer hier auf `find -delete`
  oder `dotglob` umstellt, löscht einem laufenden Wechsel den halb gebauten
  Graphen.
- **`docker/updater/graphhopper-deploy.sh`** nimmt den Dienst aus dem Deploy,
  solange er baut, und zieht ihn danach nach. Von **beiden** Updater-Varianten
  gesourct — dieselbe Begründung wie bei `region-hook.sh`. Gedeckelt durch
  `GH_IMPORT_GRACE` (4 h), sonst schnitte ein Container, der aus einem anderen
  Grund nie fertig wird, den Dienst dauerhaft von Updates ab.
  `tests/test_graphhopper_import_deploy.sh` prüft die Entscheidung ohne Docker
  und die Verdrahtung in `update-images.sh` mit.
- **`switch-region.sh`**, Notbremse in `_on_exit`: startet GraphHopper nur gegen
  ein Verzeichnis mit Fingerprint **und** `edges` (`test_switch_region.sh`,
  Fall 12b).

Ein vierter Leser kommt ohne Schreibrecht aus: die öffentliche Statusseite nennt
einen laufenden Neuaufbau als Grund für die Routing-Pause
(`app/services/graph_aufbau.py`, lesende Mounts). Sie verlässt sich darauf, dass der
Fingerprint **unmittelbar vor** dem Import geschrieben wird — seine Änderungszeit ist
der Beginn — und deckelt mit derselben Frist wie `GH_IMPORT_GRACE`. Wer den
Fingerprint woanders schreibt, zieht `tests/test_graph_aufbau.py` mit.

### Speicher: Import im Heap, Betrieb per MMAP

`graphhopper/entrypoint.sh` startet in **zwei Phasen**, wenn `GH_COMMAND=server`
und kein `edges` da ist: erst `import` mit `RAM_STORE` und nur `JAVA_OPTS`, dann
`server` mit `GH_DATAACCESS` (Standard `MMAP`) und zusätzlich
`GH_SERVER_JAVA_OPTS`. `-Xmx` in `JAVA_OPTS` bemisst also den **Import** — darauf
beziehen sich Installer, Wiki und der Regionswechsel (`region.py` erzeugt es aus
der RAM-Schätzung) —, im Betrieb liegt der Graph im Seitencache und die JVM
bleibt weit darunter. Das Dateiformat ist bei beiden Zugriffsarten dasselbe.
`GH_COMMAND=import` (Regionswechsel) bleibt einphasig mit `RAM_STORE`. Wer die
Server-Phase anders konfiguriert, setzt `GH_SERVER_JAVA_OPTS` komplett, nicht
ergänzend; die Vorgabe (Heap im Leerlauf zurückgeben, bei OOM beenden) steht nur
im Entrypoint.

### Abbiegeverbote: beide Profile mit `turn_costs`

Ohne `turn_costs` im Profil kennt GraphHopper **keine** OSM-Abbiegeverbote — bis
2026-10 war das bei `car` und `truck` der Fall. Gemeldet an der B 472 bei
Peißenberg (Anschluss WM 15): die Route nahm die Auffahrt regelkonform hinauf
und bog an ihrer Spitze per Haarnadel in die Gegenrichtung ab, über ein
`only_right_turn` hinweg. Sichtbar wurde es mit der Straßenpräferenz
„standard", weil die Strafe auf `TERTIARY` den Weg über die Rampen billiger
macht. `graphhopper/entrypoint.sh` setzt `turn_costs` deshalb für beide
Profile, und der Wert steht im Fingerprint: ein Graph ohne sie wird neu gebaut
(`test_entrypoint_graph_zustand.sh`, Fall 4b; die erzeugte Konfiguration prüft
`test_entrypoint_start_phasen.sh`, Fall 1b).

Das braucht **GraphHopper ≥ 10.2**. 9.1 bricht den Import mit `turn_costs` an
gültigen `no_entry`/`no_exit`-Relationen mit Via-Weg und mehreren from- oder
to-Wegen ab (`fromEdges and toEdges cannot be size > 1 at the same time`,
GraphHopper #3086/#3100). Solche gibt es in DACH; nach #594 kam auf 9.1 kein
Import mehr durch, und weil der Entrypoint den Torso danach wegräumt, drehte
der Container im Kreis. Die Fassung steht deshalb ebenfalls im Fingerprint
(`GH_VERSION` aus dem Dockerfile, Fall 4c): das Speicherformat wechselt
zwischen den Versionen, und einen fremden Graphen lädt GraphHopper nicht.
Wer `GH_VERSION` hebt, baut damit auf jeder Installation den Graphen neu.

**Kein CH.** Mit `turn_costs` wäre die Contraction Hierarchy für `car`
kantenbasiert — die teuerste Phase des Imports an Heap und Zeit, für einen
Nutzen nur bei „schnell" ohne Fahrzeughöhe (alles andere schickt ein Custom
Model und `ch.disable`). `profiles_ch` fehlt deshalb; jede Anfrage läuft
flexibel. Nicht im Fingerprint: ein fertiger Graph mit CH-Daten lädt weiter
(`test_entrypoint_start_phasen.sh`, Fall 1c). Wird „schnell" auf langen
Strecken zu langsam, ist LM (`profiles_lm`) der nächste Schritt, nicht CH.

### Die Wegpunktreihenfolge gehört dem Menschen

`order_index` ist die Wahrheit, und `calculate_route` leitet ihn **nicht** aus der
fertigen Route ab. Einmal tat sie es, und dabei schloss sich ein Kreis: die Punkte
gingen nach ihrer Lage entlang der *alten* Route in die Anfrage, und danach wurde
`order_index` aus der *neuen* zurückgeschrieben. Ein Umsortieren von Hand ging
zweimal verloren — es kam nie in die Anfrage hinein und wurde nach der Antwort
überschrieben; die Route blieb, wie sie war, die Liste sprang zurück.

Die Ausnahme sind die automatisch vorgeschlagenen Halte: das Frontend hängt
Technische Halte und Tankstopps ans **Ende** der Liste, obwohl sie in der Mitte
liegen, und ohne Einordnen führe der Konvoi an ihnen vorbei und wieder zurück
(der gemeldete Umweg von mehreren hundert Kilometern). Eingeordnet werden sie
anhand ihrer Projektion auf die **vorherige** Route — und nur einmal: danach
steht so ein Halt mitten in der Liste und ist ein Wegpunkt wie jeder andere.

Wer eingeordnet wird, sagt die Spalte `pending_placement` und **nicht** die
Position in der Liste (Migration `0046`). Zuerst wurde geraten — „der
zusammenhängende Lauf von `technical_stop` am Listenende" —, und das traf den
Normalfall, verschob aber auch einen Technischen Halt, den jemand bewusst als
*letzten* Wegpunkt gesetzt hatte. Die Marke kommt von der Herkunft: gesetzt beim
Anlegen eines Vorschlags (nur die beiden Stellen im Frontend setzen sie),
gelöscht, sobald der Wegpunkt einen Platz hat — durch die Routenberechnung,
durch Ziehen in der Liste oder durch ein ausdrücklich gesetztes `order_index`.
Dass sie **verfällt**, ist kein Detail: eine Marke, die bliebe, ließe denselben
Halt bei jedem Lauf erneut wandern, auch dorthin, wo ihn gerade jemand weggezogen
hat.

Die Entscheidung steht in `app/services/waypoint_order.py`, getrennt von Datenbank
und Routing-Dienst, und wird von `tests/test_wegpunkt_reihenfolge.py` ohne beides
geprüft — samt den drei Stellen, an denen die Marke verfällt. Der Backfill der
Migration steht aus demselben Grund als Funktion daneben und nicht in einer
`WHERE`-Bedingung (`tests/test_wegpunkt_platzierung_migration.py`, wie bei
`0039`): er entscheidet über Bestandsdaten.

Die Kilometrierung für den Zeitplan kommt weiter aus der Projektion, sortiert aber
nichts mehr um. Sie wird monoton gehalten (`cumulative_along_route`): wo die Route
ein Stück doppelt befährt, trifft die Suche nach dem nächsten Streckenpunkt sonst
die falsche Vorbeifahrt, und aus der negativen Teilstrecke wird eine rückwärts
laufende Ankunftszeit.

### Durchfahrtshöhen: gesperrt wird beim Routing, gezeigt wird danach

Das Custom Model in `services/routing.py` nimmt jede Kante mit `max_height` unter
dem höchsten Fahrzeug aus dem Graphen — das war schon immer so, aber still.
`services/durchfahrtshoehe.py` macht aus dem Path-Detail `max_height` die Liste
der Unterführungen, unter denen die Route trotzdem hindurchgeht, gespeichert in
`routes.durchfahrtshoehen` (Migration `0055`) wie der Kanalwechsel, gezeigt in
`DurchfahrtsHoehen.svelte` und im Marschbefehl.

Zwei Dinge, die man kennen muss:

- **GraphHopper rundet `max_height` auf 10 cm** (9.1 und 10.2, `MaxHeight.create`, Faktor
  0,1 mit `Math.round`): aus 3,85 m auf dem Schild werden 3,9 m im Graphen. Die
  Sperre `max_height < Fahrzeughöhe` kann deshalb ein Fahrzeug von 3,88 m unter
  ein 3,85-m-Schild schicken. Die Stufe `eng` (< 10 cm Spielraum) ist genau dafür
  da; die Sperre selbst ist unverändert.
- **`None` ist nicht `[]`.** `None` heißt „nicht ermittelt" (alte oder importierte
  Route), `[]` heißt „keine bekannte Beschränkung". Wer das zusammenlegt, behauptet
  bei jeder alten Route freie Fahrt.

Brücken **ohne** `maxheight` in OSM kennt GraphHopper nicht; gemieden werden sie
nicht. Gefunden werden sie nach der Berechnung in `services/bruecken.py`: Overpass
liefert alle `bridge=*`-Wege im 25-m-Korridor, gezählt wird, was die Linie
*kreuzt*. Das Frontend stößt die Suche an (`POST …/route/bruecken`), wie bei den
Tankstellen — die Berechnung soll nicht an einem fremden Dienst hängen. Ergebnis in
`routes.bruecken` (Migration `0056`), `None` = nicht gesucht; jede Neuberechnung setzt
es zurück, und ein Ergebnis zu einer inzwischen ersetzten Linie wird mit 409
verworfen. Drei Regeln, die man kennen muss:

- **Nicht exakt vergleichen.** Ob die Route über eine Brücke *fährt* oder nur an
  einem Knoten *anschließt*, wird mit Toleranzen (~2 m bzw. ~0,5 m) entschieden,
  nicht über die exakte Schnittmenge: GraphHopper und Overpass liefern dieselben
  OSM-Knoten, aber nicht zwingend bitgleich.
- **Bekannt ist bekannt.** Eine Kreuzung im Abschnitt eines Eintrags aus Stufe 1
  (über dessen `m`) steht nicht doppelt da.
- **Schnellstraßen zählen, nicht listen.** `routes.schnellstrassen` hält bei der
  Berechnung fest, wo `road_class` Autobahn oder Kraftfahrstraße ist; die Suche läuft
  später und hat das Detail nicht mehr.

Tests: `tests/test_durchfahrtshoehen.py`, `tests/test_bruecken_ohne_hoehe.py`,
`frontend/e2e/durchfahrtshoehen.spec.ts`. Anwenderdoku: `wiki/Konvoi-Planung.md`,
„Durchfahrtshöhen".

### Fahrzeugbelegung: ein Fahrzeug, ein Gerät

Wer ein Fahrzeug wählt, belegt es — am Server, für alle drei Oberflächen zugleich:
Fahrer-Link im Browser, Begleit-App (derselbe Kanal) und angemeldetes Tracking.
Gemeldet war: KdoW in der App gewählt, im Browser noch einmal wählbar; beide
schrieben in dieselbe Positionszeile. Der alte Schutz im Web („hat eine Position
= vergeben") galt nur dort, und eine Position bleibt liegen, wenn niemand mehr
sendet — das Fahrzeug war danach für immer ausgegraut.

Die Entscheidung steht in `app/services/belegung.py` (`Belegungen`, ohne Netz und
Uhr geprüft von `tests/test_fahrzeug_belegung.py`), die Verdrahtung in beiden
WebSocket-Handlern (`track_ws`, `tracking_ws`; am echten Kanal geprüft von
`tests/test_fahrzeug_belegung_kanal.py`). Ein Gerät weist sich mit `?client=`
aus; `belegen`/`freigeben` sind eigene Frames, jeder Frame für ein Fahrzeug hält
die Belegung, nach **fünf Minuten** ohne Frame wird sie frei. Ein
Verbindungsabriss gibt **nicht** frei — das Funkloch ist der Normalfall.
„GPS-Freigabe zurücksetzen" (`DELETE …/position` mit `suppress`) gibt sofort frei.

Drei Dinge, die man kennen muss:

- **Clients ohne `client` werden nie abgewiesen** (App-Fassungen aus dem Store),
  belegen aber, was sie senden. Und sie bekommen **keinen** der neuen
  Nachrichtentypen: `broadcast_belegung` geht nur an Verbindungen mit Kennung,
  weil der Store der angemeldeten Ansicht früher jede unbekannte Nachricht als
  Position las.
- **Im Speicher, nicht in der Datenbank** — wie die Verbindungen selbst in
  `tracking_manager`. Nach einem Neustart (Nightly deployt mehrmals täglich)
  belegt jedes Gerät sein Fahrzeug mit dem `belegen` nach dem Verbindungsaufbau
  neu; die Clients schicken es auf die `belegungen`-Nachricht hin.
- Die Gegenstellen sind `frontend/src/lib/tracking/belegung.ts` und in der
  Begleit-App `packages/track-api/src/belegung.ts` — dasselbe Protokoll, zwei
  Umsetzungen. Wer eine ändert, zieht die andere mit.
  `frontend/e2e/fahrzeug-belegung.spec.ts` hält die Zusagen an der Oberfläche fest.
  Anwenderdoku: `wiki/Live-Tracking.md`, „Ein Fahrzeug, ein Gerät".

### Aktionsseite: öffentlich, verzögert, vergröbert

Eine Organisation kann Konvois öffentlich zeigen (Hilfskonvois, Presse,
Bildschirm bei Veranstaltungen). Ausgeliefert wird die Seite **nicht** von
dieser Instanz, sondern von einer eigenen Anwendung im Repo
**Convoyplan-EventTracker**. Die holt `GET /api/public/aktion/{slug}` mit
ihrem Abruf-Token (`Authorization: Bearer`) einmal pro Minute ab. Damit sieht
die Einsatzinstanz den Andrang nie, und der EventTracker sieht nie eine
Echtzeitposition. Plan und Hintergrund:
`docs/superpowers/plans/2026-10-02-oeffentliche-aktionsseite.md`.

Drei Regeln, alle in `app/services/aktionsseite.py` und **nur** dort. Ein
Filter beim Empfänger ließe sich mit den Entwicklertools aushebeln:

- **Verzögert**: nur Punkte bis `jetzt − delay_minutes`; mindestens 60, auch
  als CHECK in der Datenbank.
- **Vergröbert, sobald der Konvoi steht** (20 min im Umkreis von 300 m oder
  keine Daten): feste Rasterzelle von etwa 10 km, die Linie endet 10 km davor.
  Die Verzögerung schützt keinen parkenden Lkw — ohne diese Regel stünde der
  Autohof die ganze Nacht metergenau auf der Seite. Fest gerastert statt
  verrauscht, weil sich Rauschen über viele Abrufe herausmitteln ließe.
- **Positivliste**: die Pydantic-Modelle in `api/routes/aktionsseite.py`,
  jedes mit `extra="forbid"`. Sie sind zugleich der Vertrag mit dem
  EventTracker; `tests/test_aktionsseite_felder.py` schreibt sie aus. Kein
  interner Konvoiname, keine Datenbank-Kennung, nichts aus dem Fahrzeug.

Unbekannt, abgeschaltet, abgelaufen oder falsches Token ergeben **dieselbe**
404. Das Token liegt nur als SHA-256 vor, sichtbar ist es einmal beim Anlegen
und beim Erneuern. Im Export fehlen Slug und Hash, wie beim Share-Link.

Der **Positionsverlauf** (`vehicle_position_trail`) entsteht nur für Konvois
an einer aktiven Seite (`services/positionsverlauf.py`). Ausgedünnt wird auf
einen Punkt pro Minute, bei stehendem Fahrzeug auf einen alle fünf Minuten;
die Retention löscht nach 45 Tagen. `aufzeichnen` steht an **jeder** Stelle,
die `VehiclePosition` schreibt — heute drei. Wer eine vierte baut, zieht den
Aufruf mit; `tests/test_positionsverlauf.py` prüft das am Quelltext und
schlägt sonst an.

Die Positionen tragen die **Serverzeit**. Puffert ein Gerät im Funkloch und
sendet später, landen die Punkte gestaucht am Ende der Linie.

### Tracker: das Gerät hängt am Fahrzeug, die Position gehört dem Konvoi

Ein festes Ortungsgerät (Repo **ConvoyPlan-Tracker**: Plan, Protokoll, Simulator,
später Firmware) sendet die Position seines Fahrzeugs ohne Zutun der Besatzung.
Das Datenmodell kennt aber keine Position je Fahrzeug, nur je `(convoy_id,
vehicle_id)`. Deshalb entscheidet die **Instanz**, ob gesendet wird, und sagt es
dem Gerät in jeder Antwort (`modus`): `senden` nur, solange das gekoppelte
Fahrzeug in einem Konvoi mit Status `active` oder `running` eingeplant ist
(E7 im Tracker-Plan), sonst `schweigen`. Das ist zugleich die Antwort auf die
Datenschutzfrage — ein Tracker ist keine Ortung rund um die Uhr. Steht das
Fahrzeug in zwei laufenden Konvois, bekommen beide die Position (E8 dort).

Die Regeln stehen in `app/services/ortungsgeraet.py`, geprüft ohne Datenbank
von `tests/test_tracker_geraete.py`; die Verdrahtung in `api/routes/geraete.py`
(zwei Router: `/api/geraete/*` für das Gerät, `/api/org/geraete` für den
Org-Admin). Vier Dinge, die man kennen muss:

- **Vierte Schreibstelle für `VehiclePosition`.** `tests/test_positionsverlauf.py`
  zählt sie mit; wer eine fünfte baut, trägt sie dort ein und ruft
  `positionsverlauf.aufzeichnen` mit. Auch `is_recently_cleared` („GPS-Freigabe
  zurücksetzen") und `planned → en_route` samt `alarm_quittung.zuruecksetzen`
  gelten hier wie am Fahrer-Link.
- **Gerätezeit, nicht Serverzeit.** Jeder Fix trägt seine GNSS-Zeit; mehr als
  120 s Zukunft oder älter als 24 h fällt weg, **je Fix**, nicht je Bündel. Die
  aktuelle Position wird nur ersetzt, wenn der Fix jünger ist
  (`on_conflict_do_update … where recorded_at < excluded.recorded_at`); der
  Verlauf bekommt jeden Fix mit seiner Zeit. Sonst wäre jede Tunnelfahrt ein
  Knäuel am Ende der Linie.
- **Code und Token nur als SHA-256**, wie beim Abruf-Token der Aktionsseite.
  Unbekannt, abgelaufen, verbraucht: dieselbe 404. Ein neuer Code macht das
  alte Token sofort ungültig; `aktiv=false` ebenso (401, das Gerät geht in
  *gesperrt*). Die Plansperre der Organisation (`org_plan.ist_gesperrt`) ergibt
  `schweigen` — der dritte Schreibweg zieht sie mit.
- **Die Belegung ist aufgeteilt, nicht erweitert** (E5 im Tracker-Plan,
  `services/positionsquelle.py`). Der Tracker belegt das Fahrzeug *nicht* —
  die Belegung (`belegung.py`) sagt weiter, welches Gerät der Besatzung Status,
  Stärke, Betriebsstoff und Quittung meldet. Die **Position** aber gehört dem
  Tracker, solange er sendet (ein Bündel in den letzten fünf Minuten, dieselbe
  Frist wie die Belegung): Alle drei Telefonpfade fragen vor dem Schreiben
  `positionsquelle.telefon_erlaubt`, verwerfen sonst und sagen es **nur dem
  Absender** (`position_abgelehnt`, nur mit Gerätekennung — der alte Store las
  Unbekanntes als Position). Fünf Minuten statt sofortigem Rückfall, weil ein
  Rückfall je Frame das Springen zurückbrächte, das die Belegung abgestellt hat;
  statt nie, weil ein toter Tracker das Fahrzeug nicht stumm machen darf. Die
  Führung **übersteuert** mit `PATCH …/vehicles/{id}/positionsquelle`
  (`ConvoyVehicle.tracker_uebersteuert_at`, Migration `0058`, in der Datenbank,
  weil ein Neustart die Entscheidung nicht aufheben darf): dann gilt das
  Telefon, Bündel des Trackers werden in diesem Konvoi verworfen, bis sie es
  zurücknimmt. `vehicle_positions.quelle` sagt der Karte, was vom Tracker kam;
  jede Schreibstelle setzt die Spalte ausdrücklich. Gegenstellen:
  `frontend/src/lib/tracking/positionsquelle.ts` und `packages/track-api` in der
  Begleit-App. Tests: `tests/test_positionsquelle.py` (Entscheidung ohne Uhr,
  dann REST, Tracker und Fahrer-Link am gestellten Kanal).

**Firmware** (`services/firmware_angebot.py`, E9 im Tracker-Plan): Die Ablage ist
ein statisches HTTPS-Verzeichnis je Kanal (`TRACKER_FIRMWARE_URL`, Vorgabe
`https://firmware.convoyplan.de`; `<kanal>/manifest.json` mit `version`, `sha256`,
`groesse`, `image`, optional `hardware`). Die Instanz holt das Manifest stündlich
(bei Ausfall bleibt der letzte Stand), lädt das Image **einmal** nach
`/uploads/firmware/`, prüft SHA-256 und Größe und bietet es in der Anweisung an —
nur neuer als der gemeldete Stand, nur passende Hardware, und die Adresse zeigt auf
**diese Instanz** (`GET /api/geraete/firmware/<kanal>/<version>.bin`, Gerätetoken,
`Range`). Nicht in die Ablage, weil ein Tracker mit IoT-SIM oft nur eine
Positivliste von Hosts erreicht und seine Instanz ohnehin darauf steht. Geliefert
wird nur die Version aus dem aktuellen Manifest; eine beliebige Version im Pfad
ließe sich sonst zum Laden fremder Adressen missbrauchen. In Tests zeigt
`conftest.py` die Ablage ins Leere, sonst fragte jedes `hallo` im Netz nach.
Die Referenz-Instanz im Simulator des Tracker-Repos tut dasselbe wie dieser Code;
wer das Protokoll ändert, zieht beide. Anwenderdoku: `wiki/Tracker.md`.

### Alarmquittung: die Führung quittiert am Server

Ein technischer Halt oder Ausfall löst `alert` aus; **quittiert** wird er seit
`0049` am Server und nicht mehr je Gerät. Die Regeln stehen in
`app/services/alarm_quittung.py`, die Prüfung in
`tests/test_alarm_quittung.py`, die Zusage an der Oberfläche in
`frontend/e2e/alarm-quittung.spec.ts`.

- **Die Quittung gehört einem Alarm**, erkannt an seinem Zeitstempel (`ts` im
  `alert` = `status_changed_at`, als Zeitpunkt verglichen, nicht als Text).
  **Jeder** Statuswechsel setzt sie zurück — wer eine neue Stelle schreibt, die
  `vehicle_status` setzt, ruft `alarm_quittung.zuruecksetzen(cv)` mit.
- `alarm_quittiert` geht über `broadcast_neu`, also **nur an Verbindungen mit
  Gerätekennung** (und an die Broadcast-Beobachter). Aus demselben Grund wie die
  Belegung: Der Store der angemeldeten Ansicht las früher jede unbekannte
  Nachricht als Position.
- Am Fahrer-Link wird `alarm_quittieren` **vor** der Belegung behandelt: Seine
  `vehicle_id` ist das alarmierende Fahrzeug, nicht das eigene. Wer quittiert
  hat, leitet der Server ab (Fahrzeug der Belegung, Name des Kontos), einem Text
  vom Client glaubt er nicht.
- Die Gegenstelle in der Begleit-App ist `packages/track-api` und
  `app/src/alerts/board.ts` im Repo Convoyplan-Companion; `hello` meldet die
  Fähigkeit als `alarm-quittung`.

### API-Docs (Swagger/OpenAPI)

`/docs`, `/redoc` und `/openapi.json` sind in Produktion **standardmäßig deaktiviert**
(404). Eine extern erreichbare Instanz sollte sie **per API-Key** absichern statt
offen zu schalten:

- **`DOCS_API_KEY=<geheim>`** (empfohlen): Docs sind erreichbar, aber geschützt.
  Der Browser-Einstieg läuft über `/docs`, das ohne gültiges Cookie ein
  Anmeldeformular zeigt; nach erfolgreicher Eingabe merkt ein HttpOnly-Cookie
  die Freigabe. Programmatischer Zugriff via Header `X-API-Key: <geheim>`.
- **`ENABLE_DOCS=true`**: Docs offen erreichbar (ohne Key) — nur für Dev/intern.

Ein `?key=…` im Query-String wird nicht akzeptiert. Siehe `backend/app/api/docs_ui.py`
(Türsteher, Formular, Cookie) und `backend/app/config.py` (`docs_api_key`, `enable_docs`).

### MCP-Server (KI-Schnittstelle)

`/mcp` stellt Konvois, Fahrzeuge, Wegpunkte, Routen und Status als
Model-Context-Protocol-Server bereit. **Standardmäßig aus** — abgeschaltet gibt
es `/mcp`, `/register` und die Protected-Resource-Metadaten nicht. `/authorize`,
`/token`, `/revoke` und die AS-Metadaten bleiben, solange der App-Client an ist
(siehe „Begleit-App" unten); MCP-Clients kommen dort trotzdem nicht weiter.

Der Schalter sitzt im Admin-Portal unter **System → KI-Schnittstelle** und wirkt
ohne Neustart; `MCP_ENABLED` ist nur noch der Ausgangswert (Datenbank schlägt
Umgebung, `app/services/mcp_config.py`). Er *entfernt* die Routen, statt sie mit
404 zu bedecken — `app/mcp/mount.py` trennt dafür Bauen (`mount`) von Anhängen
(`aktivieren`/`deaktivieren`). `tests/test_mcp_toggle.py` prüft die Routentabelle
selbst, nicht nur den Statuscode; wer daran etwas ändert, sieht zuerst dort nach.

Die Instanz ist dabei Resource Server *und* OAuth-2.1-Authorization-Server; Zugriff
entsteht erst durch die Zustimmung eines angemeldeten Benutzers auf `/oauth/consent`
und gilt für genau eine Organisation, gedeckelt durch dessen Rolle. Kein Werkzeug
löscht Daten. Jeder schreibende Aufruf landet im Audit-Log mit Quelle `mcp`.

#### Die Richtlinie je Organisation

Über dem Instanzschalter liegt eine zweite Ebene: **jede Organisation nimmt erst
teil, wenn ihr Admin sie einschaltet** (`services/org_mcp_policy.py`, Tabelle
`organization_mcp_policies`, Portal: Org-Admin → **KI-Zugriff**). Keine Zeile heißt
aus — der Standard steht damit an *einer* Stelle (`org_mcp_policy.AUS`) und nicht in
einem `server_default`. Migration `0042` schaltet nur die Organisationen ein, an denen
schon eine aktive Verbindung hängt, mit genau deren Scopes; alles andere bleibt aus.

Zwei Achsen, die als **Und** wirken: **Bereiche** (`app/mcp/areas.py` — Konvois,
Fahrzeuge, Wegpunkte, Routen, Status) sagen *worauf*, die Scopes sagen *wie weit*.
`convoy:read` ist dabei keine Wahl, sondern Voraussetzung: ohne ihn käme ein Token
nicht an `AuthSettings.required_scopes` vorbei, also ergänzt `setzen()` ihn bei jeder
eingeschalteten Richtlinie.

Die Freigabe kennt **keine Scope-Hierarchie** — das ist der Unterschied zu
`mcp/scopes.py`. Dort sagt die Hierarchie, was ein erteiltes *Recht* einschließt; hier
geht es darum, was eine Organisation *freigeben will*, und „planen ja, Positionen
nein" muss ausdrückbar bleiben. Aus demselben Grund greift `policy.zuschneiden()` im
Consent **nach** `effective()`: davor brächte `convoy:write` ein `fleet:status` mit.

Im Adminportal listet der Reiter **MCP** alle Organisationen mit ihrem Zustand
(`GET /api/admin/mcp/organizations`, LEFT JOIN auf die Richtlinien — ein Join über
`organization_mcp_policies` ließe die Mehrheit weg, denn keine Zeile ist der Normalfall).
Die Liste ist **rein lesend**: wer die Instanz betreibt, sieht *dass* eine Organisation
teilnimmt, entscheidet aber nicht über ihre Einsatzdaten. Genau dafür gibt es die zweite
Ebene.

Durchgesetzt wird an vier Stellen, und die maßgebliche ist die dritte:
Zustimmungsbildschirm, `tools/list` (`OrgPolicyToolsMiddleware`), **jeder Aufruf**
(`McpContext.require_werkzeug`, aus `mcp_context(werkzeug=…)` heraus) und die
Resources/Abos (`require_bereich`). Die Prüfung sitzt zentral in `mcp_context`, weil 23
Prüfungen in 23 Werkzeugen genau eine sind, die jemand beim 24. vergisst; der Preis ist,
dass jedes Werkzeug seinen Namen durchreicht, und genau das hält
`tests/test_org_mcp_policy.py` per AST gegen den Quelltext — zusammen mit der Regel,
dass jedes Werkzeug einen Bereich hat oder in `GRUNDWERKZEUGE` steht.

Bei den Scopes (`app/mcp/scopes.py`) sind zwei Listen auseinanderzuhalten, die einmal
eine waren: `SCOPES_SUPPORTED` weist aus, *was es gibt* (Protected Resource Metadata),
`REQUIRED_SCOPES` ist die Schwelle des Endpunkts. Steht die volle Liste versehentlich
an der zweiten Stelle, verlangt `RequireAuthMiddleware` von jedem Token sämtliche
Scopes und weist jede lesende Verbindung ab. Erteilt wird ausgeschrieben
(`effective()`), weil dieselbe Middleware ohne Hierarchie prüft — ein Token mit nur
`convoy:write` käme sonst nicht einmal an `/mcp` vorbei.

Welche Rechte eine Verbindung bekommt, entscheidet der Mensch auf dem
Zustimmungsbildschirm, nicht der Client: er kreuzt an, was seine Rolle hergibt. Das ist
kein Komfort, sondern Voraussetzung dafür, dass ChatGPT mehr als lesen kann — es fragt
einmalig beim Verbinden und fordert nie nach. Hintergrund und offene Punkte der
ChatGPT-Anbindung: `docs/superpowers/plans/2026-09-17-chatgpt-app.md`.

Für Clients mit Oberfläche (ChatGPT Apps SDK) liegen drei Ansichten in
`app/mcp/widgets.py` samt `widgets/`. Sie sind **Zugabe, nicht Voraussetzung**: kein
Werkzeug braucht sie, und ihr Inhalt ist eine leere Vorlage — die Daten kommen erst
aus dem Werkzeugaufruf. Vier Regeln hält `tests/test_mcp_widgets.py` fest: jeder
`_meta`-Verweis zeigt auf eine Resource, die es gibt, **nichts wird von außen
nachgeladen**, die Zeichenfunktion steht im HTML **vor** dem Aufruf durch den Rahmen,
und jedes Widget bringt mit, was es aufruft. Die letzten beiden sind nachgetragen, weil
beide Fälle eingetreten sind und beide dasselbe ergeben: eine leere Fläche, deren
Ausnahme der Rahmen abfängt. Was zwei Widgets brauchen, gehört deshalb in `rahmen.html`
und kommt über `w`. Damit die Ansichten Daten bekommen, geben alle Werkzeuge
`dict[str, Any]` zurück statt `dict` — nur so leitet das SDK ein Ausgabeschema ab und
liefert `structuredContent`.

Jedes Werkzeug trägt Verhaltenszusagen (`app/mcp/annotations.py`). Sie sind
unverbindlich — Rechte entscheiden Scopes und Rolle —, aber sie können still falsch
werden: Wer ein Werkzeug von lesend auf schreibend umbaut, muss die Annotation
mitziehen. `tests/test_mcp_widgets.py` hält `read_only_hint` gegen `WRITE_TOOLS` und
verbietet `destructive_hint` an jedem Werkzeug.

Der Aussteller (`oauth_tokens.issuer_url()`) ist **eine** Zeichenkette, normalisiert über
`AnyHttpUrl` — dieselbe, die Pydantic ins Metadatendokument schreibt. Wer sie dort
„vereinfacht", baut die Lücke wieder ein, an der ChatGPT einmal abgebrochen ist: RFC 9207
verlangt den `iss`-Parameter zeichengenau gleich dem Aussteller aus der Metadata, und ein
Test, der dabei `rstrip("/")` benutzt, prüft genau das Falsche.

Der CIMD-Schalter sitzt wie der Hauptschalter im Portal (`mcp_config.is_cimd_allowed`,
Datenbank schlägt Umgebung). Die AS-Metadata wird deshalb je Anfrage fertiggestellt und
nicht beim Start — stünde die Ankündigung im vorgebauten Dokument, bliebe sie bis zum
nächsten Neustart falsch.

Code in `backend/app/mcp/` (Werkzeuge, Scopes, Montage), `backend/app/services/
oauth_provider.py` und `oauth_tokens.py`. Verwaltung im Admin-Portal unter **MCP**.
Anwenderdoku: `wiki/MCP-Server.md`.

Die ASGI-Verdrahtung in `app/mcp/mount.py` hängt an internen Details des SDK —
`mcp` ist deshalb exakt gepinnt, und `tests/test_mcp_auth.py` prüft das beobachtbare
Verhalten. Bei einem SDK-Upgrade zuerst dort nachsehen.

### Begleit-App: Anmeldung über den Browser (OAuth ohne Zustimmungsschirm)

Die App (Repo Convoyplan-Companion) meldet sich per OAuth 2.1 + PKCE über den
Browser des Systems an (RFC 8252) — ein nativer Passkey bräuchte jede Instanz-Domain
im Store-Build. Der Client steht im Code (`app/services/app_client.py`), nicht in der
Datenbank: `convoyplan-companion`, ohne Secret, genau eine Redirect-URI
`de.convoyplan.companion:/oauth`. `validate_redirect_uri` bleibt für registrierte
Clients bei HTTPS/Loopback; das Schema gilt nur hier und kommt nie aus einer Anfrage.

Vier Dinge, die man kennen muss:

- **Unabhängig von MCP.** `app/mcp/mount.py` trennt die Routen: MCP-eigene
  (`/mcp`, `/register`, Protected-Resource-Metadaten) hängen am MCP-Schalter, die des
  Authorization Servers an MCP **oder** `APP_OAUTH_ENABLED`. Deshalb prüft der
  Provider beim Einlösen selbst (`_client_zulaessig`), sonst tauschte eine
  MCP-Verbindung bei abgeschaltetem MCP an `/token` weiter. `org_slug` kommt über
  eine Hülle um `/authorize` (`_OrgAusAnfrage` → `ANGEFRAGTE_ORG`), weil das SDK
  zusätzliche Parameter verwirft.
- **Kein Zustimmungsschirm, aber auch kein stiller Code.** `/oauth/app` stellt den
  Code ohne Rückfrage nur aus, wenn die Org-Sitzung *nach* der Anfrage entstand
  (`frisch_angemeldet`: `iat` der Sitzung ≥ `iat` des Tickets — deshalb trägt
  `create_token` jetzt `iat`); sonst 409 und ein Klick. Ohne das könnte jede fremde
  Seite den Browser eines Angemeldeten auf `/authorize` schicken, und der Code ginge
  an die App, die sich das Schema genommen hat. Gelesen wird nur das Cookie der
  Organisation aus dem Ticket, nicht `get_current_person`.
- **Tokens für die REST-API.** Access-Tokens der App sind `typ="access"` mit
  `aud=<instanz>/api` (15 min). `deps._decode_token` prüft die Audience ausdrücklich
  (PyJWT dort mit `verify_aud: False`, weil Login-Tokens keine tragen): ein Token mit
  fremder `aud` gilt nicht. Refresh-Tokens 90 Tage ohne Nutzung, mit Rotation; sie
  tragen die `token_version` (Migration `0054`) — gilt seither auch für MCP: ein
  Passwortwechsel beendet die Kette beim nächsten Erneuern. Die Mitgliedschaft wird
  bei jedem Tausch neu gelesen.
- **`TokenError` nie innerhalb von `get_db_session()` werfen.** Sie ist eine
  eingefrorene Dataclass, `contextlib` scheitert am Traceback, und aus `invalid_grant`
  wird ein 500. Im Token-Pfad gilt `_token_sitzung()` mit `_TokenAbbruch`.

Die App erkennt den Weg an `convoyplan_app_client_id` in `/.well-known/oauth-authorization-server` (so liest es Convoyplan-Companion#89; zusätzlich `GET /api/version` → `app_oauth`). In den MCP-Listen und
-Zählern des Admin- und Org-Portals taucht der Client nicht auf, die Aufräumroutine
lässt seine Zeile stehen. Tests: `tests/test_app_anmeldung.py` (ganzer Weg mit MCP
aus), `tests/test_mcp_toggle.py` (Routentabelle mit und ohne App-Client),
`frontend/e2e/app-anmeldung.spec.ts`. Anwenderdoku: `wiki/Sicherheit-und-Datenschutz.md`,
„Anmeldung der Begleit-App".

### Auskunft für Agenten (llms.txt, Well-Known, Markdown)

Jede Instanz liefert unter ihrer eigenen Domain aus, was sie ist und wie man sie
programmatisch anspricht: `/llms.txt`, `/agents.md`, `/auth.md`, `/api.md`,
`/openapi.json`, `/sitemap.xml`, `/robots.txt`, die Well-Known-Dokumente
(`agent-card.json`, `agent-skills/index.json`, `ard.json`, `mcp/server-card.json`,
`api-catalog`), `/ask` (NLWeb) und die Seiten `/about`, `/pricing`, `/developers`,
`/docs`, `/contact`, `/privacy`, `/terms`.

Dazu `/.well-known/openai-apps-challenge`, sobald `OPENAI_APPS_CHALLENGE` gesetzt ist —
der Nachweis der Domain für eine ChatGPT-App-Einreichung. Ohne Eintrag gibt es den Pfad
nicht; Hintergrund in `docs/superpowers/plans/2026-09-17-chatgpt-app-einreichung.md`.

Alles davon **liegt im Frontend**, nicht im Backend: Caddy reicht nur `/api/*`, `/mcp`,
`/.well-known/oauth-*` und die OAuth-Endpunkte ans Backend durch, der Rest geht ans
Frontend. Verteilt wird in `frontend/src/lib/server/agent/dispatch.ts`, aufgerufen aus
`hooks.server.ts` — eine Tabelle statt je einer SvelteKit-Route, weil der
Dateisystem-Router ein Verzeichnis mit führendem Punkt (`.well-known`) übergeht.

Die Texte stehen in `lib/server/agent/documents.ts`, die Produktfakten in
`lib/agent/facts.ts`, der Seitenkatalog in `lib/agent/pages.ts`. **HTML und Markdown
entstehen aus derselben Quelle** (`render.ts` rendert dasselbe Dokument, das unter
`/<seite>.md` ausgeliefert wird) — wer eine Seite ändert, ändert beide Fassungen.

Die Startseite ist die Ausnahme von `render.ts`: sie trägt die Anmeldekarte und bleibt
deshalb eine Svelte-Seite (`routes/+page.svelte`). Deckungsgleich mit `/index.md` bleibt
sie über die Fakten statt über den Renderer — Titel aus `PAGES`, Untertitel und
Fließtext aus `PRODUCT`, Kacheln aus `FEATURES`. Dieselbe `FEATURES`-Liste füllt die
`featureList` im JSON-LD und die Aufzählung in `indexMd()`; Produktprosa gehört deshalb
nach `facts.ts` und nicht ins Markup.

Zwei Regeln, die den Aufwand erklären:

- **Nichts ankündigen, was es auf dieser Instanz nicht gibt.** Die Dokumente werden je
  Anfrage aus `GET /api/status/capabilities` gebaut (Domain, MCP an/aus, Demo an/aus).
  Ein `server-card.json`, das auf einen abgeschalteten `/mcp` zeigt, wäre schlechter als
  keines.
- **Nicht nach User-Agent unterscheiden.** Markdown gibt es über `Accept: text/markdown`,
  über `.md` und über `?mode=agent` — nicht, weil ein Crawler sich als Crawler zu
  erkennen gibt. Das wäre Cloaking.

Abschaltbar über `AGENT_DISCOVERY=false` (Standard an); dann existieren diese Pfade
nicht. Anwenderdoku: `wiki/Agenten-Auskunft.md`.

`/openapi.json` ist bewusst **nicht** die vollständige Beschreibung — die bleibt hinter
`DOCS_API_KEY`. Das Frontend reicht `/api/public/openapi.json` durch; das Backend baut
dort eine kuratierte Teilmenge aus der laufenden App
(`backend/app/api/routes/public_meta.py`). Die Liste der öffentlichen Operationen steht
ausdrücklich in `PUBLIC_OPERATIONS`, mit **eigenen** Beschreibungen statt der Docstrings:
Docstrings erklären hier Entscheidungen, und die gehören nicht in ein offenes Dokument.
`tests/test_public_openapi.py` prüft die Liste in beide Richtungen — jeder Eintrag
existiert, und keiner hängt an einem Guard. Wer dort etwas ändert, sieht zuerst in diesem
Test nach.

### Meldungen aus der Anwendung (Fehler und Wünsche)

Der Melde-Knopf sitzt in der Planungsansicht (Seitenleiste, neben *Hilfe*) und
im Org-Admin. Der Dialog hängt **einmal** im Org-Layout
(`routes/o/[slug]/+layout.svelte`) und wird über `stores/feedback.ts` geöffnet —
ein Store und keine Prop-Kette, weil Auslöser und Dialog nicht beieinander
stehen.

Das Bildschirmfoto entsteht im Browser (`lib/screenshot.ts`) über
`getDisplayMedia`, Einfügen oder Dateiauswahl und geht als **Data-URL im
JSON-Körper** mit, nicht als zweiter Multipart-Aufruf: sonst stünde die Meldung
zwischen beiden Aufrufen ohne ihr Bild da, und zwar genau dann, wenn das Netz
wackelt. Kein `html2canvas` — ein Nachzeichner malt das DOM nach, und bei Karte,
Schriften und überlagerten Ebenen kommt dabei etwas anderes heraus als auf dem
Schirm stand.

Erkannt wird das Format an den **Magic Bytes** (`services/feedback.py`), nicht
am angegebenen Typ, und SVG ist ausgeschlossen — ein Bildschirmfoto ist nie
eines, und es ist das einzige Bildformat, das Skript trägt. Abgelegt wird unter
`/uploads/feedback/`, ausgeliefert nur über
`GET /api/admin/feedback/{id}/screenshot`: ein ratbarer Pfad unter `/uploads/`
wäre für die ganze Instanz lesbar, und auf einem Bild aus dem Einsatz stehen
Einsatzdaten.

Melden und Sichten liegen in **einer** Datei (`api/routes/feedback.py`, zwei
Router). Die Herkunft einer Meldung kommt aus der Sitzung, nie aus dem Körper;
`melder()` probiert dafür erst `get_org_context` und fällt auf
`get_current_person` zurück, weil der Dialog auch außerhalb einer Organisation
aufgeht. `/api/feedback` steht in `_EXEMPT_PREFIXES` des Lizenzwächters — der
Demo-Modus ist der Zustand, in dem am ehesten jemand melden will.

Zwei Einschätzungen, die getrennt bleiben: `severity` gehört dem Melder und wird
nicht angefasst, `priority` dem Betreiber. In einem Feld verlöre man die erste
beim ersten Triage-Klick, und genau die sagt, wie schlimm es sich *im Einsatz*
angefühlt hat.

`frontend/e2e/feedback-melden.spec.ts` hält die Zusage fest, die man der
Oberfläche nicht ansieht: der abgeschickte Aufruf enthält die Felder, die der
Ausklapper „Was mitgeschickt wird" nennt — und kein Feld mehr. Anwenderdoku:
`wiki/Meldungen.md`.

### Lizenz: Schlüssel je Instanz, Plan je Organisation

Verkauft wird Betrieb, Wartung und Support, nicht Funktionen — ein Schlüssel
schaltet den Demo-Modus ab und sonst nichts frei. Unter AGPL wäre jede
Funktionssperre ohnehin nur ein Zaun für Ehrliche. Zwei Ebenen, die man nicht
vermischen darf:

- **Der Schlüssel** (`services/license.py`, Payload v2 aus dem Lizenzmanager)
  gilt für die Instanz und trägt `max_orgs`. Die Grenze greift **nur beim
  Anlegen** einer Organisation (`services/org_kontingent.py`, an allen drei
  Stellen: Admin, `POST /api/organizations/`, Ersteinrichtung), nie beim
  Betrieb. Schlüssel ohne `v` sind unbegrenzt — „ausgestellte Schlüssel bleiben
  gültig" heißt: mit dem, was sie erlaubt haben. Nach `contract_until` gilt fürs
  Anlegen wieder eine Organisation, lizenziert bleibt die Instanz.
- **Der Plan** (`services/org_plan.py`, Tabelle `organization_plans`, Migration
  `0051`) gilt für eine Organisation auf einer gemeinsamen Hosting-Instanz und
  wird vom Superadmin gesetzt — signiert werden muss nichts, die Instanz gehört
  dem, der ihn setzt. Keine Zeile = keine Grenzen; das ist der Normalfall.

Die Grenzen eines Plans sind **weich**, und das ist Absicht: eine Absage beim
Anlegen des 26. Fahrzeugs träfe den Moment, in dem jemand während einer Lage
nachträgt. Gemeldet wird nur (`GET /api/org/plan`, Hinweis im Org-Layout,
Übersicht im Adminportal). Hart ist allein der **Ablauf**: nach `valid_until`
14 Tage Kulanz, danach nur lesend — durchgesetzt in `api/deps.get_org_context`
(schreibende Methoden) und in `mcp/context.mcp_context` (`WRITE_TOOLS`). Wer
einen dritten Weg zum Schreiben in eine Organisation baut, zieht die Sperre
dort mit.

Gespeichert werden die geltenden Werte, nicht nur der Paketname: ein Angebot
weicht vom Katalog ab, und eine Änderung an `KATALOG` darf bestehende Verträge
nicht umschreiben. **Preise gehören nirgends ins Repo** — weder hierher noch ins
Wiki; sie stehen nur im Angebot.

Den **Ablauf des Schlüssels** kündigt die Instanz selbst an
(`services/lizenz_ablauf.py`): Mail an die Superadmins 30 und 7 Tage vorher und
beim Ablauf, je Stufe einmal (Merker `license.expiry_notified` =
`<ablaufdatum>:<stufe>`, ein neuer Schlüssel fängt also von vorn an), dazu
`LizenzAblaufHinweis.svelte` für Superadmins. Die Grenze von 30 Tagen steht nur
im Backend (`WARN_TAGE`, `expiry_warning` im Status) — das Frontend rechnet
nicht selbst. Tests: `tests/test_lizenz_ablauf_warnung.py`,
`frontend/e2e/lizenz-ablauf-hinweis.spec.ts`.

Tests: `tests/test_lizenz_organisationsgrenze.py`, `tests/test_org_plan_grenzen.py`
(Rechenregeln ohne Datenbank, danach durch die App und über MCP),
`frontend/e2e/org-plan-hinweis.spec.ts` (wer den Hinweis sieht). Anwenderdoku:
`wiki/Lizenz-und-Demo-Modus.md`.

### Passkeys: Domain, einmalige Challenge, kein TOTP danach

Anmelden geht auch per WebAuthn. Die Regeln stehen in `app/services/passkey.py`,
die Verdrahtung in `api/routes/passkeys.py`, die Browserseite in
`frontend/src/lib/passkey.ts` (base64url ↔ ArrayBuffer, sonst nichts) und
`lib/components/PasskeyVerwaltung.svelte`. Drei Dinge, die man kennen muss:

- **Relying Party ist `APP_BASE_URL`** — Hostname als RP-ID, die Adresse selbst
  als einziger Ursprung. Bewusst keine eigene Einstellung: eine zweite, die von
  der ersten abweichen kann, ergäbe nur Passkeys, die nirgends passen. Ein
  Domainwechsel macht bestehende Passkeys ungültig; das ist WebAuthn.
- **Eine Challenge gilt einmal** und liegt im Speicher (wie `rate_limit` und
  `tracking_manager`), gedeckelt durch `MAX_OFFENE`, weil die Login-Optionen
  öffentlich sind. Ein Token, das die Challenge signiert mit sich trägt, wäre
  zustandslos, aber bis zum Ablauf beliebig oft einlösbar.
- **Benutzerverifikation ist Pflicht, deshalb folgt kein TOTP.** Wer
  `require_user_verification` lockert, macht aus dem Passkey einen reinen
  Besitzfaktor, und der Login übersprünge MFA trotzdem. Einrichten verlangt das
  Passwort erneut — ein Passkey überlebt Passwortwechsel und -reset.

**Autofill** (`starteAutofill` in `$lib/passkey.ts`) hält auf den Anmeldeseiten eine
stille Anfrage (`mediation: 'conditional'`) offen. Wer dort etwas ändert, hält drei
Dinge fest, die `e2e/passkey-autofill.spec.ts` prüft: der Knopf beendet sie, **bevor**
er seine eigene stellt (zwei offene lehnt der Browser ab); sie wird nach
`AUTOFILL_ERNEUERN_MS` mit frischer Challenge neu gestellt, weil der Server eine nach
fünf Minuten verwirft; und eine sofortige Ablehnung durch den Browser beendet sie,
statt im Kreis Challenges abzurufen. Im Test mit echtem virtuellem Authenticator ist
Autofill für den Knopf-Weg abgeschaltet — das Gerät beantwortet die stille Anfrage
sonst selbst, und wer schneller ist, entscheidet über Grün oder Rot.

Die Anmeldepfade liegen unter `/api/auth/login/passkey…`, weil der Lizenzwächter
genau `/api/auth/login` durchlässt. Wer sie verlegt, zieht `_EXEMPT_PREFIXES`
mit, sonst gibt es im Demo-Modus keine Passkey-Anmeldung.

Tests: `tests/test_passkey_anmeldung.py` mit einem Software-Authenticator (echte
P-256-Signaturen, die Bibliothek wird **nicht** gemockt) und
`frontend/e2e/passkey-anmeldung.spec.ts` mit Chromiums virtuellem Authenticator —
dort prüft der Test die Signatur über die angekommenen Bytes, weil ein Fehler in
der base64url-Umwandlung sonst nur als „Anmeldung fehlgeschlagen" sichtbar wäre.
Anwenderdoku: `wiki/Sicherheit-und-Datenschutz.md`, „Passkeys".

## Test-Konventionen

Was in `.github/workflows/ci.yml` blockierend läuft, ist die verbindliche Liste:

- **Backend** — `ruff check app/` und `pytest tests/` (`backend/`). Tests sind
  `async` (`asyncio_mode = "auto"`), sprechen die App über
  `AsyncClient(transport=ASGITransport(app=app))` an und brauchen eine
  PostGIS-Datenbank (`DATABASE_URL`). Autouse-Fixtures in `tests/conftest.py`
  schalten Rate-Limiting, HIBP-Abfrage und Update-Check ab; ein Test, der genau
  das prüft, aktiviert es selbst wieder.
- **Frontend** — `npm run check` (svelte-check) und `npm run test:e2e`
  (Playwright, Job `Frontend – E2E (Playwright)`) in `frontend/`. Die Tests
  liegen in `frontend/e2e/` und starten sich ihre Server selbst: den **gebauten**
  Stand der App (`build` + `preview`, nicht `vite dev` — der übersetzt beim ersten
  Zugriff und lässt parallele Tests in den Zeitablauf laufen) und eine schlanke
  Komponentenhülle (`e2e/harness/`) für alles, was in der App hinter der Anmeldung
  sitzt. Ein Backend braucht es nicht: `mockTrack` beantwortet die Tracking-API,
  die Hülle stubbt `$lib/api`, und `blockExternal` bricht alles ab, was nicht von
  der Testinstanz kommt — ohne das hängen die Tests ohne Netz an den Kartenkacheln.
  Die Hülle ist **kein** Teil des Produktionsbaus; eine Testroute unter `src/routes/`
  wäre eine, die mit ausgeliefert wird. Ihre Vite-Konfiguration spiegelt den
  `<style>`-Block aus `src/app.html` in die Seite und setzt `__APP_VERSION__` —
  ein Test, der Geometrie misst, misst sonst gegen Farben und Schriftgrößen, die
  es in der App gar nicht gibt. Der Job läuft im **Playwright-Image**
  (`mcr.microsoft.com/playwright:v1.63.0-noble`), weil `npx playwright install` auf
  dem Runner nach dem Download beim Entpacken stehenblieb — ohne Ausgabe, ohne
  Abbruch. Dessen Marke muss zur Fassung von `@playwright/test` passen: Wer die
  Abhängigkeit hebt, hebt die Marke in `ci.yml` mit.

  **Lokal** braucht es den Browser einmalig: `npx playwright install chromium`
  in `frontend/`. Bleibt der Befehl nach dem Download ohne Ausgabe stehen, liegt
  es an der Node-Fassung — dann entweder eine ältere nehmen oder die Suite im
  selben Image fahren wie die CI:
  `docker run --rm -v "$PWD":/w -w /w/frontend mcr.microsoft.com/playwright:v1.63.0-noble
  sh -c 'npm ci && npm run test:e2e'`.
- **Shell** — die Suiten unter `docker/updater/tests/` und für den
  GraphHopper-Entrypoint; sie tragen den Regionswechsel und laufen im Job
  `Shell – Updater und Entrypoint`. Derselbe Job fährt auch die Suiten
  unter `.github/`, die **Shell in einer YAML-Datei** prüfen: die Entscheidung
  in `.github/actions/build-or-reuse/`, den Nachweisschritt des Region-Jobs
  und die Versionsnummer des automatischen Releases (`.github/workflows/tests/`). Beide **schneiden ihr Original aus der
  YAML-Datei heraus**, statt es nachzubauen — ein Nachbau prüft die Kopie. Wer
  dort einen weiteren Test anlegt, braucht nichts zu verdrahten: der Job
  sammelt `test_*.sh` aus allen vier Verzeichnissen ein.
- **Container** — Trivy scannt alle fünf Images (`backend`, `frontend`,
  `graphhopper`, `updater`, `osmium`) auf HIGH/CRITICAL mit verfügbarem Fix.
  Ausnahmen gehören mit Begründung in `.trivyignore`.

Neue Tests liegen neben den bestehenden in `backend/tests/` und werden nach dem
geprüften Verhalten benannt (`test_<thema>.py`), nicht nach der Implementierung.
Dasselbe gilt vorne: Was in `frontend/e2e/` geprüft wird, ist eine Zusage an den
Anwender — dass der QR-Code die Adresse und **kein** Sitzungstoken trägt, dass
weder Passwort noch Seiteninhalt auf dem Ausdruck landen, dass ein widerrufener
Link keinen QR-Knopf hat. Solche Zusagen sieht man einem Bildschirmfoto nicht an,
und still falsch werden sie trotzdem.
