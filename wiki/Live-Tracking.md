# Live-Tracking

## Übersicht

ConvoyPlan ermöglicht die Echtzeit-Verfolgung aller Fahrzeuge eines Konvois über eine WebSocket-Verbindung. Fahrer übermitteln ihre GPS-Position, Planer und Beobachter sehen die aktuellen Positionen live auf der Karte.

<p align="center">
  <img src="https://raw.githubusercontent.com/RettTechSolutions/ConvoyPlan/main/docs/diagrams/live-tracking.svg" alt="Datenfluss: Fahrzeuge senden Position an den WebSocket-Hub, der sie live an alle Beteiligten verteilt" width="880">
</p>

---

## Tracking als Fahrer starten

1. Melde dich mit deinem Fahrer-Konto an
2. Wähle den aktiven Konvoi und dein zugewiesenes Fahrzeug aus
3. Klicke auf **Tracking starten** – der Browser fragt nach der Standortfreigabe
4. Bestätige die Standortfreigabe

Die GPS-Position wird nun automatisch alle **5 Sekunden** an den Server übermittelt.

> **Wichtig:** GPS-Tracking erfordert eine HTTPS-Verbindung und einen modernen Browser mit aktivierter Standortfreigabe.

### Manueller Modus

Falls kein GPS-Signal verfügbar ist (z. B. in Gebäuden oder bei GPS-Ausfall):

1. Deaktiviere das automatische GPS
2. Tippe auf der Karte auf deine aktuelle Position
3. Die gemeldete Position wird manuell gesetzt

---

## Fahrzeugstatus melden

Fahrer können ihren aktuellen Status melden:

| Status | Bedeutung |
|--------|-----------|
| **Geplant** | Fahrzeug ist noch nicht gestartet |
| **Unterwegs** | Fahrzeug befindet sich auf der Route |
| **Angekommen** | Fahrzeug hat das Ziel erreicht |
| **Verzögert** | Fahrzeug weicht vom Zeitplan ab |

Der Status ist für alle berechtigten Nutzer der Organisation in Echtzeit sichtbar.

---

## Tracking als Planer / Beobachter

1. Öffne den aktiven Konvoi
2. Auf der Karte erscheinen alle Fahrzeuge mit ihrer aktuellen Position als **Marker**
3. Klicke auf einen Marker, um Fahrzeugdetails (Name, Funkrufname, Status, letzte Meldung) anzuzeigen
4. Die Karte aktualisiert sich automatisch ohne manuelles Neu-Laden

---

## Öffentliche Lageübersicht

Über einen **Freigabelink** (siehe [Teilen & Öffentliche Ansicht](Teilen)) können auch Personen ohne Login die Fahrzeugpositionen und den Routenverlauf beobachten.

---

## Hinweise

- Tracking ist nur während eines **aktiven Einsatzes** sinnvoll; die Genauigkeit hängt vom GPS-Empfang des Endgeräts ab
- Bei schlechter Verbindung wird die letzte bekannte Position angezeigt
- Alle Positionen werden serverseitig gespeichert und sind Teil des Einsatzprotokolls

---

## Nächste Schritte

- [Rollen & Berechtigungen →](Rollen)
- [Teilen & Öffentliche Ansicht →](Teilen)
