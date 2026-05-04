# Ansatz: Marschverbandsplanung als WebApp

## 1. Grundidee

Das Projekt wird zunächst als browserbasierte WebApp umgesetzt.

Die WebApp dient primär zur:
- Planung von Marschverbänden
- Erstellung von Routen
- Verwaltung von Fahrzeugen
- Berechnung von Durchlaufzeiten
- Export der Route für Navigation

Eine native App kann später folgen.

---

## 2. Technischer Ansatz

## Frontend

Empfehlung:
- React
- Vue
- SvelteKit
- alternativ Flutter Web

Kartenkomponente:
- Leaflet
- OpenLayers
- MapLibre GL

Kartendaten:
- OpenStreetMap

---

## Backend

Aufgaben:
- Benutzerverwaltung
- Speichern von Routen
- Fahrzeugverwaltung
- Marschverbandsverwaltung
- Berechnung von Zeitplänen
- Exportfunktionen

Geeignete Technologien:
- Node.js / NestJS
- Python FastAPI
- Go
- Java Spring Boot

---

## 3. Routing

Mögliche Routing-Engines:
- GraphHopper
- OSRM
- Valhalla

Empfehlung:
- GraphHopper oder Valhalla, weil Fahrzeugprofile besser anpassbar sind.

Routingparameter:
- maximale Höhe
- maximales Gewicht
- Fahrzeugtyp
- Geschwindigkeit innerorts
- Geschwindigkeit außerorts
- Vermeidung bestimmter Straßen
- Wegpunkte
- technische Halte

---

## 4. App-Modell

## Planungsmodus

Funktionen:
- Route auf Karte planen
- Wegpunkte setzen
- technische Halte definieren
- Durchlaufpunkte setzen
- Fahrzeugdaten hinterlegen
- Konvoi zusammenstellen
- Teilverbände vorbereiten
- Zeitplan automatisch berechnen

## Navigationsmodus

Funktionen:
- geplante Route anzeigen
- Zeit-/Wegpunktliste anzeigen
- Route als GPX exportieren
- Route per Link teilen
- später: Live-Position anzeigen

---

## 5. Progressive Web App

Die WebApp sollte direkt als PWA geplant werden.

Vorteile:
- installierbar auf Android/iOS
- Startsymbol auf Homescreen
- Offline-Caching möglich
- kein App-Store-Zwang in der ersten Phase

Einschränkung:
- iOS ist bei Hintergrundnavigation und GPS teilweise restriktiver als Android.

---

## 6. Datenmodell grob

### Marschverband

- ID
- Name
- Organisation
- Startzeit
- Startpunkt
- Zielpunkt
- geplante Route
- Fahrzeuge
- Wegpunkte
- Status

### Fahrzeug

- ID
- Name
- Funkrufname
- Kennzeichen
- Höhe
- Gewicht
- Länge
- Funktion im Konvoi

### Wegpunkt

- ID
- Name
- Typ
- Koordinaten
- geplante Ankunft
- geplante Abfahrt
- Haltezeit
- Bemerkung

### Route

- ID
- Geometrie
- Distanz
- Fahrzeit
- Exportformat
- Routingparameter

---

## 7. MVP-Version

Für eine erste Version reicht:

- WebLogin
- Karte mit OSM
- Start/Ziel/Wegpunkte setzen
- Fahrzeuge anlegen
- Marschverband zusammenstellen
- Geschwindigkeit innerorts/außerorts definieren
- Zeitplan berechnen
- GPX/JSON exportieren
- Route per Link teilen

---

## 8. Spätere Ausbaustufen

### Version 2

- Benutzer- und Rollenmodell
- mehrere Organisationen
- Teilverbände
- technische Halte
- PDF-Export Marschbefehl
- Offline-Karten

### Version 3

- Live-Tracking
- Teilnehmerstatus
- Wetterintegration
- Sperrungen/Baustellen
- Lagedatenintegration
- native App-Wrapper

---

## 9. Empfehlung

Das Projekt sollte zuerst als WebApp/PWA umgesetzt werden.

Der Fokus liegt am Anfang nicht auf echter Turn-by-Turn-Navigation, sondern auf:

- sauberer Planung
- belastbarer Zeitberechnung
- exportierbarer Route
- einfacher Bedienbarkeit
- BOS-tauglicher Konvoiverwaltung

Die Navigation kann zunächst über bestehende Navigationsapps erfolgen.
