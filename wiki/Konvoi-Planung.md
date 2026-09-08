# Konvoi planen

## Neuen Konvoi erstellen

1. Klicke in der linken Seitenleiste auf **Konvois** → **Neuer Konvoi**
2. Fülle die Grundeinstellungen aus:

| Feld | Beschreibung |
|------|-------------|
| **Name** | Bezeichnung des Konvois (z. B. „Marsch nach Musterdorf") |
| **Organisation** | Zugehörige Organisation |
| **Startzeit** | Geplanter Abfahrtszeitpunkt (Datum + Uhrzeit) |
| **Geschwindigkeit urban** | Km/h in Ortschaften (Standard: 40 km/h) |
| **Geschwindigkeit rural** | Km/h außerorts (Standard: 65 km/h) |
| **Abstand urban / rural / Autobahn** | Fahrzeugabstand in Metern |

---

## Route festlegen

### Startpunkt und Ziel setzen
- Klicke auf die Karte, um **Startpunkt** (grün) und **Zielort** (rot) zu setzen
- Alternativ: Adresse über die **Suchleiste** eingeben und als Punkt übernehmen

Die Routenberechnung deckt standardmäßig den gesamten DACH-Raum ab (Deutschland, Österreich, Schweiz, Liechtenstein — der GraphHopper-Graph enthält das entsprechende Straßennetz). Die Karte zeigt das direkt: Alles außerhalb dieser Region ist abgedunkelt bzw. ausgegraut, die Außengrenze selbst als feine Linie gezogen — ein Ziel jenseits davon fällt so schon vor der Berechnung auf. Betreiber, die einen kleineren Kartenausschnitt (z. B. nur Deutschland) installiert haben, sehen die Maske entsprechend enger gefasst. Die Kartendarstellung folgt außerdem dem gewählten Hell-/Dunkel-Design der App, ohne dass die Karte dafür neu geladen wird.

### Wegpunkte hinzufügen
Über das Panel können folgende Wegpunkttypen hinzugefügt werden:

| Typ | Bedeutung |
|-----|-----------|
| **Waypoint** | Normaler Durchfahrtspunkt ohne Halt |
| **Stop (Halt)** | Geplanter Aufenthalt mit Haltedauer |
| **Checkpoint** | Kontrollpunkt, z. B. zur Lageüberprüfung |
| **Technischer Halt** | Fahrtechnische Pause (Kraftstoff, Inspektion) |

Für jeden Wegpunkt kann eine **Haltedauer** (Minuten) sowie eine **Notiz** erfasst werden.

### Routing-Präferenz
Wähle im Konvoi-Menü die bevorzugte Streckenführung:

| Option | Bedeutung |
|--------|-----------|
| **Schnell** | Kürzeste Fahrzeit (Autobahnen bevorzugt) |
| **Bundesstraße** | Vorrangig überörtliche Hauptstraßen |
| **Landstraße** | Bevorzugt ländliche Strecken |

---

## Automatische Zeitplanung

Sobald Start, Ziel und Wegpunkte gesetzt sind, berechnet ConvoyPlan automatisch:

- **Ankunftszeit** an jedem Wegpunkt
- **Abfahrtszeit** (Ankunft + Haltedauer)
- **Gesamtfahrtdauer** und **Gesamtstrecke**

Die Fahrzeit bis zu jedem Wegpunkt wird **streckenproportional** zur Gesamtroute berechnet, nicht gleichmäßig auf alle Wegpunkte verteilt: Ein Wegpunkt bei 40 % der Streckenlänge erhält auch rechnerisch 40 % der Gesamtfahrzeit als ETA. Haltezeiten an vorherigen Wegpunkten verschieben alle nachfolgenden Zeiten entsprechend nach hinten.

Der **Zeitplan**-Tab zeigt zusätzlich zu den Wegpunkten eine **Abmarsch**-Zeile (Startzeit des Konvois) und eine **Ziel**-Zeile mit der berechneten Ankunftszeit am Zielort (Startzeit + Gesamtfahrzeit + alle Haltezeiten).

---

## Kraftstoffanalyse

ConvoyPlan analysiert automatisch, ob der Konvoi einen Tankstopp benötigt:

1. Basierend auf den Fahrzeugdaten (Tankinhalt, Verbrauch, aktueller Füllstand) wird die **minimale Reichweite** des Konvois ermittelt
2. Reicht die Reichweite nicht für die gesamte Strecke, wird ein **empfohlener Tankstopp** auf der Route vorgeschlagen
3. Über die **Tankstellen-Suche** werden nahe gelegene Tankstellen (aus OpenStreetMap) mit Name, Betreiber und Öffnungszeiten angezeigt

---

## Technische Halte

Ab **3 Stunden** Marschdauer simuliert ConvoyPlan die Lenkzeit des Verbands und empfiehlt daraus Halte in Anlehnung an die Lenk- und Ruhezeiten der VO (EG) 561/2006. Dabei werden drei Haltearten unterschieden:

| Halteart | Auslöser | Haltedauer |
|---|---|---|
| 🔧 **Technischer Halt (WOLKE)** | Alle **2 Stunden** Lenkzeit | **15 Minuten** pro angefangener 3 Fahrzeuge |
| ☕ **Lenkpause** | Spätestens nach **4,5 Stunden** Lenkzeit am Stück | **45 Minuten** (länger, falls der fahrzeuganzahlbasierte Halt ohnehin mehr Zeit braucht) |
| 🛏 **Tagesruhezeit** | Spätestens nach **9 Stunden** Tageslenkzeit | **11 Stunden** |

Dabei gilt:

- Ein technischer Halt, der wegen der Verbandsgröße bereits ≥ 45 Minuten dauert, erfüllt die fällige Lenkpause mit — er wird in der Übersicht dann zusätzlich mit **„deckt Lenkpause ab"** markiert, ein separater Stopp entfällt.
- Fallen zwei Halttermine dicht hintereinander (innerhalb von 30 Minuten), werden sie zu einem einzigen Halt der höherwertigen Art zusammengefasst (Tagesruhezeit vor Lenkpause vor technischem Halt), statt zwei Stopps kurz nacheinander vorzuschlagen.
- Kurz vor dem Ziel entfällt der letzte Halt, wenn er ohnehin am Ziel selbst fällig wäre. Wie groß dieses Zeitfenster ist, richtet sich nach der Gesamtlenkzeit (10 % davon, mindestens 30 Minuten, höchstens 2 Stunden) — auf einer Tagesfahrt wird so nur der allerletzte Halt übersprungen, nie eine ganze Gruppe.

Jeder empfohlene Halt zeigt in der Planungsansicht seine Art, die Haltedauer und die kumulierte Lenkzeit bis zu diesem Punkt an. Die empfohlenen Positionen werden auf der Route interpoliert und können per Klick als Wegpunkte übernommen werden.

---

## Leitstellen & Kanalwechsel

Führt die Route durch Bereiche verschiedener Leitstellen, werden automatisch **Kanalwechsel-Punkte** berechnet:

- Position (Koordinaten + Streckenkilometer)
- Name der Leitstelle, Anrufgruppe
- Zu aktivierende Zusatzkanäle

Diese Angaben erscheinen im PDF-Marschbefehl und in der Routenansicht.

---

## Unterkonvois

Konvois können hierarchisch strukturiert werden. Ein **Übergeordneter Konvoi** kann mehrere **Unterkonvois** enthalten, die jeweils eigenständige Routen und Fahrzeuglisten haben.

---

## Nächste Schritte

- [Fahrzeuge hinzufügen →](Fahrzeuge)
- [Marschbefehl exportieren →](Marschbefehl-Export)
