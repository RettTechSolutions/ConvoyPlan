# Installation und Setup

Diese Seite beschreibt die Installation von ConvoyPlan auf einem Server. Für die
Arbeit am Code (Backend/Frontend lokal, Tests, Migrationen) siehe
**[Entwicklung](Entwicklung)**.

> **Kurz gesagt:** Den Installer benutzen. Für den Betrieb ist **kein**
> `git clone` nötig. Die `docker-compose.yml` zieht fertige Images aus der GitHub
> Container Registry und baut nichts selbst, ein `--build` hat also keine
> Wirkung. Wer im Repository-Klon `docker compose up` aufruft, scheitert an der
> fehlenden `.env` (`required variable POSTGRES_PASSWORD is missing a value`).

---

## Voraussetzungen

| Komponente | Zweck |
|---|---|
| Docker Engine + Docker Compose Plugin | Alle Dienste laufen als Container |
| `curl`, `openssl`, `sudo` (Linux) | Werden vom Installer benutzt |
| Ports `80` und `443` von außen erreichbar | Caddy, Let's Encrypt |
| DNS-Eintrag der Domain auf den Server | Für ein öffentliches Zertifikat |
| Arbeitsspeicher je nach Kartenregion | Für den Import des Routing-Graphen, siehe Tabelle |

| Region | Download | RAM für den Import (`-Xmx`) | Erster Import ca. |
|---|---|---|---|
| DACH (Standard) | ~5,5 GB | 8 GB | 60–120 Min. |
| Deutschland | ~4 GB | 6 GB | 45–90 Min. |
| Bayern | ~1 GB | 3 GB | 10–20 Min. |
| Berlin (zum Testen) | ~30 MB | 1 GB | wenige Minuten |

Im laufenden Betrieb braucht GraphHopper deutlich weniger, siehe `GH_DATAACCESS`
unter [GraphHopper](#graphhopper).

---

## Installation mit dem Installer (empfohlen)

**Linux:**

```bash
curl -sSL https://convoyplan.de/install.sh | bash
```

**Windows (PowerShell als Administrator):**

```powershell
irm https://convoyplan.de/install.ps1 | iex
```

Der Installer fragt interaktiv nach:

1. **Installationsverzeichnis**: Standard `~/convoyplan`, unter Windows `%USERPROFILE%\convoyplan`
2. **Domain** (FQDN, z. B. `convoy.example.com`)
3. **E-Mail für Let's Encrypt**
4. **Datenbankpasswort** (zweimal)
5. **OSM-Region**: DACH, Deutschland, Bayern, Berlin oder eine eigene Geofabrik-URL
6. **Lizenzschlüssel** (optional): Enter = Demo-Modus, später im Admin-Bereich nachtragbar

Einen GitHub-Token fragt der Installer nicht ab. Das Repository ist öffentlich,
der Auto-Updater kommt ohne aus (siehe [Auto-Updater](Auto-Updater#github-token-optional)).

Danach läuft er ohne weitere Rückfragen durch:

- Er lädt `docker-compose.yml` und `caddy/entrypoint.sh` aus `main` ins Installationsverzeichnis.
- Er schreibt die `.env` (Rechte `600`) mit DB-Zugang, Domain, Region und einem
  frisch erzeugten `JWT_SECRET`. Dazu kommen die Image-Adressen und die Pfade, die der
  [Auto-Updater](Auto-Updater) braucht (`STACK_FILE_PATH`, `CADDY_ENTRYPOINT_PATH`,
  `COMPOSE_PROJECT_NAME=convoyplan`).
- Er führt `docker compose pull` und `docker compose up -d` aus. Im Terminal
  fährt dabei ein Konvoi als Fortschrittsanzeige über den Bildschirm. Beim Laden
  der Images rückt er je fertigem Dienst vor. Die Docker-Ausgabe erscheint dann
  nur bei einem Fehler. Wer sie vollständig sehen will, startet mit
  `CONVOYPLAN_PLAIN=1` (Linux: `curl -sSL https://convoyplan.de/install.sh | CONVOYPLAN_PLAIN=1 bash`).
- Unter Linux mit systemd richtet er zusätzlich einen Watchdog-Timer ein
  (`convoyplan-updater-watchdog.timer`, alle 2 Minuten). Er holt einen
  hängengebliebenen Updater zurück.

Am Ende nennt der Installer die Adresse des Setup-Wizards:
`https://<DOMAIN>/setup`. GraphHopper baut den Routing-Graphen im Hintergrund,
und bis dahin gibt es keine Routenberechnung. Fortschritt anzeigen:

```bash
cd ~/convoyplan
docker compose logs -f graphhopper
docker compose ps        # Zustand und Healthchecks aller Dienste
```

> ⚠️ **Die `docker-compose.yml` im Installationsverzeichnis nicht von Hand
> ändern.** Der Installer ersetzt sie bei jedem Lauf und der Auto-Updater bei
> Updates. Eigene Einstellungen gehören in die `.env`. Dort ist praktisch jeder
> Wert der Compose-Datei als Variable herausgeführt (siehe [Konfiguration](#konfiguration)).

### Erneut ausführen: Aktualisieren oder neu konfigurieren

Updates spielt normalerweise der [Auto-Updater](Auto-Updater) ein. Der Installer
lässt sich trotzdem jederzeit erneut starten. Findet er im gewählten Verzeichnis
eine vollständige `.env`, bietet er zwei Wege an:

- **[J] Nur aktualisieren** (Standard): Die Einstellungen bleiben, fehlende
  Einträge werden ergänzt, Compose-Datei und Images erneuert, der Stack wird neu gestartet.
- **[n] Neu konfigurieren**: Alle Fragen kommen erneut, die bisherigen Werte
  sind vorausgewählt. Datenbankpasswort, Region und Lizenzschlüssel bleiben
  mit Enter erhalten, ein vorhandener `GITHUB_TOKEN` bleibt ohne Rückfrage. `JWT_SECRET` wird nicht abgefragt
  und bleibt immer, damit bestehende Anmeldungen und MFA-Secrets gültig bleiben.

---

## Setup-Wizard

Beim ersten Aufruf leitet die Anwendung automatisch auf `/setup` weiter. Der
fünfstufige Wizard führt durch:

1. **Superadmin-Account**: E-Mail-Adresse und Passwort festlegen.
2. **Erste Organisation**: Org-Name und Org-Code anlegen (URL-Slug, 4–8 Zeichen). Der Slug wird Teil aller org-spezifischen URLs (`/o/[slug]/plan/`, `/o/[slug]/admin/`).
3. **Domain und SSL**: Serverdomain (FQDN) eingeben und TLS-Modus wählen:
   - **Let's Encrypt**: automatisches öffentliches Zertifikat
   - **Eigenes Zertifikat**: PEM-Datei hochladen
   - **Intern**: selbstsigniertes Zertifikat für lokale Nutzung
4. **Branding** (optional): App-Name, Farben und Logo anpassen. Lässt sich überspringen und ist später im Admin-Bereich erreichbar.
5. **Abschluss**: Caddy wird live neu geladen, danach geht es direkt zur Anmeldung unter `https://<DOMAIN>/o/[slug]/login`.

Den Lizenzschlüssel danach im Admin-Bereich unter **System → Lizenz** eintragen.
Ohne Schlüssel läuft die Instanz im Demo-Modus (siehe
[Lizenz und Demo-Modus](Lizenz-und-Demo-Modus)).

---

## Manuelle Installation (ohne Installer)

Nur nötig, wenn der Installer nicht in Frage kommt. Er ist ein Shell-Skript und
macht nichts anderes als die Schritte hier. Ein Repository-Klon wird auch hier
nicht gebraucht:

```bash
mkdir -p ~/convoyplan/caddy && cd ~/convoyplan
RAW=https://raw.githubusercontent.com/RettTechSolutions/ConvoyPlan/main
curl -sSfL $RAW/docker-compose.yml -o docker-compose.yml
curl -sSfL $RAW/caddy/entrypoint.sh -o caddy/entrypoint.sh
curl -sSfL $RAW/.env.example        -o .env
chmod +x caddy/entrypoint.sh
chmod 600 .env
```

In der `.env` mindestens setzen:

| Variable | Wert |
|---|---|
| `POSTGRES_PASSWORD` | eigenes Passwort. Ohne Wert startet Compose gar nicht. |
| `JWT_SECRET` | `openssl rand -hex 32`. Mit dem Platzhalter startet das Backend nicht. |
| `DOMAIN`, `ACME_EMAIL` | FQDN bzw. E-Mail für Let's Encrypt |
| `STACK_FILE_PATH` | absoluter Pfad dieser `docker-compose.yml`, z. B. `/home/<user>/convoyplan/docker-compose.yml` (für den Auto-Updater) |
| `CADDY_ENTRYPOINT_PATH` | absoluter Pfad von `caddy/entrypoint.sh` |
| `COMPOSE_PROJECT_NAME` | `convoyplan` |

Dazu nach Bedarf Region und Speicher (`OSM_DOWNLOAD_URL`, `OSM_FILENAME`,
`JAVA_OPTS`, Werte siehe [Voraussetzungen](#voraussetzungen)). Danach:

```bash
docker compose pull
docker compose up -d
```

und den Setup-Wizard unter `https://<DOMAIN>/setup` aufrufen.

---

## Portainer

Portainer kann denselben Stack betreiben. Die Images liegen in der GitHub
Container Registry:

| Variable | Wert |
|---|---|
| `BACKEND_IMAGE` | `ghcr.io/retttechsolutions/convoyplan/backend:latest` |
| `FRONTEND_IMAGE` | `ghcr.io/retttechsolutions/convoyplan/frontend:latest` |
| `GRAPHHOPPER_IMAGE` | `ghcr.io/retttechsolutions/convoyplan/graphhopper:latest` |
| `UPDATER_IMAGE` | `ghcr.io/retttechsolutions/convoyplan/updater:latest` |
| `REGION_MERGE_IMAGE` | `ghcr.io/retttechsolutions/convoyplan/osmium:latest` |
| `POSTGRES_PASSWORD` | sicheres Datenbankpasswort (Pflicht) |
| `JWT_SECRET` | mit `openssl rand -hex 32` erzeugen (Pflicht) |
| `DOMAIN` / `ACME_EMAIL` | FQDN bzw. E-Mail für Let's Encrypt |

Caddy bindet `caddy/entrypoint.sh` per Bind-Mount ein (`CADDY_ENTRYPOINT_PATH`,
Standard `./caddy/entrypoint.sh`). Bei einem reinen Web-Editor-Stack liegt die
Datei nicht neben der Compose-Datei. Dann muss sie auf dem Host abgelegt und
`CADDY_ENTRYPOINT_PATH` auf diesen absoluten Pfad gesetzt werden.

> **Hinweis:** Der `updater` braucht die Compose-Datei auf dem Host
> (`STACK_FILE_PATH`). In Portainer übernimmt sonst Portainers eigener
> Stack-Update-Mechanismus das Deployment neuer Images.

---

## Konfiguration

Eine vollständige Vorlage liegt in `.env.example`. Die wichtigsten Variablen:

### Datenbank

| Variable | Beschreibung |
|---|---|
| `POSTGRES_USER` | Datenbankbenutzer |
| `POSTGRES_PASSWORD` | Datenbankpasswort – in Produktion zwingend ändern |
| `POSTGRES_DB` | Datenbankname |

### Backend

| Variable | Standard | Beschreibung |
|---|---|---|
| `DATABASE_URL` | *(aus POSTGRES_\* zusammengesetzt)* | PostgreSQL/PostGIS-Verbindung |
| `APP_ENV` | `production` | `production` erzwingt einen starken `JWT_SECRET` (Fail-Closed); `development` lockert die Prüfung für lokale Arbeit |
| `JWT_SECRET` | *(kein sicherer Default)* | Signaturschlüssel für JWTs – in Produktion zwingend ≥ 32 Zeichen; sonst **startet das Backend nicht** |
| `JWT_ALGORITHM` | `HS256` | JWT-Algorithmus |
| `JWT_EXPIRE_MINUTES` | `10080` | Token-Ablaufzeit in Minuten (7 Tage) |
| `GRAPHHOPPER_URL` | `http://graphhopper:8989` | URL der Routing-Engine |
| `APP_BASE_URL` | `https://convoyplan.example.com` | Öffentliche App-Origin (Fallback für CORS in Produktion) |
| `CORS_ORIGINS` | *(leer)* | Komma-getrennte Allowlist oder `*`; leer = App-Origin aus `APP_BASE_URL`. `*` nur in Entwicklung |

Sicheren JWT-Secret generieren (die Installer tun das automatisch):

```bash
openssl rand -hex 32
```

> ⚠️ In Produktion (`APP_ENV=production`, Default) verweigert das Backend den Start, wenn `JWT_SECRET` leer, der Platzhalter oder kürzer als 32 Zeichen ist (Fail-Closed).

### SSL / Caddy

| Variable | Beschreibung |
|---|---|
| `DOMAIN` | Serverdomain (z. B. `convoy.example.com`), Standard: `localhost` |
| `ACME_EMAIL` | E-Mail für Let's Encrypt |
| `CADDY_TLS_CERT` | Pfad zum PEM-Zertifikat (optional, für eigene Zertifikate) |
| `CADDY_TLS_KEY` | Pfad zum PEM-Schlüssel (optional, für eigene Zertifikate) |
| `HTTP_PORT` | Externer HTTP-Port, Standard: `80` |
| `HTTPS_PORT` | Externer HTTPS-Port, Standard: `443` |

### GraphHopper

| Variable | Standard | Beschreibung |
|---|---|---|
| `OSM_DOWNLOAD_URL` | `https://download.geofabrik.de/europe/dach-latest.osm.pbf` | Download-URL der OSM-PBF-Datei |
| `OSM_FILENAME` | `dach-latest.osm.pbf` | Dateiname im persistenten OSM-Volume |
| `JAVA_OPTS` | `-Xmx8g -Xms1g -XX:+UseG1GC` | JVM-Speicherkonfiguration für den **Graph-Import** |
| `GH_DATAACCESS` | `MMAP` | Speicherzugriff des laufenden Routing-Servers: `MMAP` (Graph im Seitencache des Kernels, JVM bleibt klein) oder `RAM_STORE` (Graph komplett im Java-Heap) |
| `GH_SERVER_JAVA_OPTS` | *(leer = Standard)* | Zusätzliche JVM-Optionen nur für den Server; Standard gibt ungenutzten Heap im Leerlauf zurück und beendet die JVM bei `OutOfMemoryError` |

> Richtwerte: DACH `-Xmx8g`, Deutschland `-Xmx6g`, Bayern `-Xmx3g`, Berlin `-Xmx1g`.
> Sie gelten für den Import. Im Betrieb liegt der Graph mit `GH_DATAACCESS=MMAP`
> im Seitencache statt im Heap — der Speicher wird also nur belegt, solange
> er nicht anderweitig gebraucht wird, und die JVM bleibt deutlich unter `-Xmx`.
> Wer genug RAM hat und die Einlesezeit nach einem Neustart vermeiden will,
> setzt `GH_DATAACCESS=RAM_STORE`. MMAP blendet den Graphen in 1-MB-Segmenten
> ein; ein 14-GB-Graph braucht damit rund 14 000 Mappings, der Linux-Standard
> `vm.max_map_count=65530` reicht also bis weit über 50 GB Graph.

> **Regionswechsel:** Die Variablen hier gelten nur für den **Erststart**. Zum
> Wechseln der Kartenregion im laufenden Betrieb gibt es seit `2026.4.0` die
> Karte „Kartenregion" im Admin-Panel unter **System** — dort mit
> Vorabschätzung von Speicher-, Platten- und Zeitbedarf, Live-Fortschritt und
> ohne nennenswerten Routing-Ausfall (der neue Graph entsteht neben dem
> laufenden). Seit `2026.5.0` lassen sich dort auch **mehrere** Regionen
> gleichzeitig wählen; sie werden zu einer Karte zusammengeführt, sodass
> Routen über die Ländergrenzen hinweg funktionieren.
>
> Die aktive Region liegt danach in `/data/osm/.region` im `osm_data`-Volume
> und hat Vorrang vor den Variablen aus der `.env` — so überlebt sie ein
> `docker compose up`. Wer die Variablen hier nachträglich ändert, ändert
> deshalb **nichts** an einer bereits per Panel gewechselten Installation.
>
> Der Umriss auf der Karte — die Maske, die alles außerhalb des routbaren
> Gebiets abdunkelt — folgt der aktiven Region automatisch: Das Backend leitet
> ihn unter `GET /api/region/outline` aus `.region` und den Geometrien des
> Geofabrik-Index ab. Bis `2026.5.2` war er eine mitgelieferte DACH-Datei und
> musste von Hand getauscht werden; wer das früher getan hat, braucht dafür
> jetzt nichts mehr zu tun.
>
> Bei einer aus mehreren Regionen zusammengesetzten Karte nennt die Karte
> „Kartenregion" unter **Aktuelle Region** zusätzlich die einzelnen
> Bestandteile — praktisch, um nach einem Wechsel nachzuvollziehen, welche
> Länder/Gebiete tatsächlich geladen sind, statt das nur am kryptischen
> `merged-<hash>.osm.pbf`-Dateinamen abzulesen. Bei nur einer Region entfällt
> die Zeile, da der Dateiname (z. B. `dach-latest.osm.pbf`) die Auskunft
> bereits enthält.
>
> **Wartungsmodus und Terminierung:** Seit `2026.6.0` lässt sich beim Wechsel
> die Option „Routing während des Imports pausieren" aktivieren. GraphHopper
> wird dabei angehalten, **bevor** der Graph gebaut wird, statt erst danach —
> sein Speicher steht damit dem Import zur Verfügung, wodurch große
> kombinierte Karten auf Maschinen mit knappem Arbeitsspeicher überhaupt erst
> baubar werden. Der Preis: keine Routenplanung, bis der Wechsel durch ist.
> Zusätzlich lässt sich unter „Startzeitpunkt" ein Termin für den Wechsel
> setzen (höchstens 30 Tage voraus, in der Vergangenheit abgelehnt) — sinnvoll
> in Kombination mit pausiertem Routing, wenn der Ausfall in eine
> nutzungsarme Zeit fallen soll. Ein geplanter Wechsel übersteht einen
> Neustart des Updaters und lässt sich bis zum Anlauf abbrechen; ohne Termin
> startet der Wechsel sofort. Die Speicherprüfung läuft dabei vor dem
> Download, nicht erst nach zwölf Minuten Import.
>
> **Abbruch:** Ein abgebrochener Wechsel wird als **„Abgebrochen"** gemeldet,
> nicht als „Fehlgeschlagen" — der Unterschied ist der zwischen einer erfüllten
> Absicht und einer Störung. Die bisherige
> Region läuft in beiden Fällen unverändert weiter. Abbrechen lässt sich bis
> einschließlich Phase 3 (Graph-Bau); ab dem Schwenk ist kein Abbruch mehr
> vorgesehen.
>
> **Wenn Geofabrik hakt:** Die Größenabfrage vor dem Wechsel läuft für alle
> Bestandteile gleichzeitig und wiederholt einen Fehlversuch zweimal (1 s, 3 s
> Pause). Bleibt sie erfolglos, nennt die Meldung die betroffene Region. Sie
> betrifft ausschließlich die Vorab-Rechnung — die geladene Karte und das
> Routing sind davon nicht berührt.

### Sicherheit und Datenschutz

| Variable | Standard | Beschreibung |
|---|---|---|
| `MFA_ENCRYPTION_KEY` | *(aus `JWT_SECRET` abgeleitet)* | Fernet-Schlüssel zur Verschlüsselung der TOTP-Secrets at-rest. Rotation von `JWT_SECRET` macht ohne eigenen Schlüssel bestehende MFA-Secrets unlesbar |
| `PASSWORD_BREACH_CHECK_ENABLED` | `true` | Abgleich neuer Passwörter gegen Have-I-Been-Pwned (k-Anonymity, fail-open). Für Air-Gapped-Setups auf `false` |
| `CSP_ENFORCE` | `false` | Content-Security-Policy erzwingen (Default: Report-Only, bricht die UI nicht) |
| `QUOTA_ROUTING_PER_HOUR` | `240` | Stundenbudget für Routenberechnungen (GraphHopper) je angemeldetem Benutzer. `0` = Drossel aus |
| `QUOTA_ROUTING_DEMO_PER_HOUR` | `40` | Dasselbe für Demo-Sitzungen (zusätzlich pro IP gezählt) |
| `QUOTA_GEOCODE_PER_HOUR` | `600` | Stundenbudget für die Adresssuche (HERE/Photon) je Benutzer |
| `QUOTA_GEOCODE_DEMO_PER_HOUR` | `100` | Dasselbe für Demo-Sitzungen |
| `QUOTA_TRAFFIC_PER_HOUR` | `600` | Stundenbudget für die Live-Verkehrslage (HERE/TomTom) je Benutzer |
| `QUOTA_TRAFFIC_DEMO_PER_HOUR` | `100` | Dasselbe für Demo-Sitzungen |
| `RETENTION_ENABLED` | `true` | Periodisches Purgen alter Daten durch den `retention`-Container |
| `RETENTION_INTERVAL` | `3600` | Sekunden zwischen den Purge-Läufen |
| `RETENTION_POSITIONS_HOURS` | `24` | Live-Positionen älter als dieser Wert werden gelöscht |
| `RETENTION_AUDIT_DAYS` | `365` | Audit-Log-Einträge älter als dieser Wert werden gelöscht |
| `RETENTION_SHARE_LINKS_DAYS` | `30` | Widerrufene Share-Links älter als dieser Wert werden gelöscht |
| `RETENTION_POSITION_TRAIL_DAYS` | `45` | Positionsverlauf der Aktionsseiten älter als dieser Wert wird gelöscht |
| `RETENTION_OAUTH_TOKENS_GRACE_DAYS` | `30` | Karenz für tote MCP-Refresh-Tokens — kürzer setzen schwächt die Wiederverwendungserkennung |
| `RETENTION_OAUTH_CLIENTS_DAYS` | `7` | Verwaiste MCP-Registrierungen (ohne Tokens und Codes) älter als dieser Wert werden gelöscht |
| `BACKUP_DIR` | `./backups` | Zielverzeichnis für `scripts/backup.sh` |
| `BACKUP_RETENTION_DAYS` | `30` | Aufbewahrungsdauer der Backups |

> Details zu Härtung, Audit-Log, DSGVO und Backup/Restore: **[Sicherheit und Datenschutz](Sicherheit-und-Datenschutz)**.

### Lizenz und Auto-Updater

| Variable | Beschreibung |
|---|---|
| `LICENSE_KEY` | Lizenzschlüssel. Ohne gültigen Schlüssel läuft die App im Demo-Modus. Alternativ über den Admin-Bereich eintragbar (wird dann in der DB gespeichert). |
| `GITHUB_TOKEN` | Optional. Hebt nur das Rate-Limit der GitHub-API (60 → 5000 Anfragen/Stunde je IP). Wenn, dann ein fine-grained Token mit „Public repositories (read-only)" ohne weitere Rechte. Details: [Auto-Updater](Auto-Updater#github-token-optional). |
| `GITHUB_REPO` | Repository, das der Auto-Updater überwacht. Standard: `RettTechSolutions/ConvoyPlan`. |
| `UPDATE_CHANNEL` | Fallback-Kanal: `stable` (Standard), `beta` oder `nightly`. Der Schalter im Admin-Bereich überschreibt diesen Wert. |
| `UPDATE_MODE` | Fallback-Modus: `auto` (Standard) oder `notify`. Der Schalter im Admin-Bereich überschreibt diesen Wert. |
| `UPDATE_NOTIFY_ON_AUTO` | Nur bei `auto`: `true` schickt zusätzlich eine E-Mail an Superadmins nach automatischer Installation (Standard: `false`). |
| `UPDATE_NOTIFY_INTERVAL` | Prüfintervall in Sekunden für fällige Update-Benachrichtigungen (Standard: `1800`). |

> Details: **[Auto-Updater](Auto-Updater)** und **[Lizenz und Demo-Modus](Lizenz-und-Demo-Modus)**.

### Verkehrsdaten

| Variable | Beschreibung |
|---|---|
| `HERE_TRAFFIC_API_KEY` / `TOMTOM_TRAFFIC_API_KEY` | Optionale API-Keys für die Live-Verkehrslage. Ohne Key bleibt die Funktion inaktiv. Alternativ im Admin-Bereich hinterlegbar (hat Vorrang). |
| `TRAFFIC_FLOW_PROVIDER` | Anbieter erzwingen (`here`/`tomtom`). Standard: automatisch, HERE bevorzugt. |
| `HERE_API_KEY` | Optional. Aktiviert die Adresssuche im Plan-Editor über HERE Geocoding & Search (serverseitig proxied). Leer = `HERE_TRAFFIC_API_KEY` mitbenutzen bzw. Photon-Fallback. |
| `HERE_MONTHLY_LIMIT` | Kostendeckel für die Adresssuche: max. HERE-Anfragen pro Kalendermonat (Standard `25000`, `0` = kein App-Deckel). Deckel erreicht → automatischer Photon-Fallback. |
| `OPENDATA_TRAFFIC_ENABLED` | Offene Baustellen-/Sperrungsfeeds aktiviert lassen. Standard: `true`. |
| `OPENDATA_TRAFFIC_FEEDS` | Kommaseparierte Liste `format\|url`. Formate: `mobidata_bw`, `berlin_viz`, `datex2`. |
| `OPENDATA_TRAFFIC_CLIENT_CERT` | Client-Zertifikat (PEM) für per mTLS geschützte `datex2`-Feeds (mobilithek). |
| `OPENDATA_TRAFFIC_CA_CERT` | Nur für Broker mit **privater** CA. Für den mobilithek-Broker **leer lassen**. |

> Schritt-für-Schritt-Anleitung: **[Verkehrsdaten](Verkehrsdaten)**.

---

## Kartenregion wechseln

Die Region wechselt man im laufenden Betrieb im Admin-Panel unter **System →
Kartenregion** (siehe oben). Der neue Graph entsteht dabei neben dem laufenden.

Die Vorabschätzung rechnet den Heap für den Import als `(2 GB + 1,1 × Extract)`
plus 20 % Sicherheitsaufschlag. Gesperrt wird ein Wechsel erst, wenn schon der
Bedarf **ohne** Aufschlag nicht in den freien Speicher (abzüglich 1 GB Reserve)
passt — dieselbe Schwelle, an der der Updater abbräche. Passt nur der Aufschlag
nicht, heißt das „knapp": Der Import läuft mit gedeckeltem Heap, und
„Routing während des Imports pausieren" gibt ihm den Speicher des laufenden
GraphHopper dazu.

Gutgeschrieben wird dabei, was GraphHopper **tatsächlich** belegt, gemessen am
Container (Panel über den `dockerproxy`, Updater über die cgroup), nicht sein
`-Xmx`. Seit der Server den Graphen per MMAP einblendet, sind das meist nur
einige hundert MB — der Wartungsmodus bringt also deutlich weniger als früher.
Lässt sich nicht messen, nennt das Panel den `-Xmx` als Obergrenze und sagt
dazu, dass er nicht gemessen ist.

Wie viel Heap ein Import wirklich gebraucht hat, steht am Ende seines Protokolls
im Panel (`garbage-first heap total …K`). Auf der Platte belegt der fertige
Graph erfahrungsgemäß gut die Hälfte des Extracts (gemessen: 8,5 GB Extracts,
4,9 GB Graph).

Nur wenn das nicht geht, lässt sich der Graph-Cache von Hand verwerfen. Danach
ist das Routing bis zum Ende des Neuimports weg:

```bash
cd ~/convoyplan
docker compose down
docker volume rm convoyplan_gh_graph
docker compose up -d
```

---

## Checkliste für Produktion

- [ ] Installation über den Installer, nicht aus einem Repository-Klon
- [ ] `JWT_SECRET` stark und nirgends versioniert (der Installer erzeugt ihn)
- [ ] Eigenes Datenbankpasswort
- [ ] `CORS_ORIGINS` leer lassen oder auf die produktive Domain einschränken, nie `*`
- [ ] Persistente Volumes (`postgres_data`, `caddy_data`, `cert_uploads`, `logo_uploads`) regelmäßig sichern, siehe `scripts/backup.sh`
- [ ] Genug RAM für den Import der gewählten Region (siehe [Voraussetzungen](#voraussetzungen))
- [ ] GraphHopper-Graph-Cache (`gh_graph`) auf schnellem Speicher
- [ ] Lizenzschlüssel eintragen (Admin → System → Lizenz), sonst läuft die Instanz dauerhaft im Demo-Modus

---

## Nützliche Docker-Befehle

Im Installationsverzeichnis (Standard `~/convoyplan`):

```bash
docker compose ps                   # Zustand und Healthchecks
docker compose logs -f backend      # Backend-Logs
docker compose logs -f graphhopper  # GraphHopper-Logs (Import-Fortschritt)
docker compose pull && docker compose up -d   # Images von Hand aktualisieren (Kanal-Tags aus .env, pflegt der Updater)
docker compose down                 # Dienste stoppen
docker compose down -v              # Dienste stoppen und ALLE Daten löschen
```

---

## Sicherheitshinweise

- `POSTGRES_PASSWORD` ist Pflicht. Ohne Wert verweigert Compose den Start, es gibt kein Standardpasswort.
- In Produktion (`APP_ENV=production`, Default) verweigert das Backend den Start, wenn `JWT_SECRET` leer, der Platzhalter oder kürzer als 32 Zeichen ist (Fail-Closed).
- Datenbank (`5432`) und GraphHopper (`8989`) sind nur an `127.0.0.1` gebunden, das Backend ist von außen nur über Caddy erreichbar.
- Die Caddy-Admin-API läuft auf Port `:2019` und ist nur intern im Docker-Netzwerk erreichbar.
- Caddy liefert Security-Header (HSTS, `X-Content-Type-Options`, `X-Frame-Options` u. a.) und eine Content-Security-Policy aus (Report-Only, mit `CSP_ENFORCE=true` erzwingbar).
- Die persistierte Caddyfile (`/certs/Caddyfile`, vom Setup-Wizard geschrieben) wird bei jedem Backend-Start gegen die aktuelle Header-Baseline geprüft und bei Bedarf neu erzeugt und live nachgeladen.
- Endpunkte, die fremdes Kontingent kosten (Routing, Adresssuche, Verkehrslage), haben ein Stundenbudget je Aufrufer (`QUOTA_*`).
- TOTP-Secrets werden Fernet-verschlüsselt at-rest gespeichert. Passwort- und MFA-Reset entziehen über die `token_version` alle bestehenden JWTs.
- Öffentliche Share-Links sind ohne Login abrufbar. Ihre Tokens sind wie vertrauliche Links zu behandeln und bei Bedarf zu widerrufen.
- Live-Tracking verarbeitet Standortdaten. Die Aufbewahrung regelt der `retention`-Container.

> Vollständige Übersicht: **[Sicherheit und Datenschutz](Sicherheit-und-Datenschutz)**.
