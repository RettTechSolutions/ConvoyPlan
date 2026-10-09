# Eigene Overpass-Instanz — optionaler Dienst neben GraphHopper

Anlass: Die Brückensuche meldete „OpenStreetMap-Dienst nicht erreichbar"
(RettTechSolutions/ConvoyPlan#608). Ein Teil davon war hausgemacht: drei
gleichzeitige Abfragen gegen zwei Slots je IP. Behoben ist das mit #608. Übrig
bleibt das, was kein Code behebt:

- **Es gibt keinen Ersatz.** Von den öffentlichen Spiegeln antworteten im
  Oktober 2026 zwei nur mit 500 (`kumi.systems`, `private.coffee`), einer hatte
  ein abgelaufenes Zertifikat (`osm.jp`), einer kennt nur die Schweiz
  (`osm.ch`). Übrig blieb `maps.mail.ru`, und dorthin schicken wir keine Routen.
- **Jede Abfrage enthält die geplante Route.** Sperrungen und Brücken werden
  entlang der Linie gesucht, und die Linie geht an einen fremden Server. Für
  BOS-Konvois ist das keine Nebensache.
- **Die ganze Instanz teilt sich zwei Slots.** Mehrere Organisationen auf einer
  gemeinsamen Hosting-Instanz, die gleichzeitig planen, warten aufeinander.

Eine eigene Instanz löst alle drei. Sie ist **optional**, weil sie Platte und
Importzeit kostet, die nicht jede Installation hat.

Dieses Dokument hält fest, wie sie in den Stack passt, was man dabei falsch
machen kann und in welcher Reihenfolge gebaut wird.

---

## 1. Ausgangslage

| Was | Wo | Bedeutung hier |
|---|---|---|
| PBF der Region | Volume `osm_data`, Datei aus `/data/osm/.region` | liegt schon da, wird **nicht** ein zweites Mal geladen |
| Regionswechsel | `switch-region.sh`, Staging unter `/data/graph/.staging` | Vorbild für den Neuaufbau ohne Ausfall |
| Vollständigkeit | `edges` bei GraphHopper, **nicht** der Fingerprint | dieselbe Lehre wie am 2026-09-19 |
| Overpass im Backend | `services/overpass.py`, `OVERPASS_URLS` (#608) | nur die Liste ändert sich |
| Images | fünf, je an fünf Stellen verdrahtet | ein sechstes heißt: alle fünf Stellen |

Compose kennt **keine Profile**, und das ist Absicht
(`docs/superpowers/specs/2026-09-20-zwei-hosts-design.md`, Abschnitt 3):
fehlt `COMPOSE_PROFILES` an einer Stelle, verschwindet ein Dienst beim nächsten
`up -d` still. Daran hält sich dieser Plan.

## 2. Wie „optional" ohne Profil geht

Der Dienst `overpass` steht **immer** in `docker-compose.yml`. Ob er arbeitet,
sagt `OVERPASS_LOCAL` (Standard `false`):

- **`false`**: Der Entrypoint schläft (`exec sleep infinity`). Kein Import, keine
  Platte, ein paar MB RAM. Der Healthcheck meldet gesund.
- **`true`**: Import beim ersten Start, danach Betrieb.

Warum so herum und nicht als zweite Compose-Datei: Der Updater kennt genau eine
Stack-Datei und überschreibt sie bei jedem Update aus dem Repo
(`_update_stack_file`). Eine Zusatzdatei überlebte das nicht. Ein Dienst, der
ruhend mitläuft, kann nicht still verschwinden. Ein Dienst, der fehlt, schon.

Der Preis: Jede Installation zieht das Image (geschätzt 200–300 MB), auch ohne
es zu nutzen. Das ist vertretbar.

## 3. Image

Ein eigenes Image `ghcr.io/retttechsolutions/convoyplan/overpass`,
`FROM wiktorn/overpass-api:<fassung>@sha256:…`. Ein eigenes und kein fremdes
Image, weil:

- Trivy, cosign und Kanal-Tags (`latest`/`beta`/`nightly`) nur für eigene
  Images gelten. Ein fremdes Image liefe an der Signaturprüfung im Updater
  vorbei.
- `build-or-reuse` genau dafür da ist: Neu gebaut wird nur, wenn sich unser
  Entrypoint oder der Base-Digest bewegt.

Vom Base-Image wird nur der **Betrieb** genutzt (nginx, fcgiwrap, Dispatcher).
Den Import macht unser Entrypoint selbst (Abschnitt 4), weil das Image nur
eine URL auf `.osm.bz2` kennt und wir ein PBF auf der Platte haben:

```
osmium cat /data/osm/<datei>.osm.pbf -f osm -o - \
  | update_database --db-dir=/db/.staging --compression-method=gz --map-compression-method=gz
```

Kein Zwischenschritt über `.osm.bz2`. Der kostete bei DACH zweistellige GB
temporäre Platte und Stunden.

## 4. Entrypoint: Import, Fertig-Marke, Wechsel

Dieselbe Trennung wie bei GraphHopper, aus demselben Grund (2026-09-19):

| Datei | Geschrieben | Sagt |
|---|---|---|
| `.fingerprint` | **vor** dem Import | *wofür* gebaut wird (PBF-Name + Größe + Replikationsnummer aus dem PBF-Kopf) |
| `.fertig` | **nach** erfolgreichem Import | *dass* es fertig ist |

Ablauf beim Start mit `OVERPASS_LOCAL=true`:

1. `/data/osm/.region` lesen, wie `graphhopper/entrypoint.sh` es tut
   (`region-source.sh`, nicht nachbauen).
2. `/db/aktiv` hat `.fertig` **und** einen passenden Fingerprint → Betrieb.
3. Sonst Import nach `/db/.staging`. Währenddessen bedient eine vorhandene
   alte `/db/aktiv` weiter. Nach Erfolg: `.fertig` schreiben, `aktiv` →
   `.alt`, `.staging` → `aktiv`, Dispatcher neu starten, `.alt` löschen.
4. Ein `.staging` ohne `.fertig` beim Start ist ein Torso → wegwerfen und neu.

**Wipe-Regel wie bei GraphHopper:** Wer aufräumt, fasst Punktdateien nur mit
Absicht an. Ein `rm -rf /db/*` darf ein laufendes `.staging` nicht treffen.

Der Regionswechsel braucht **keinen** eigenen Hook. Nach dem Tausch schreibt
`switch-region.sh` die neue `.region`, der Fingerprint passt nicht mehr, und
der nächste Start baut neu. Der Updater startet `overpass` nach dem Wechsel
mit (`_compose up -d --force-recreate graphhopper overpass`). Bis der neue
Import fertig ist, antwortet die alte Region. Das Backend merkt das nicht,
aber Abfragen außerhalb der alten Region liefern leer, und **leer sieht aus
wie „keine Brücke"**. Deshalb Abschnitt 6.

## 5. Aktuell halten

Ein PBF ist ein Stand. GraphHopper lädt es nur beim Regionswechsel neu. Für
Routing reicht das, für Baustellen nicht.

- **Geofabrik-Einzelextrakt** (DACH, DE, Bayern, Berlin — alle Vorgaben des
  Installers): Geofabrik führt je Extrakt ein `-updates/`-Verzeichnis mit
  täglichen Diffs. Die Startnummer steht im PBF-Kopf
  (`osmosis_replication_sequence_number`). Der Entrypoint wendet die Diffs
  stündlich geprüft an (`apply_osc_to_db`). *Vor Baubeginn prüfen: gibt es
  `dach-updates/state.txt` noch, und passt die Nummer im Kopf dazu.*
- **Zusammengeführte Extrakte** (`merge-extracts.sh`) und eigene URLs: keine
  Diff-Quelle. Dann **wöchentlicher Neuaufbau** über Staging (Abschnitt 4),
  mit neu geladenem PBF in ein eigenes Verzeichnis, nicht über das von
  GraphHopper.

Wie alt der Stand ist, liefert Overpass selbst (`osm3s.timestamp_osm_base`) und
zeigt das Admin-Portal (Abschnitt 8).

## 6. Backend

- **Kein Ersatz als Vorgabe** (entschieden 2026-10-09). Bei
  `OVERPASS_LOCAL=true` setzt der Installer `OVERPASS_URLS` auf
  `http://overpass/api/interpreter`, und nur darauf. Die Route bleibt im Haus.
  Wer ausdrücklich zustimmt (Abschnitt 7), bekommt
  `https://overpass-api.de/api/interpreter` als zweite URL dazu.
- **Ohne Ersatz braucht der Ausfall einen eigenen Text.** Baut die eigene
  Instanz oder passt ihre Region nicht, gibt es keine nächste URL. Dann darf
  weder eine leere Liste herauskommen noch „OpenStreetMap-Dienst nicht
  erreichbar". Das Backend antwortet mit einem eigenen Grund (`503`,
  `detail: "overpass_import"` bzw. `"overpass_region"`), und
  `DurchfahrtsHoehen.svelte` sagt „Eigene OpenStreetMap-Instanz baut gerade
  neu – Brücken danach erneut suchen". Dasselbe gilt für Sperrungen und
  Tankstellen.
- **Slots je Server**, nicht global: die Semaphore aus #608 gilt der
  öffentlichen Instanz. Die eigene verträgt mehr (`OVERPASS_RATE_LIMIT` im
  Image). Also ein Slot-Zähler je Host, Anzahl aus einer Tabelle mit Vorgabe 2.
- **Leer ist nicht „nichts gefunden", solange gebaut wird.** Der Entrypoint
  schreibt seinen Zustand nach `/db/status.json` (`betrieb`, `import`,
  `aktualisiert`, `fehler`, Region, Stand). Das Backend liest ihn über einen
  lesenden Mount, wie bei `graph_aufbau.py`. Stimmt die Region der Instanz
  nicht mit `.region` überein, gilt die eigene Instanz als nicht verfügbar,
  und es geht zur nächsten URL. Das ist dieselbe Regel wie beim Routing-Graphen
  und die wichtigste dieses Plans.
- `probe()` prüft die erste URL, also die eigene. `/api/status` sagt, ob die
  eigene oder die öffentliche geantwortet hat.

## 7. Installer und Regionsvorschau

- `install.sh`/`install.ps1`: eine Frage nach der Regionswahl, „Eigene
  OpenStreetMap-Abfrage-Instanz? (j/N)", mit Platz- und RAM-Hinweis für die
  gewählte Region. Bei *ja* eine zweite Frage: „Bei Ausfall der eigenen
  Instanz auf overpass-api.de ausweichen? Die geplante Route geht dann an
  diesen Server. (j/N)". Vorgabe *nein*. Schreibt `OVERPASS_LOCAL` und
  `OVERPASS_URLS`. Im Update-Modus ergänzt `_patch_env` nur
  `OVERPASS_LOCAL=false` und fasst `OVERPASS_URLS` nicht an.
- `region_estimate.py`: Ist `OVERPASS_LOCAL` an, rechnet die Vorschau die
  Overpass-Datenbank mit ein, als Platte für Staging **und** Bestand während
  des Wechsels. Die Faktoren kommen aus dem Spike (Abschnitt 11, Schritt 1),
  nicht aus diesem Dokument.
- Auch im Admin-Portal schaltbar? **Nein**, nicht in der ersten Fassung. Der
  Schalter startet einen stundenlangen Import und belegt zweistellige GB. Das
  gehört in den Installer, wo die Platte gefragt wird.

## 8. Oberfläche

- **Systemübersicht**: Der Container erscheint dort von selbst
  (dockerproxy). Dazu eine Zeile „Overpass: eigene Instanz · Stand <Zeit> ·
  Region <Name>" bzw. „Import läuft seit …".
- **InfoPill / öffentliche Statusseite**: „Sperren (Overpass)" bleibt, mit
  dem Zusatz *eigene* oder *öffentlich*.

## 9. Updater und CI — das sechste Image

Alle Stellen, an denen die fünf Images heute stehen, bekommen `overpass` dazu:

- `docker-compose.yml`: Dienst, Volume `overpass_db`, Env auch beim Updater
  (`OVERPASS_IMAGE`, `OVERPASS_LOCAL`)
- `update-images.sh`: `_apply_channel_images`, cosign-Schleife
- `env-kanal.sh`: das Muster der `*_IMAGE`-Zeilen. Test
  `test_env_kanal.sh` zieht mit.
- `ci.yml`: Trivy-Matrix
- `release.yml`, `nightly-images.yml`: Metadaten, `build-or-reuse`, LTS-Retag,
  Signatur
- `install.sh`/`install.ps1`: `OVERPASS_IMAGE` im `.env`-Heredoc

Ein Shell-Test zählt die Images an allen Stellen. Heute hält die Disziplin das
zusammen. Bei sechs Stellen mal sechs Images reicht das nicht mehr.

## 10. Tests, die zählen

| Test | Prüft |
|---|---|
| `docker/overpass/tests/test_entrypoint_zustand.sh` | Fingerprint ohne `.fertig` → neu; `.staging`-Torso → weg; `OVERPASS_LOCAL=false` → schläft, rührt `/db` nicht an; Wipe trifft keine Punktdateien |
| `…/test_entrypoint_wechsel.sh` | alte DB bedient während des Imports, Tausch erst nach `.fertig` |
| `backend/tests/test_overpass.py` | Slots je Host; fremde Region → nächste URL; Zustand `import` → nächste URL |
| `backend/tests/test_overpass_eigene_instanz.py` | `/api/status` unterscheidet eigene/öffentliche; ohne Ersatz und mit bauender Instanz kommt `503` mit Grund, nie eine leere Liste |
| `frontend/e2e/durchfahrtshoehen.spec.ts` | „baut gerade neu" statt „nicht erreichbar" |
| Installer-Test | ohne Antwort auf die Ersatzfrage steht nur die eigene URL in `.env` |
| Image-Zähltest (Abschnitt 9) | sechs Images an allen Stellen |

Alle Entscheidungen im Entrypoint stehen in einer eigenen Datei
(`decide.sh`-Muster), prüfbar ohne Docker, ohne Overpass, ohne PBF.

## 11. Reihenfolge

1. **Spike, nichts davon wird gemergt.** DACH-PBF in `wiktorn/overpass-api`
   importieren, direkt per Pipe. Messen: Importdauer, Spitzen-RAM, Größe der
   DB, Antwortzeit der Brückenabfrage für München→Berlin. Prüfen, ob die
   Geofabrik-Diffs zur Nummer im PBF-Kopf passen. Ergebnis als Tabelle in
   dieses Dokument.
2. Image + Entrypoint + Shell-Tests (Abschnitte 3, 4, 10), noch ohne Compose.
3. Compose-Dienst ruhend (`OVERPASS_LOCAL=false`), Updater, CI, Release
   (Abschnitt 9). Ab hier zieht jede Installation das Image, aber nichts
   ändert sich.
4. Backend: Slots je Host, Zustand lesen, Region prüfen (Abschnitt 6).
5. Diffs bzw. wöchentlicher Neuaufbau (Abschnitt 5).
6. Installer, Regionsvorschau, Oberfläche, Wiki (`wiki/Verkehrsdaten.md`,
   `wiki/Installation-und-Setup.md`) (Abschnitte 7, 8).

## 12. Offen

- **Ressourcen**: Schätzungen ohne Messung. DACH-PBF etwa 5 GB → DB grob
  20–40 GB, Import einige Stunden, RAM beim Import einige GB. Der Spike
  ersetzt diese Zeile durch Zahlen.
- **Zwei-Host-Betrieb**: `overpass` gehört auf den Routing-Host (PBF liegt
  dort). Die Wächtertabelle in `deploy/zwei-hosts/` zieht mit, sobald es sie
  gibt.
- **Lizenz**: Overpass API ist AGPL, wie ConvoyPlan. Ein eigenes Image auf
  dieser Basis ist unproblematisch, der Quelltext-Verweis gehört ins Label.
