# Marschbefehl & Export

## Marschbefehl (PDF)

Der Marschbefehl ist das offizielle Führungsdokument für den Konvoi. ConvoyPlan generiert ihn im standardisierten 7-Abschnitte-Format.

### Pflichtfelder befüllen

Öffne den Konvoi und wechsle zum Tab **Marschbefehl**. Folgende Felder stehen zur Verfügung:

| Abschnitt | Feld | Beschreibung |
|-----------|------|-------------|
| 1 | **Lage** | Operative Ausgangslage, Lagebeschreibung |
| 2 | **Auftrag** | Aufgabe und Ziel des Konvois |
| 3 | **Marschform** | Geschlossener Verband / Gruppen / Einzeln |
| 4 | **Ablaufpunkt** | Name des Startorts |
| 4 | **Ablaufzeit** | Geplante Abfahrtszeit |
| 4 | **Ablaufführer** | Verantwortliche Person |
| 5 | **Versorgung** | Kraftstoff, Verpflegung, Logistik |
| 6 | **Funkgruppe** | Primäre Funkgruppe / Netz |
| 7 | **Anlagen** | Verweis auf Beilagen und Anhänge |

### Marschform-Optionen

| Option | Bedeutung |
|--------|-----------|
| **Geschlossener Verband** | Alle Fahrzeuge fahren gemeinsam als Einheit |
| **Gruppenweise** | Fahrzeuggruppen mit Abstand |
| **Einzeln** | Fahrzeuge fahren unabhängig voneinander |

### PDF generieren

1. Klicke auf **Marschbefehl exportieren** → **Als PDF herunterladen**
2. Das PDF enthält automatisch:
   - Alle ausgefüllten Abschnitte
   - Routenkarte mit Wegpunkten
   - Zeitplan-Tabelle (Wegpunkte, Ankunft, Abfahrt)
   - Fahrzeugliste mit Positionen und Sonderfunktionen
   - Kraftstoffanalyse
   - Kanalwechsel-Punkte (falls Leitstellen konfiguriert)

---

## Roadbook (PDF)

Das Roadbook ist die Route zum Ausdrucken: oben eine Übersichtskarte mit Start (**S**), Ziel (**Z**) und den nummerierten Wegpunkten, darunter **jede Navigationsanweisung** der Route — für Beifahrer, Kradmelder oder als Rückfallebene, wenn das Navi ausfällt.

1. Route berechnen (Tab **Plan** → **Route berechnen**)
2. Tab **Export** → **🧭 Roadbook (PDF)**

Jede Zeile der Tabelle enthält:

| Spalte | Inhalt |
|---|---|
| **Nr.** | laufende Nummer der Anweisung |
| Symbol | Richtungspfeil (↑ geradeaus, → rechts, ↺ Kreisverkehr, ◉ Wegpunkt, ⚑ Ziel …) |
| **Anweisung** | Abbiegehinweis mit Straßenname und -nummer (z. B. „Rechts abbiegen auf Pragstraße (B 10)"), bei Autobahnen die Zielangabe („Richtung München") |
| **bei km** | Kilometrierung ab Start, an der das Manöver kommt |
| **dann** | Strecke bis zur nächsten Anweisung |

Wegpunkte sind farbig hervorgehoben und tragen dieselbe Nummer wie auf der Karte, dazu Typ, geplante Ankunft/Abfahrt, Haltedauer mit Zweck und die Notiz. Die Ziel-Zeile nennt die geplante Ankunft.

**Gut zu wissen:**

- Die Anweisungen entstehen bei der **Routenberechnung** und werden mit der Route gespeichert. Eine Route, die vor diesem Update berechnet wurde, hat noch keine — das Roadbook sagt das und bittet um eine Neuberechnung.
- Eine **importierte** Route (GPX/GeoJSON) hat keine Anweisungen; das Roadbook zeigt dann nur die Karte.
- Zeiten stammen aus dem Zeitplan des Konvois (Marschgeschwindigkeiten), nicht aus der Pkw-Fahrzeit des Routers.
- Den Kartenhintergrund lädt der Server von OpenStreetMap. Ist der Kachelserver nicht erreichbar, enthält die Karte nur die Route auf neutralem Grund. Andere Kachelquelle oder offline: `ROADBOOK_TILE_URL` (leer = ohne Hintergrund).
- Vor Ort gilt die Beschilderung — die Anweisungen beruhen auf OpenStreetMap-Daten.

---

## GPX-Export

Der GPX-Export enthält:
- **Wegpunkte** (Start, Ziel, alle Zwischenpunkte mit Namen und Zeiten)
- **Routengeometrie** (Fahrtweg als Track)

Verwendungszweck: Navigation auf Garmin-Geräten, Smartphone-Apps (OsmAnd, Maps.me) oder Übergabe an andere Einsatzkräfte.

1. Klicke auf **Exportieren** → **GPX herunterladen**
2. Die Datei kann direkt in Navigationsgeräte oder Apps importiert werden

---

## JSON-Export

Der vollständige JSON-Export enthält alle Konvoidaten:
- Fahrzeugliste, Marschbefehls-Felder, Wegpunkte, Geschwindigkeiten, Zeitplan
- Geeignet für Archivierung oder Import in andere Systeme

---

## Import-Funktionen

### GPX importieren

1. Klicke auf **Importieren** → **GPX-Datei auswählen**
2. Wähle, ob die importierten Punkte bestehende Wegpunkte **ersetzen** oder **ergänzen** sollen
3. GPX-Tracks werden in Wegpunkte umgewandelt und in die Routenplanung übernommen

### GeoJSON importieren

Externe Routengeometrien (z. B. aus GIS-Systemen) können als GeoJSON importiert werden. Die Geometrie wird auf der Karte dargestellt und kann als Routenbasis genutzt werden.

---

## Nächste Schritte

- [Konvoi teilen →](Teilen)
- [Rollen & Berechtigungen →](Rollen)
