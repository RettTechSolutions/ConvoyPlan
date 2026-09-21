# Fahrzeugverwaltung

## Fahrzeug anlegen

1. Navigiere zu **Fahrzeuge** in der Seitenleiste → **Neues Fahrzeug**
2. Fülle die Fahrzeugdaten aus:

### Stammdaten

| Feld | Beschreibung |
|------|-------------|
| **Name** | Bezeichnung des Fahrzeugs (z. B. „GKW 1") |
| **Funkrufname** | Taktische Kennung (z. B. „Florian Muster 48/1") |
| **Kennzeichen** | Amtliches Kennzeichen |

### Abmessungen & Gewicht

| Feld | Beschreibung |
|------|-------------|
| **Höhe** | Fahrzeughöhe in cm (relevant für Streckeneinschränkungen) |
| **Länge** | Fahrzeuglänge in cm |
| **Breite** | Fahrzeugbreite in cm |
| **Gewicht** | Gesamtgewicht in kg |

### Kraftstoffdaten

| Feld | Beschreibung |
|------|-------------|
| **Tankinhalt** | Maximales Tankvolumen in Litern |
| **Verbrauch** | Kraftstoffverbrauch in L/100 km |
| **Aktueller Füllstand** | Aktuell verfügbarer Kraftstoff in Litern |

> Die Kraftstoffdaten werden für die automatische **Kraftstoffanalyse** und die Empfehlung eines Tankstopps verwendet.

### Regelbesatzung

| Feld | Beschreibung |
|------|-------------|
| **F** | Führer der üblichen Besatzung |
| **U** | Unterführer |
| **M** | Mannschaften |

Die Regelbesatzung gehört zum Fahrzeug und wird einmal eingetragen — in der
Notation `Führer/Unterführer/Mannschaften`, also etwa `0/1/8` für eine
Gesamtstärke von 9. Wird das Fahrzeug einem Konvoi zugewiesen, übernimmt
ConvoyPlan sie dort als **Sollstärke**; für den einzelnen Marsch bleibt sie in
der Tabelle *Sollstärke* änderbar (Tab **Fahrzeuge**, unterhalb der
Marschfolge).

Bleiben die Felder leer, heißt das **nicht angegeben** — nicht „unbesetzt".
Eine später geänderte Regelbesatzung gilt für neue Zuweisungen; bereits
geplante Konvois behalten ihre Sollstärke, damit ein fertiger Marschbefehl
nicht nachträglich anders aussieht.

---

## Fahrzeug einem Konvoi zuweisen

1. Öffne den gewünschten Konvoi
2. Wechsle zum Tab **Fahrzeuge**
3. Klicke auf **Fahrzeug hinzufügen** und wähle ein Fahrzeug aus
4. Lege die **Sonderfunktion** und die **Position** in der Formation fest
5. Die **Sollstärke** steht bereits da, wenn das Fahrzeug eine Regelbesatzung hat

### Sonderfunktionen

| Funktion | Bedeutung |
|----------|-----------|
| **Spitzenführer** | Führendes Fahrzeug an der Spitze des Konvois |
| **Schließender** | Letztes Fahrzeug, sichert das Ende des Verbands |
| **Sanitäter** | Medizinisches Fahrzeug |
| **Ablaufführer** | Verantwortlicher für den Marschabschnitt |

### Formationsreihenfolge

Die Reihenfolge der Fahrzeuge im Konvoi kann per **Drag & Drop** angepasst werden. Die Positionsnummer bestimmt die Reihenfolge im PDF-Marschbefehl und in der Fahrzeugliste.

---

## Mobiler Kontakt

Pro Fahrzeugzuweisung kann eine **Mobiltelefonnummer** eingetragen werden. Diese wird im Marschbefehl ausgegeben und dient als Kontaktdaten für den Einsatz.

---

## Fahrzeuge aus anderen Organisationen

Mitglieder derselben Organisation können Fahrzeuge aus dem gemeinsamen Fahrzeugpool nutzen. Fahrzeuge sind innerhalb einer Organisation sichtbar und können von allen berechtigten Planern zugewiesen werden.

---

## Nächste Schritte

- [Live-Tracking starten →](Live-Tracking)
- [Marschbefehl exportieren →](Marschbefehl-Export)
