# 🚦 Verkehrsdaten einrichten — Baustellen, Sperrungen & Stau

ConvoyPlan blendet auf der Karte **Baustellen, Sperrungen und Hindernisse** sowie
optional die **Live-Verkehrslage (Stau)** ein. Die Daten stammen aus mehreren
Quellen, die zu einer gemeinsamen Ebene zusammengeführt werden („in einen Topf").
Fällt eine Quelle aus, liefern die anderen weiter.

Diese Anleitung zeigt, was **out of the box** läuft und wie du die optionalen
Quellen (Live-Stau, bundesweite Baustellen) aktivierst.

---

## 📊 Überblick — welche Quelle liefert was

| Quelle | Abdeckung | Kosten | Setup nötig? |
|---|---|---|---|
| **Autobahn-API** (bund.dev) | bundesweit, alle Autobahnen | frei | nein — läuft |
| **MobiData BW** | Baden-Württemberg (bis Kreisstraße) | frei | nein — läuft |
| **Berlin VIZ** | Berlin | frei | nein — läuft |
| **mobilithek (DATEX II)** | weitere Bundesländer (Bundes-/Landesstraßen) | frei | ✅ Abschnitt 3 |
| **HERE / TomTom** | Live-Verkehrslage (Stau), bundesweit | eigener API-Key (Freikontingent) | ✅ Abschnitt 2 |

> **Farbcodierung auf der Karte:** 🟠 Baustelle · 🔴 Sperrung · 🟡 Warnung/Hindernis ·
> Live-Verkehrslage grün→gelb→rot nach Staufaktor.

---

## 1. ✅ Sofort aktiv (kein Setup)

Autobahn-Baustellen/-Sperrungen (bundesweit) sowie die offenen Feeds für
**Baden-Württemberg** und **Berlin** sind standardmäßig aktiv. Nichts zu tun.

---

## 2. 🟢 Live-Verkehrslage (Stau) aktivieren — HERE oder TomTom

Die Echtzeit-Verkehrslage (wie das rot/orange Stau-Bild bei Google) gibt es nur
bei kommerziellen Anbietern — beide mit kostenlosem Kontingent.

1. **Kostenlosen API-Key holen:**
   - **HERE** — [platform.here.com](https://platform.here.com/) · 250.000 Anfragen/Monat gratis (empfohlen)
   - **TomTom** — [developer.tomtom.com](https://developer.tomtom.com/)
2. Im ConvoyPlan **Admin-Bereich → „Live-Verkehrslage (Stau)"** den Key eintragen
   und speichern. Fertig — im Plan-Export-Tab erscheint der Schalter
   **„🚦 Verkehrslage laden"**.

> ⚠️ **Lizenzhinweis:** Die Anzeige von HERE-/TomTom-Verkehrsdaten auf der
> OSM-Basiskarte kann lizenzpflichtig sein. Vor produktivem Einsatz die
> Nutzungsbedingungen des Anbieters prüfen.

> 💡 **Ein Key, zwei Funktionen:** HERE gibt **einen** API-Key für alle Produkte
> aus. Ist ein HERE-Key hinterlegt (hier oder als `HERE_TRAFFIC_API_KEY`), nutzt
> ihn ConvoyPlan **automatisch auch für die Adresssuche** im Plan-Editor
> (HERE Geocoding & Search, serverseitig proxied — der Key verlässt den Server
> nie). Ohne Key läuft die Adresssuche wie bisher über das offene Photon
> (komoot). Ein eigener `HERE_API_KEY` überschreibt den Traffic-Key nur für die
> Adresssuche.

> 💰 **Kostendeckel für die Adresssuche:** Damit auf dem HERE-**Base-Plan**
> (30.000 Transaktionen/Monat gratis, darüber kostenpflichtig) **keine Kosten**
> entstehen, begrenzt `HERE_MONTHLY_LIMIT` die HERE-Anfragen pro Kalendermonat
> (Standard **25.000**, mit Puffer unter dem Freikontingent). Ist der Deckel
> erreicht, läuft die Adresssuche für den Rest des Monats automatisch über das
> kostenlose Photon weiter — kein Ausfall. `0` schaltet den App-Deckel ab (dann
> greift nur HEREs eigenes Kontingent). Der Client reduziert die Anfragen
> zusätzlich (Suche erst ab 3 Zeichen, längere Tipp-Pause, Cache identischer
> Eingaben).
>
> **Ganz ohne Kostenrisiko:** Wer den **Limited Plan** (ohne Kreditkarte, 1.000
> Anfragen/Tag) nutzt, kann grundsätzlich nicht abgerechnet werden — dort führt
> ein erschöpftes Kontingent nur zum automatischen Photon-Fallback.

---

## 3. 🇩🇪 Bundesweite Baustellen über die mobilithek (DATEX II)

Für Baustellen/Sperrungen **abseits der Autobahn** in weiteren Bundesländern
nutzt ConvoyPlan die **mobilithek** (nationaler Zugangspunkt des Bundes) im
Standard **DATEX II**. Der Zugang ist kostenlos, erfordert aber ein Konto,
ein Zertifikat und ein abonniertes Datenangebot.

### 3.1 Konto, Organisation & Maschinenkonto (in der mobilithek)

1. Auf [mobilithek.info](https://mobilithek.info) registrieren und freischalten
   lassen.
2. Eine **Organisation** anlegen (Zertifikate & Datennutzungen hängen an der
   Organisation, nicht am persönlichen Profil).
3. In der Organisation ein **Maschinenkonto** anlegen und dafür ein
   **Client-Zertifikat** erzeugen. Beim Download vergibst du ein Passwort für die
   `.p12`-Datei — merken!

### 3.2 Baustellen-Angebote abonnieren → Broker-URLs

1. Unter **Datenangebote** ein **DATEX-II-Baustellen-Angebot** eines Bundeslands
   öffnen (Filter: Kategorie „Verkehr", Lizenz „frei/kostenlos").
2. Eine **Datennutzung** als **HTTP Client Pull** anlegen und mit dem
   Maschinenkonto verknüpfen.
3. Du erhältst eine **Broker-Abruf-URL** in dieser Form:
   ```
   https://mobilithek.info:8443/mobilithek/api/v1.0/subscription/<ID>/clientPullService?subscriptionID=<ID>
   ```
   Pro Bundesland ein Abo = eine URL.

### 3.3 Zertifikat konvertieren & auf dem Server ablegen

ConvoyPlan liest das Zertifikat als **PEM** (nicht `.p12`). Auf dem Server im
Installationsverzeichnis (Standard `~/convoyplan`):

```bash
cd ~/convoyplan
mkdir -p secrets

# .p12 → PEM (fragt nach dem beim Download vergebenen Passwort):
openssl pkcs12 -in /pfad/zu/certificate.p12 -out secrets/mobilithek-client.pem -nodes

# WICHTIG: der Container-User (appuser, UID 1001) muss lesen dürfen:
sudo chown -R 1001:1001 secrets
sudo chmod 700 secrets
sudo chmod 600 secrets/*
```

> 🔒 **Geheimhaltung:** `mobilithek-client.pem` enthält den privaten Schlüssel —
> nur auf dem Server, **niemals ins Git**. (Der Ordner `secrets/` ist per
> `.gitignore` ausgeschlossen.)

### 3.4 `.env` konfigurieren

In `~/convoyplan/.env` ergänzen — die Feeds kommasepariert, jeweils als
`datex2|<url>`:

```bash
OPENDATA_TRAFFIC_CLIENT_CERT=/secrets/mobilithek-client.pem
OPENDATA_TRAFFIC_FEEDS=mobidata_bw|https://api.mobidata-bw.de/datasets/traffic/roadworks/roadworks_geojson.json,berlin_viz|https://api.viz.berlin.de/daten/baustellen_sperrungen_viz.json,datex2|<broker-url-land-1>,datex2|<broker-url-land-2>
```

> ⚠️ **`OPENDATA_TRAFFIC_CA_CERT` NICHT setzen!** Der mobilithek-Broker
> (`mobilithek.info:8443`) nutzt ein **öffentliches Telekom-Zertifikat** — die
> Prüfung läuft über den System-Truststore. Setzt man die mobilithek-„CA-Kette",
> **bricht** die Verbindung (`self-signed certificate in chain`).

### 3.5 Neu starten & prüfen

```bash
docker compose up -d backend

# Erreichbarkeit + Anzahl der Verkehrs-Features:
docker compose exec backend python -c "import asyncio; from app.services import opendata_traffic as o; print(len(asyncio.run(o._get_features())), 'Features')"
```

Steigt die Zahl deutlich an, fließen die Länder-Feeds. Auf der Karte erscheinen
die Baustellen nach spätestens dem 5-Minuten-Cache.

---

## 4. 🛠️ Fehlerbehebung

| Symptom | Ursache & Lösung |
|---|---|
| **Backend startet nicht, Log: `Can't locate revision '00xx'`** | Das laufende Image ist **älter** als die Datenbank. Aktuelles Image ziehen: `docker compose pull backend && docker compose up -d backend`. **Nicht** die DB downgraden. |
| **`PermissionError [Errno 13]` beim Zertifikat** | Datei gehört nicht dem Container-User. `sudo chown 1001:1001 secrets/* && chmod 600 secrets/*`. |
| **`CERTIFICATE_VERIFY_FAILED: self-signed certificate in chain`** | `OPENDATA_TRAFFIC_CA_CERT` ist gesetzt — **entfernen** (der Broker nutzt ein öffentliches Zertifikat). |
| **`HTTP 400` beim `curl`-Test** | Fehlender `Accept-Encoding: gzip`-Header — der Broker liefert immer gzip. Beim `curl`-Test `--compressed` nutzen; ConvoyPlan (httpx) sendet das automatisch. |
| **`HTTP 204` / leer** | Noch **kein Datenpaket** im Puffer — das Abo ist frisch oder der Anbieter hat noch nicht publiziert. Kommt automatisch. |
| **`HTTP 403 / 404`** | Datennutzung/Zertifikat nicht scharfgeschaltet bzw. Abo ungültig — in der mobilithek den Status der Datennutzung prüfen. |
| **Feature-Zahl steigt nicht** | Feeds testen (siehe unten), `.env`-Werte prüfen (`docker compose exec backend printenv | grep OPENDATA_TRAFFIC`). |

**Einzelnen Feed direkt testen** (auf dem Server, mit Zertifikat):

```bash
curl -s --compressed --cert secrets/mobilithek-client.pem \
  "https://mobilithek.info:8443/mobilithek/api/v1.0/subscription/<ID>/clientPullService?subscriptionID=<ID>" \
  | head -c 300
```
Kommt `<?xml … <d2LogicalModel …` zurück, ist alles korrekt.

---

## 📋 Referenz — Umgebungsvariablen

| Variable | Zweck |
|---|---|
| `OPENDATA_TRAFFIC_ENABLED` | Offene Baustellenfeeds an/aus (Standard `true`) |
| `OPENDATA_TRAFFIC_FEEDS` | Feed-Liste `format\|url`, kommasepariert. Formate: `mobidata_bw`, `berlin_viz`, `datex2` |
| `OPENDATA_TRAFFIC_CLIENT_CERT` | Pfad zum mTLS-Client-Zertifikat (PEM) für `datex2`-Feeds |
| `OPENDATA_TRAFFIC_CA_CERT` | Nur für Broker mit **privater** CA. Für die mobilithek **leer lassen**. |
| `HERE_TRAFFIC_API_KEY` / `TOMTOM_TRAFFIC_API_KEY` | Live-Verkehrslage (alternativ im Admin-Panel) |
| `TRAFFIC_FLOW_PROVIDER` | `here` / `tomtom` erzwingen (leer = automatisch, HERE bevorzugt) |
| `HERE_API_KEY` | Adresssuche über HERE Geocoding & Search. Leer = HERE-Traffic-Key mitbenutzen bzw. Photon-Fallback |
| `HERE_MONTHLY_LIMIT` | Kostendeckel: max. HERE-Anfragen/Monat für die Adresssuche (Standard 25000, `0` = aus). Deckel erreicht → Photon-Fallback |

> 💡 Die Zertifikatsdateien werden über den Host-Ordner `./secrets` read-only nach
> `/secrets` in den Container gemountet (siehe `docker-compose.yml`).
