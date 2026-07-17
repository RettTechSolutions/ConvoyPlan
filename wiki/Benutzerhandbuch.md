# Benutzerhandbuch

Dieses Handbuch richtet sich an Planer, Fahrer und Administratoren, die ConvoyPlan im Alltag verwenden.

---

## Rollen

| Rolle | Berechtigungen |
|---|---|
| **Beobachter** | Routen und Live-Tracking lesen |
| **Fahrer** | Eigene Position aktualisieren, Fahrzeugstatus setzen |
| **Planer** | Konvois erstellen und bearbeiten, Fahrzeuge zuordnen, Routen berechnen |
| **Admin (Org)** | Alle Planer-Rechte + Organisationsverwaltung |
| **Superadmin** | Vollzugriff auf alle Bereiche und Benutzer |

---

## Anmeldung

1. Die Anwendung im Browser öffnen (z. B. `https://convoy.example.com`).
2. E-Mail-Adresse und Passwort eingeben.
3. Auf **Anmelden** klicken.

> Beim ersten Start der Instanz wird automatisch auf den **Setup-Wizard** weitergeleitet. Dieser muss zuerst abgeschlossen werden, bevor eine Anmeldung möglich ist.

---

## Ersteinrichtung (Setup-Wizard)

Der Setup-Wizard erscheint automatisch beim ersten Start.

### Schritt 1 – Superadmin-Account

E-Mail-Adresse und Passwort für den Superadmin-Account eingeben. Dieser Account hat vollen Zugriff auf alle Einstellungen.

### Schritt 2 – Domain und SSL

- **Domain:** Den vollständigen Domainnamen eingeben (z. B. `convoy.example.com`). Für lokale Tests `localhost` verwenden.
- **TLS-Modus wählen:**
  - *Let's Encrypt* – automatisches öffentliches Zertifikat (erfordert öffentlich erreichbare Domain)
  - *Eigenes Zertifikat* – PEM-Zertifikat und Schlüssel hochladen
  - *Intern* – selbstsigniertes Zertifikat für lokale Nutzung

### Schritt 3 – Abschluss

Caddy wird automatisch neu geladen. Danach ist die Anmeldung direkt möglich.

---

## Fahrzeuge verwalten

Fahrzeuge werden einmalig angelegt und können dann beliebigen Konvois zugeordnet werden.

### Fahrzeug anlegen

1. Im Menü **Fahrzeuge** öffnen.
2. **Neues Fahrzeug** klicken.
3. Felder ausfüllen:
   - **Funkrufname** (z. B. `RTW 1-1`)
   - **Kennzeichen**
   - **Abmessungen** (Länge, Breite in Metern)
   - **Gewicht** (kg)
   - **Kraftstoffart und Tankdaten** (für Kraftstoffplanung)
4. Speichern.

---

## Marschverband planen

### Neuen Konvoi erstellen

1. **Planung** im Menü öffnen.
2. **Neuer Konvoi** klicken und den Wizard starten:
   - Name und Beschreibung eingeben
   - Startzeit festlegen
   - Marschgeschwindigkeiten (innerorts / außerorts) eintragen
   - Fahrzeuge aus der Liste auswählen und zuordnen

### Wegpunkte setzen

1. Den Konvoi öffnen und zur **Kartenansicht** wechseln.
2. Auf der Karte Klicken um Wegpunkte zu setzen, oder über die Seitenleiste manuell hinzufügen.
3. Für jeden Wegpunkt kann festgelegt werden:
   - **Typ:** Start, Stopp, Kontrollpunkt, Tankhalt, Technischer Halt
   - **Haltezeit** in Minuten
   - **Zweck / Notiz**

### Route berechnen

1. Mindestens Start- und Zielpunkt setzen.
2. **Route berechnen** klicken.
3. GraphHopper berechnet die Route; ConvoyPlan erstellt automatisch den Zeitplan mit streckenproportionalen Ankunfts- und Abfahrtszeiten je Wegpunkt (ein Wegpunkt bei 40 % der Strecke bekommt auch 40 % der Fahrzeit als ETA). Der **Zeitplan**-Tab zeigt zusätzlich eine **Abmarsch**-Zeile (Startzeit) und eine **Ziel**-Zeile mit der Gesamt-Ankunftszeit.

### Konvoi bearbeiten

Bestehende Konvois können jederzeit vollständig bearbeitet werden: Name, Beschreibung, Start-/Endzeit, Geschwindigkeitsprofile und Wegpunkte.

---

## Teilverbände (Sub-Convoys)

Für mehrstufige Marschverbände können Teilverbände angelegt werden.

1. Einen Konvoi öffnen.
2. **Neuer Teilverband** klicken.
3. Name und Fahrzeuge des Teilverbandes eingeben.
4. Der Teilverband ist dem übergeordneten Konvoi zugeordnet.

---

## Export und Freigabe

### Marschbefehl als PDF

1. Konvoi öffnen → Reiter **Export**.
2. **PDF herunterladen** klicken.
3. Der Marschbefehl enthält Zeitplan, Wegpunkte, Fahrzeugliste und Kanalwechsel.

### GPX / JSON exportieren

1. Konvoi öffnen → Reiter **Export**.
2. **GPX exportieren** oder **JSON exportieren** wählen.
3. Die Datei kann in Navigationsgeräten oder zur Dokumentation verwendet werden.

### Route importieren

1. Konvoi öffnen → Reiter **Export** → Abschnitt **Import**.
2. GPX-Track oder GeoJSON-Datei hochladen.
3. Die Route wird in den Konvoi übernommen.

### Öffentlicher Freigabelink

1. Konvoi öffnen → **Freigabelink erstellen**.
2. Den Link teilen – Empfänger können die Route ohne Login einsehen.
3. Freigabelinks sollten wie vertrauliche Links behandelt werden.

---

## Live-Tracking

### Als Fahrer

1. Den Konvoi öffnen → Reiter **Tracking**.
2. Browser-Standortfreigabe erlauben.
3. **Tracking starten** klicken – die eigene Position wird automatisch übermittelt.
4. Fahrzeugstatus über die Statusschaltfläche aktualisieren:
   - *Geplant* → *Unterwegs* → *Angekommen*
   - Bei Verzögerung: *Verspätet* setzen

### Als Beobachter / Planer

1. Den Konvoi öffnen → Reiter **Tracking**.
2. Alle Fahrzeugpositionen werden in Echtzeit auf der Karte angezeigt.
3. Fahrzeugstatus (unterwegs, angekommen, verspätet) wird farblich markiert.

---

## Lagedaten

GeoJSON-Lagedaten können als zusätzliche Kartenebenen hochgeladen werden (z. B. Sperrzonen, Sammelplätze, Einsatzräume).

1. Konvoi öffnen → Reiter **Lage**.
2. **Layer hochladen** klicken und eine GeoJSON-Datei auswählen.
3. Der Layer wird sofort auf der Karte angezeigt.
4. Layer können ein- und ausgeblendet oder gelöscht werden.

---

## Wetter und Sperrungen

### Wetter

- Das Wetter-Widget wird direkt auf der Planungskarte angezeigt.
- Daten kommen von Open-Meteo – kein API-Key erforderlich.

### Sperrungen und Baustellen

1. In der Kartenansicht das **Sperrungen-Layer** aktivieren.
2. Aktuelle Sperrungen und Baustellen entlang der gesamten Route werden angezeigt – zusammengeführt aus OpenStreetMap/Overpass, der offiziellen Autobahn-API (bund.dev), lizenzfreien offenen Baustellenfeeds (MobiData BW, Berlin VIZ) und optional DATEX-II-Feeds der mobilithek (bundesweite Länder-Feeds, auch mTLS-geschützt). Fällt eine Quelle aus, liefern die anderen weiterhin Ergebnisse. Auf der Karte sind die Meldungen nach Schweregrad eingefärbt (rot = Voll-/Sperrung, gelb = Warnung/Hindernis, orange = Baustelle).

### Live-Verkehrslage (Stau)

Zeigt die Fließgeschwindigkeit entlang der Route als Ampel-Ebene (grün → gelb → rot) – wie bei Google Maps.

1. Die Funktion ist nur aktiv, wenn ein Superadmin einen HERE- oder TomTom-API-Key hinterlegt hat (Admin-Bereich oder Umgebungsvariable). Ohne Key erscheint kein Schalter.
2. Im Export-Tab bzw. auf der Planungskarte den Schalter **Verkehrslage laden** aktivieren.
3. Die Verkehrsdaten werden als farbige Linien direkt über die Karte gelegt.

> HERE/TomTom decken bundesweit ab – anders als die regionalen offenen Baustellenfeeds. Die Nutzungsbedingungen des jeweiligen Anbieters sind vor Produktivbetrieb zu prüfen.

---

## Leitstellen und Kanalwechsel

Leitstellen definieren Zuständigkeitsbereiche. Bei der Routenberechnung werden automatisch Kanalwechselpunkte ermittelt und im Zeitplan sowie im PDF ausgewiesen.

### Leitstelle anlegen (Admin)

1. **Admin-Bereich** öffnen → Reiter **Leitstellen**.
2. **Neue Leitstelle** klicken.
3. Name und Zuständigkeitsgebiet eintragen – das Gebiet kann direkt auf der Karte gezeichnet werden.

---

## Organisationen

Organisationen ermöglichen die mandantenfähige Nutzung: jede Organisation hat eigene Mitglieder und Rollen.

### Organisation anlegen

1. Im Menü **Organisationen** öffnen.
2. **Neue Organisation** anlegen.

### Mitglieder einladen

1. Organisation öffnen → **Mitglied einladen**.
2. E-Mail-Adresse eingeben und Rolle wählen.

### Rollen

| Rolle | Vergabe durch |
|---|---|
| Beobachter | Org-Admin |
| Fahrer | Org-Admin |
| Planer | Org-Admin |
| Org-Admin | Org-Admin oder Superadmin |

---

## Admin-Bereich

Superadmins haben Zugriff auf alle Verwaltungsfunktionen.

### Benutzer verwalten

1. **Admin** → **Benutzer**.
2. Benutzer aktivieren, deaktivieren oder Rolle ändern.

### Branding anpassen

1. **Admin** → **Branding**.
2. Logo hochladen, Primär- und Akzentfarbe sowie App-Name anpassen.
3. Eine Live-Vorschau zeigt die Änderungen sofort.

> Dies ist das **globale Plattform-Branding**. Jede Organisation kann zusätzlich ein eigenes Branding im Org-Admin-Bereich hinterlegen, das nur innerhalb ihres `/o/[slug]`-Bereichs gilt – siehe [Multi-Tenancy](Multi-Tenancy#org-spezifische-login-seite-und-branding).

### System und Updates

1. **Admin** → **Software-Update**.
2. Aktuelle und verfügbare Version werden angezeigt.
3. **Update-Kanal** wählen: **Stable** (Standard – nur veröffentlichte Releases), **Beta** (nummerierte Vorabversionen/Release-Kandidaten) oder **Nightly** (jeder Commit auf `main`, für Tests).
4. **Update-Modus** wählen: **Automatisch** (Standard – installiert verfügbare Updates im gewählten Kanal ohne weiteres Zutun) oder **Benachrichtigen** (informiert Superadmins per E-Mail, Installation erfolgt bewusst über **Jetzt updaten**).
5. Der Updater prüft standardmäßig alle 5 Minuten (`UPDATE_INTERVAL`) auf neue Stände im gewählten Kanal.
6. Optional: E-Mail-Benachrichtigung an alle aktiven Superadmins **nach** einem automatischen Update aktivieren.

### Live-Verkehrslage-Keys (Admin)

1. **Admin** → **Live-Verkehrslage (Stau)**.
2. HERE- und/oder TomTom-API-Key hinterlegen und bevorzugten Anbieter wählen.
3. Der Status zeigt, ob ein Key gesetzt ist (Datenbank oder Umgebungsvariable) und welcher Anbieter aktiv ist. Der gespeicherte Key wird nie im Klartext angezeigt.

### Demo-Sitzungen (Admin)

Jede Demo-Nutzung läuft als eigene, befristete Organisation.

1. **Admin** → **Demo-Sitzungen** zeigt alle offen laufenden Demo-Sitzungen mit Name, Ablaufzeit und Anzahl angelegter Konvois.
2. Die Spalte **Herkunft** zeigt Stadt/Region/Land der Sitzung, ermittelt aus der Client-IP beim Start der Sitzung (Geolokation läuft im Hintergrund und verzögert den Demo-Start nie). Bei privaten oder nicht auflösbaren IPs (z. B. lokale Entwicklung) bleibt das Feld leer.
3. Sitzungen können hier verlängert oder sofort beendet werden. Herkunftsdaten werden zusammen mit der Demo-Organisation vom Retention-Job gelöscht — siehe [Lizenz und Demo-Modus](Lizenz-und-Demo-Modus#offene-demo-sitzungen-verwalten-admin).

---

## Häufige Probleme

| Problem | Lösung |
|---|---|
| Route wird nicht berechnet | GraphHopper-Logs prüfen: `docker compose logs -f graphhopper`. Erster Start dauert mehrere Minuten. |
| Login schlägt fehl | JWT_SECRET in `.env` prüfen. Nach Änderung alle Container neu starten. |
| Karte lädt nicht | Internetverbindung für OSM-Kartenkacheln prüfen. |
| PDF ist leer | Route muss vor dem PDF-Export berechnet worden sein. |
| Tracking-Position wird nicht übertragen | Standortfreigabe im Browser erlauben. Verbindung zum WebSocket prüfen. |
