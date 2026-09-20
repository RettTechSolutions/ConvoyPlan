# Design-Spec: Der Stack auf zwei Hosts — GraphHopper zieht aus

Status: **Entwurf zur Abstimmung** · Stand: 2026-09-20

Die Produktivinstanz läuft auf einem Server mit 15,6 GB. Davon hält GraphHopper
13,7 GB — den Graphen der zusammengesetzten Region (Albanien, Kroatien, DACH,
Italien, Montenegro, Slowenien) komplett auf dem Java-Heap. Der Rest des Stacks
braucht 1,2 GB. Ein Import kommt damit gerade so durch (12,9 von 13,6 GB Heap
vor der CH-Vorbereitung), und die nächste Region, die dazukommt, kommt nicht
mehr durch. Der Server lässt sich beim Anbieter nicht vergrößern; die nächste
Stufe (12 Kerne, 24 GB, 29 €) ist eine Neuinstallation.

Diese Spezifikation beschreibt, wie der Stack auf **zwei Hosts** verteilt wird —
mit Docker Compose auf beiden, ohne Orchestrator.

---

## 0. Was dieser Plan nicht ist

Drei Dinge vorweg, damit die Entscheidung auf dem Tisch liegt und nicht im Plan
versteckt.

**Kein Kubernetes, kein Swarm.** Ein Orchestrator verteilt Container, aber ein
Container läuft auf *einem* Knoten — und der braucht dann dieselben 16 GB. Was
ein Orchestrator dazu kostet, ist genau das, was ConvoyPlan installierbar macht:
Updater, Regionswechsel, Systemübersicht, Deploy-Rollback und `install.sh`
hängen am Docker-Socket und an Compose-Volumes. Das wäre kein Portieren, sondern
ein Neuschreiben — für ein Produkt, das andere per `install.sh` auf *einen*
Server stellen.

**Der RAM-Gewinn ist klein.** Wandert der Rest des Stacks weg, hat GraphHopper
~15 statt 13,7 GB. Der Gewinn dieses Plans ist nicht Speicher, sondern
*Entkopplung*: GraphHopper bekommt einen Host, der zu ihm passt und den man
unabhängig vom Rest tauschen kann. Wer nur Speicher braucht, bekommt ihn
billiger mit `MMAP_STORE` (Abschnitt 9) oder dem 24-GB-Server.

**Die Standardinstallation bleibt bitgleich.** Ein Host, `docker-compose.yml`,
`install.sh` — nichts davon ändert sich für Bestandsinstallationen. Die
Zwei-Host-Topologie ist eine *zweite* Aufstellung daneben, mit eigenen
Compose-Dateien und einem Wiki-Abschnitt. Das ist die härteste Randbedingung
dieses Plans und der Grund für die meisten Entscheidungen unten.

---

## 1. Die Rollen

| Rolle | Dienste | Braucht |
|---|---|---|
| **Host A — App** | `caddy`, `frontend`, `backend`, `retention`, `db`, `dockerproxy`, `updater` | 2 Kerne, 4 GB, 40 GB; die öffentliche Adresse, das Zertifikat, die Datenbank |
| **Host B — Routing** | `graphhopper`, `updater` | 4+ Kerne, **16 GB**, 60 GB; keine öffentliche Erreichbarkeit |

Das Backend erreicht GraphHopper heute über `GRAPHHOPPER_URL` (`app/config.py`),
und das ist die einzige Verbindung zwischen beiden Seiten, die im Betrieb
gebraucht wird: `routing.py` rechnet Routen, `status.py` prüft `/health` und
`/info`. Caddy leitet nichts an GraphHopper durch; das Frontend spricht nur mit
dem Backend. Ein Wert in der `.env` reicht für den Betrieb.

Was *nicht* über HTTP läuft, ist der Rest — und der ist der eigentliche Inhalt
dieses Plans: der Updater, der Regionswechsel, die Systemübersicht und die
Backend-Endpunkte, die heute in `/data/osm` und `/data/graph` hineinsehen.

### Welcher Server wird was

Zwei Wege, je nachdem, was der Anbieter günstig hergibt:

- **GraphHopper zieht um** (neuer 16-GB-Server wird Host B): Datenbank,
  Uploads, Zertifikate, DNS bleiben, wo sie sind. Zu migrieren ist nur der
  Graph, und der ist abgeleitet — er baut sich auf B selbst. Migrationsrisiko
  für Nutzdaten: null. Kostet den zweiten 16-GB-Server.
- **Die App zieht um** (neuer kleiner Server wird Host A, der bestehende wird
  Host B): billiger im Monat, aber die Datenbank (37 MB), drei Volumes, die
  `.env` und die DNS-Einträge wandern. Das ist dieselbe Arbeit wie eine
  Neuinstallation, nur ohne den Graphen.

Der Plan ist für beide gleich; nur Abschnitt 7 (Umzug) unterscheidet sich. Die
Empfehlung hängt an einer Zahl, die nur der Anbieter kennt: dem Preis der
kleinsten Stufe.

---

## 2. Das Netz

GraphHopper hat **keine Authentifizierung**. Heute ist das egal, weil der Port
auf `127.0.0.1` gebunden ist. Auf zwei Hosts ist es die erste Frage, nicht die
letzte.

- Beide Hosts hängen in einem **privaten Netz** (das des Anbieters oder
  WireGuard, falls es keins gibt).
- `graphhopper` bindet auf die private Adresse von B — konfigurierbar über
  `GH_BIND`, Standard bleibt `127.0.0.1`. Ein Test hält den Standard fest.
- Die Firewall auf B lässt `8989` nur von A zu. Kein TLS im privaten Netz; die
  Route ist eine JSON-Anfrage, kein Geheimnis, und ein Zertifikat zwischen zwei
  eigenen Hosts wäre Aufwand ohne Gegner.

Auf A steht dann `GRAPHHOPPER_URL=http://<B-privat>:8989`.

---

## 3. Compose: zwei Dateien statt Profile

Die naheliegende Lösung — `graphhopper` in ein Compose-Profil — scheidet aus.
Profile sind opt-in: ein Dienst mit Profil startet nur, wenn das Profil aktiv
ist. Die Standardinstallation müsste `COMPOSE_PROFILES=routing` in jeder `.env`
und in der Umgebung des Updaters tragen; fehlt es an einer Stelle, verliert eine
Bestandsinstallation beim nächsten `up -d` still ihren Routing-Dienst. Das
Risiko trägt genau die falsche Seite.

Stattdessen zwei vollständige Dateien unter `deploy/zwei-hosts/`:

| Datei | Inhalt | Abweichung von `docker-compose.yml` |
|---|---|---|
| `app-host.yml` | alle Dienste außer `graphhopper` | `backend`: kein `depends_on: graphhopper`, keine Mounts `osm_data`/`gh_graph`, `GRAPHHOPPER_URL` **Pflicht** (`${GRAPHHOPPER_URL:?}`); `updater`: keine Mounts `osm_data`/`gh_graph`; Volumes `osm_data`, `gh_graph` fehlen |
| `routing-host.yml` | `graphhopper`, `updater` | `graphhopper.ports`: `${GH_BIND:-127.0.0.1}:8989`; `updater`: kein `depends_on: backend`, nur die Env, die er hier braucht |

Die Duplikation ist Absicht und hat einen Wächter: ein Shell-Test in
`deploy/zwei-hosts/tests/` normalisiert alle drei Dateien mit `docker compose
config` und prüft, dass jede Dienstdefinition in den Zwei-Host-Dateien mit der
in `docker-compose.yml` übereinstimmt — **bis auf die Abweichungen in der
Tabelle**, die er ausdrücklich kennt. Wer einen Dienst in `docker-compose.yml`
ändert und die Kopie vergisst, sieht es in CI. Ohne diesen Test altern die
Kopien still; mit ihm sind sie eine Tabelle, die man pflegt.

Eine Änderung an `docker-compose.yml` selbst: `backend.depends_on.graphhopper`
(`condition: service_started`) fällt weg. Es ist eine reine Startreihenfolge
ohne Wirkung — GraphHopper braucht nach dem Start eine Stunde, bis er antwortet,
und `status.py` behandelt „nicht erreichbar" ohnehin. Damit sind Standard- und
App-Host-Definition des Backends bis auf die Mounts identisch.

---

## 4. Der Updater auf zwei Hosts

Der Updater ist die Stelle, an der dieser Plan scheitert, wenn man ihn zuletzt
anfasst. Vier Dinge, in der Reihenfolge ihrer Gefährlichkeit.

### 4.1 Er überschreibt die Stack-Datei — mit der falschen

`_update_stack_file` in `update-images.sh` holt bei jedem Update
`docker-compose.yml` vom Release-Ref aus dem Repo und schreibt sie nach
`STACK_FILE_PATH`. Auf Host A liegt dort `app-host.yml`. Beim ersten
Auto-Update ersetzt der Updater sie durch die Standarddatei, das nächste `up -d`
zieht `graphhopper` auf A hoch, und der Host steht wieder bei 95 % — nur diesmal
ohne dass jemand versteht, warum.

Deshalb bekommt der Updater `STACK_FILE_VARIANT` (Standard `docker-compose.yml`;
auf A `deploy/zwei-hosts/app-host.yml`, auf B `deploy/zwei-hosts/routing-host.yml`)
und holt genau diesen Pfad. Der Test dazu fährt `_update_stack_file` gegen einen
`curl`-Stub und prüft die angefragte URL — für alle drei Werte.

### 4.2 Er wartet auf ein Backend, das es nicht gibt

`do_update` wartet nach dem Deploy auf `healthy` vom Backend und rollt sonst
zurück. Auf Host B gibt es kein Backend: `_backend_cid` bleibt leer, die
Warteschleife läuft 180 s ins Leere, der Rollback scheitert an einem leeren
Image, `deploy_alert.json` wird geschrieben, das Update gilt als fehlgeschlagen,
`LAST_DEPLOYED_FILE` bleibt stehen — und in fünf Minuten geht es von vorn los.
Ein Updater, der jeden Deploy für gescheitert hält, deployt trotzdem jedes Mal
und meldet jedes Mal einen Fehler.

Das Health-Gate greift deshalb nur, wenn `backend` in `docker compose config
--services` steht. Steht es nicht dort, gilt der Deploy nach `up -d` als gut,
und `write_status` nimmt den Commit aus dem Label
`org.opencontainers.image.revision` des GraphHopper-Images statt aus einem
Backend, das es nicht gibt. Test: `test_graphhopper_import_deploy.sh` bekommt
einen Fall „Stack ohne Backend": kein `inspect` auf Health, kein Rollback,
`status.json` mit dem Label-Wert.

### 4.3 Kanal und Modus kommen aus Dateien, die niemand schreibt

`read_channel` und `read_mode` lesen `/update_status/channel` und `/mode`. Beide
schreibt das Backend — auf Host A. Auf B schreibt sie niemand, der Updater fällt
auf `stable` zurück, und die Instanz läuft mit einem Backend auf `nightly` gegen
einen GraphHopper auf `latest`. Das fällt erst auf, wenn ein Nightly-Backend ein
Feature braucht, das der Latest-Graph nicht hat (Encoded Values!).

`UPDATE_CHANNEL` und `UPDATE_MODE` aus der Umgebung werden im Updater zum
Fallback, wenn die Datei fehlt — die Datei gewinnt weiterhin, wo es sie gibt.
Das „Fallback-Env" aus `wiki/Auto-Updater.md` gibt es heute nur scheinbar: es
sitzt im **Backend** (`update_check.py` schreibt die Datei beim Start aus seiner
Env), keiner der beiden Updater liest die Variable selbst. Auf einem Host ohne
Backend greift es also nicht — genau der Fall hier. Auf B stehen beide Werte in
der `.env`, und der Wiki-Abschnitt sagt in einem Satz, dass Kanalwechsel im
Panel den Routing-Host **nicht** erreichen.

### 4.4 „Jetzt updaten" erreicht B nicht

Der Trigger aus dem Panel ist eine Datei in `update_status` auf A. B folgt
seinem eigenen Zyklus (`UPDATE_INTERVAL`, Standard 5 min). Das ist in Ordnung
und wird dokumentiert, nicht gelöst: ein Kanal von A nach B wäre entweder ein
geteiltes Dateisystem (fragil) oder ein Dienst auf B, der Befehle annimmt (neue
Angriffsfläche für einen Knopf, den man alle paar Wochen drückt).

`graphhopper-deploy.sh` (der Schutz gegen Deploys mitten im Import) braucht
nichts: auf B liegt `/data/graph`, die Prüfung greift wie heute; auf A liegt es
nicht, und die Funktion antwortet dann bewusst mit „kein Import".

---

## 5. Der Regionswechsel

`switch-region.sh` läuft **auf dem Host, auf dem GraphHopper läuft** — er stoppt
den Container, baut im Wegwerf-Container und tauscht im Volume. Auf B geht das
alles unverändert. Was auf B fehlt, ist die *Anforderung*: `region_request.json`
schreibt das Backend, und das steht auf A.

Drei Wege, und der billigste ist der ehrlichste:

1. Ein HTTP-Agent auf B, an den das Backend weiterreicht — neue Komponente, neue
   Angriffsfläche, eigene Auth. Für einen Vorgang, der zweimal im Jahr passiert.
2. `update_status` per NFS teilen — der Updater auf A und der auf B fassen dann
   dieselben Lock- und Statusdateien an. Nein.
3. **Anforderung per CLI auf B.** `docker/updater/region-request.sh` schreibt
   dieselbe JSON, die das Backend schreibt (`url`, `filename`, `java_opts`,
   `requested_by`, optional `sources` und `scheduled_for`), und die bestehende
   Pipeline übernimmt: Allowlist-Prüfung (die `switch-region.sh` ohnehin
   *beidseitig* macht), Download, Merge, Staging-Import, Tausch, Rollback. Der
   Fortschritt steht in `region.log` auf B.

Der Plan nimmt (3). Das Panel auf A bekommt für die Karte „Kartenregion" einen
klaren Zustand statt eines 500ers: `region.py` prüft `ROUTING_HOST=extern` und
antwortet auf jeden Regions-Endpunkt mit `{"verfuegbar": false, "grund": …}`;
die Karte zeigt den Hinweis und darunter die **aktive Abdeckung** — die kommt
aus `graphhopper_bbox` in `/api/status`, das den Wert heute schon liefert.

Was `region.py` sonst noch liest, hängt an den Mounts: `disk_usage` auf
`/data/osm` und `/data/graph` (Vorschau des Wechsels), `.region` (aktive
Region), `-Xmx` aus `JAVA_OPTS` (zurückgewinnbarer Heap). Alles davon ist Teil
des Wechsels und auf A ohne Funktion — es sitzt hinter demselben Schalter.

---

## 6. Systemübersicht

Die Kachel „Container" zählt über `dockerproxy` — auf A künftig 7 statt 8, und
GraphHopper fehlt darin. Dafür gibt es eine Kachel **Routing** aus
`/api/status`: `ok` / `building` / `offline` plus Abdeckung. `_graphhopper_probe`
liefert das heute schon; die Kachel ist Anzeige, kein neuer Endpunkt.

Was **fehlt** und in diesem Plan bewusst fehlt: die Hostmetriken von B (RAM,
Platte, Last). Das Backend misst nur den Host, auf dem es läuft. Ob B beim
nächsten Import in den Swap läuft, sieht man in ConvoyPlan nicht — man sieht es
an `status: building`, das nicht mehr zu `ok` wird. Ein Nachtrag (Abschnitt 10)
kann `SYSTEM_METRICS` auf B erheben und an A melden; heute ist das ein Monitoring
außerhalb der App.

---

## 7. Der Umzug

Für „GraphHopper zieht um" (neuer Server ist B). Für „die App zieht um" kommt
vor Schritt 3 die Migration von Datenbank, Volumes, `.env` und DNS dazu — das
ist ein eigenes Runbook, das hier nicht steht.

**Vorher — B aufbauen, während A unverändert läuft.**

1. Docker auf B. Privates Netz, Firewall (`8989` nur von A).
2. `routing-host.yml` und `.env` auf B: `GITHUB_TOKEN`, `UPDATE_CHANNEL`,
   `UPDATE_MODE`, `STACK_FILE_VARIANT`, `GH_BIND`, `JAVA_OPTS` (hier darf es
   mehr sein als auf A — der Host gehört GraphHopper), `OSM_*`.
3. **Kartendaten kopieren, nicht neu bauen lassen.** Die zusammengesetzte
   Region entsteht aus sechs Downloads und einem `osmium merge`; auf einem
   frischen B wartet der Entrypoint auf eine Datei, die dort niemand baut.
   `rsync` von `merged-<hash>.osm.pbf` und `.region` aus `osm_data` auf A nach
   B (9 GB, im privaten Netz Minuten). Der *Graph* wird nicht kopiert — der
   baut sich, das ist der Zweck der Übung.
4. `docker compose -f routing-host.yml up -d`. Warten, bis `/health` antwortet
   (45–75 min). Route testen (Stuttgart → München).

**Umschalten — Minuten, und jederzeit umkehrbar.**

5. Auf A: `.env` bekommt `GRAPHHOPPER_URL=http://<B-privat>:8989`,
   `ROUTING_HOST=extern`, `STACK_FILE_VARIANT=deploy/zwei-hosts/app-host.yml`.
   Update-Modus vorher auf *Benachrichtigen* — nicht, dass der Updater mitten
   in den Schritt fährt.
6. `app-host.yml` als Stack-Datei nach `STACK_FILE_PATH` (die alte Datei
   daneben aufheben).
7. `docker compose up -d --remove-orphans`. **`--remove-orphans` ist der
   Schritt**: ohne ihn läuft der alte GraphHopper-Container auf A weiter, hält
   seine 13,7 GB, und nichts ist gewonnen. Die Volumes bleiben — sie sind der
   Rückweg.
8. Prüfen: `/api/status` meldet `graphhopper: ok`; eine Route im UI;
   Systemübersicht 7/7 plus Routing-Kachel; `free -h` auf A liegt bei ~2 GB.
   Update-Modus zurück auf *Automatisch*.

**Rollback**, an jeder Stelle bis Schritt 9: alte Stack-Datei zurück, die drei
`.env`-Einträge raus, `up -d`. Der Graph liegt noch im Volume auf A;
GraphHopper ist in zwei Minuten wieder oben.

**Nachher.**

9. Eine Woche laufen lassen. Dann auf A `gh_graph` und `osm_data` löschen
   (~26 GB). Ab hier ist der Rückweg ein Neubau, kein `up -d` mehr.
10. Wenn die App umgezogen ist: alten Server kündigen, nicht nur abschalten.

---

## 8. Reihenfolge der Umsetzung

Jede Phase hat einen Test, und keine Phase ändert das Verhalten der
Standardinstallation — das prüft `docker compose config` gegen den Stand vor
dem Plan.

| Phase | Änderung | Test |
|---|---|---|
| **1 — Updater zuerst** | `STACK_FILE_VARIANT`; Health-Gate nur mit Backend im Stack; `UPDATE_CHANNEL`/`UPDATE_MODE` als Fallback | `test_update_stack_variant.sh` (neu), Fall „ohne Backend" in `test_graphhopper_import_deploy.sh`, Fallback-Fälle in `test_update_lock_precedence.sh` |
| **2 — Compose** | `deploy/zwei-hosts/{app,routing}-host.yml`; `GH_BIND`; `depends_on.graphhopper` raus | `deploy/zwei-hosts/tests/test_dateien_deckungsgleich.sh`: Dienstdefinitionen bitgleich bis auf die Tabelle in Abschnitt 3; `GH_BIND`-Standard ist `127.0.0.1` |
| **3 — Backend** | `ROUTING_HOST=extern`: Regions-Endpunkte antworten „nicht verfügbar", keine Zugriffe auf `/data/*` | `test_region_api.py`: jeder Regions-Endpunkt ohne Mounts → 200 mit `verfuegbar: false`, nie 500 |
| **4 — Panel** | Karte „Kartenregion" mit Hinweis + Abdeckung; Kachel „Routing" in der Systemübersicht | E2E: Hülle mit `verfuegbar: false` zeigt Hinweis, keinen Wechsel-Knopf; Routing-Kachel folgt `/api/status` |
| **5 — CLI** | `docker/updater/region-request.sh` | Stub-Test: geschriebene JSON entspricht der des Backends (gleiche Schlüssel, gleiche Validierung greift in `switch-region.sh`) |
| **6 — Doku** | `wiki/Installation-und-Setup.md`, Abschnitt „GraphHopper auf eigenem Host"; `CLAUDE.md` | — |
| **7 — Umzug** | Abschnitt 7 | Route im UI |

Phase 1 kann für sich gemerged werden und ist auch für die Standardinstallation
richtig (der Fallback ändert dort nichts, weil die Dateien existieren). Phasen 2
bis 5 gehören in einen PR, weil die Compose-Dateien ohne den Backend-Schalter
eine Instanz mit 500ern in der Kartenregion ergäben.

---

## 9. Die Alternative, die 0 € kostet

Der Vollständigkeit halber, weil sie im Gespräch kurz auf dem Tisch lag und
nicht deshalb falsch ist, weil dieser Plan gewählt wurde: GraphHopper kann den
Graphen statt auf dem Heap als Memory-Mapped-Datei halten
(`graph.dataaccess.default_type: MMAP_STORE`). Der Heap fällt grob auf die
Hälfte, der Page-Cache übernimmt; der Import wird deutlich langsamer, das
Routing bei kaltem Cache etwas. Dazu `vm.max_map_count` auf dem Host.

Das ist eine Zeile im Entrypoint (`GH_DATAACCESS`, Standard `RAM_STORE`), und
sie hilft **auch** auf Host B: mit MMAP passt auf einen 16-GB-Routing-Host eine
Region, die heute nicht passt. Beides zusammen ist die Aufstellung mit der
meisten Luft.

---

## 10. Nicht in diesem Plan

- **Hostmetriken von B** in der Systemübersicht (Abschnitt 6).
- **`install.sh --role app|routing`.** Erst, wenn die Topologie einmal von Hand
  aufgebaut wurde und die Stellen bekannt sind, die der Installer treffen muss.
- **Regionswechsel aus dem Panel auf B.** Bewusst CLI (Abschnitt 5).
- **Hochverfügbarkeit.** Zwei Hosts sind hier zwei Rollen, nicht zwei
  Replikate. Fällt A aus, ist die App weg; fällt B aus, ist das Routing weg. Das
  ist genau der Zustand von heute, nur auf zwei Rechnungen.
- **Portainer-Stack** für die Zwei-Host-Aufstellung.
