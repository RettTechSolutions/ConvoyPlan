# Rollen & Berechtigungen

## Rollenübersicht

ConvoyPlan verwendet ein rollenbasiertes Berechtigungssystem auf Organisationsebene. Jedes Mitglied einer Organisation erhält eine Rolle, die seine Zugriffsrechte bestimmt.

| Rolle | Bezeichnung | Beschreibung |
|-------|-------------|-------------|
| **beobachter** | Beobachter | Lesezugriff auf Konvois, Fahrzeuge und Positionen |
| **fahrer** | Fahrer | GPS-Position übermitteln, eigenen Fahrzeugstatus melden |
| **planer** | Planer | Konvois und Routen vollständig bearbeiten |
| **admin** | Administrator | Alle Planer-Rechte + Mitglieder verwalten + Konvois löschen |

---

## Berechtigungen im Detail

### Beobachter (`beobachter`)

- Konvois der Organisation **anzeigen**
- Fahrzeuglisten und Wegpunkte **einsehen**
- Live-Tracking auf der Karte **beobachten**
- **Keine** Bearbeitungsrechte

### Fahrer (`fahrer`)

Alle Rechte des Beobachters, zusätzlich:

- Eigene **GPS-Position übermitteln**
- **Fahrzeugstatus** aktualisieren (geplant / unterwegs / angekommen / verzögert)
- Zugewiesenes Fahrzeug im Konvoi **steuern**

### Planer (`planer`)

Alle Rechte des Fahrers, zusätzlich:

- **Konvois erstellen** und bearbeiten
- **Wegpunkte** hinzufügen, verschieben, löschen
- **Fahrzeuge** anlegen, bearbeiten und dem Konvoi zuweisen
- **Marschbefehl-Felder** bearbeiten
- **Exporte** (PDF, GPX, JSON) erstellen
- **Freigabelinks** generieren
- Lage-Ebenen und Kartendaten verwalten

### Administrator (`admin`)

Alle Rechte des Planers, zusätzlich:

- **Konvois löschen**
- **Organisationsmitglieder** einladen, Rollen ändern, Mitglieder entfernen
- Organisations-Einstellungen bearbeiten

---

## Rollenänderung

Nur Administratoren können Rollen innerhalb einer Organisation ändern:

1. Gehe zu **Organisationseinstellungen** → **Mitglieder**
2. Klicke beim gewünschten Mitglied auf **Rolle bearbeiten**
3. Wähle die neue Rolle aus und bestätige

---

## Öffentliche Nutzer (ohne Login)

Über einen **Freigabelink** können Personen ohne Konto die öffentliche Routenansicht eines Konvois aufrufen. Sie haben ausschließlich Lesezugriff auf die freigegebenen Daten (Route, Wegpunkte, Zeitplan) – keine Login-Pflicht, keine Bearbeitungsmöglichkeit.

---

## Hinweise

- Ein Nutzer kann Mitglied in mehreren Organisationen mit unterschiedlichen Rollen sein
- Berechtigungen gelten immer **organisationsbezogen** – ein Planer in Organisation A hat keine Rechte in Organisation B
- Fahrzeuge sind innerhalb einer Organisation für alle berechtigten Mitglieder sichtbar
