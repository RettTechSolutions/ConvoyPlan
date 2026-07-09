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
3. GraphHopper berechnet die Route und erstellt automatisch den Zeitplan mit Ankunfts- und Abfahrtszeiten.

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
2. Aktuelle Sperrungen und Baustellen aus OpenStreetMap werden auf der Route angezeigt.

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

### System und Updates

1. **Admin** → **System**.
2. Aktueller und verfügbarer Commit-SHA werden angezeigt.
3. Mit **Update auslösen** kann ein manuelles Deployment gestartet werden.
4. Der Auto-Updater prüft alle 5 Minuten auf neue Commits und deployt automatisch.

---

## Häufige Probleme

| Problem | Lösung |
|---|---|
| Route wird nicht berechnet | GraphHopper-Logs prüfen: `docker compose logs -f graphhopper`. Erster Start dauert mehrere Minuten. |
| Login schlägt fehl | JWT_SECRET in `.env` prüfen. Nach Änderung alle Container neu starten. |
| Karte lädt nicht | Internetverbindung für OSM-Kartenkacheln prüfen. |
| PDF ist leer | Route muss vor dem PDF-Export berechnet worden sein. |
| Tracking-Position wird nicht übertragen | Standortfreigabe im Browser erlauben. Verbindung zum WebSocket prüfen. |
