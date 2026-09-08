# Live-Tracking

## Übersicht

ConvoyPlan verfolgt alle Fahrzeuge eines Konvois in Echtzeit über eine
WebSocket-Verbindung. Fahrer übermitteln ihre GPS-Position und ihren Status,
Planer und Beobachter sehen beides live auf der Karte. Die Positionen werden
zusätzlich **auf die geplante Route projiziert** – daraus leitet ConvoyPlan
Wegpunkt- und Leitstellenmeldungen sowie die Verspätungsprognose ab.

<p align="center">
  <img src="https://raw.githubusercontent.com/RettTechSolutions/ConvoyPlan/main/docs/diagrams/live-tracking.svg" alt="Datenfluss: Fahrzeuge senden Position an den WebSocket-Hub, der sie live an alle Beteiligten verteilt" width="880">
</p>

Zugang zur Tracking-Ansicht gibt es auf zwei Wegen:

- **Angemeldet** über den Konvoi im Portal (Rollen Admin, Planer, Fahrer, Beobachter)
- **Ohne Login** über einen [Tracking-Link](Teilen) – als *Viewer* (nur ansehen)
  oder als *Fahrer* (darf Position und Status senden)

---

## Tracking als Fahrer starten

1. Konvoi öffnen → Reiter **Tracking** (bei einem Fahrer-Link: direkt der Block
   **„Meine Position (Fahrer)"** oben in der Ansicht)
2. Das eigene Fahrzeug aus der Liste wählen
3. **Tracking starten** – der Browser fragt nach der Standortfreigabe
4. Freigabe bestätigen

Die Position wird danach vom Browser gemeldet, sobald sie sich ändert
(`watchPosition` mit hoher Genauigkeit); zwischengespeicherte Ortungen bis zu
5 Sekunden Alter werden akzeptiert.

> **GPS erfordert HTTPS.** Ohne gesicherte Verbindung bietet der Browser keine
> Standortbestimmung an; ConvoyPlan weist darauf hin und schaltet auf den
> manuellen Modus um.

### Manueller Modus

Ohne GPS-Signal oder ohne Standortfreigabe:

1. Auf der Karte auf die aktuelle Position tippen
2. Die gemeldete Position wird manuell gesetzt und übertragen

---

## Fahrzeugstatus melden

Die Kurz-Stati liegen im Reiter **Status** unter **„Mein Status"** (ein Fahrzeug
muss vorher gewählt sein). Sie dienen der knappen Verständigung zwischen
Fahrzeugen und Konvoiführung:

| Status | Farbe | Bedeutung |
|--------|-------|-----------|
| ○ **Geplant** | grau | Fahrzeug ist noch nicht gestartet |
| ▶ **Unterwegs** | blau | Fahrzeug befindet sich auf der Route |
| ✓ **Angekommen** | grün | Fahrzeug hat das Ziel erreicht |
| ⏸ **Techn. Halt** | gelb | Halt angefordert (Panne, Pause, Nachtanken) |
| ⚠ **Ausfall/Störung** | rot | Fahrzeug fällt aus oder ist eingeschränkt |

**Techn. Halt** und **Ausfall/Störung** werden zusätzlich abgestuft, damit die
Führung ohne Rückfrage weiß, wie dringend die Lage ist:

| Status | Stufen |
|---|---|
| Techn. Halt | *Standard* · *Dringend* · *Sehr dringend* |
| Ausfall/Störung | *Totalausfall – sofort halten* · *Eingeschränkt – in Sicherheit fahren* |

Zu beiden lässt sich eine kurze Bemerkung mitgeben (max. 200 Zeichen), etwa
„Bio-Pause" oder eine Beschreibung des Defekts.

> Ältere Konvois können noch den früheren Status *Verspätet* (`delayed`)
> tragen; er wird als *Unterwegs* angezeigt. Verspätung wird nicht mehr von
> Hand gemeldet, sondern aus der Position berechnet – siehe unten.

---

## Alarm bei technischem Halt und Ausfall

Fordert ein Fahrzeug einen technischen Halt an oder meldet einen Ausfall,
erhalten **alle verbundenen Tracking-Clients** sofort einen Alarm:

- Ein Banner über der Karte mit Fahrzeug, Art, Stufe und Bemerkung
- Ein akustisches Signal und – auf Mobilgeräten – Vibration; bei einem Ausfall
  dringlicher als bei einem Halt
- **Anzeigen** springt in den Reiter **Status**, **Quittieren** (✕) blendet den
  Alarm aus

Im Reiter **Status** listet der Abschnitt **Meldungen** alle aktiven
Anforderungen; **Alle quittieren** räumt sie gesammelt ab. Quittierte Meldungen
bleiben bis zur Erledigung sichtbar.

---

## Wegpunkte und Leitstellenwechsel

ConvoyPlan projiziert die Fahrzeugpositionen auf die Routenlinie und kennt
damit den Streckenabschnitt, den der Verband gerade belegt – von der Spitze bis
zum Schlusslicht.

- 📍 **Wegpunkt erreicht** – die Spitze hat den Wegpunkt passiert
- 📡 **Leitstellenwechsel** – der Übergabepunkt zweier Zuständigkeitsbereiche
  ist erreicht; das Banner nennt die abzumeldende und die anzumeldende
  Leitstelle samt Anrufgruppe

Ein Punkt gilt als **erreicht**, sobald die Spitze ihn überfahren hat, und als
**vollständig passiert**, wenn auch das letzte Fahrzeug darüber ist. Die
Anmeldung des Verbands bei der Startleitstelle (km 0) wird nicht angekündigt –
sie erfolgt vor dem Abmarsch.

Details zur Berechnung der Übergabepunkte: [Konvoi-Planung](Konvoi-Planung).

---

## Zeitplan und Verspätungsprognose

Der Reiter **Zeitplan** vergleicht laufend die tatsächlich zurückgelegte
Strecke des vordersten Fahrzeugs mit der geplanten Fahrzeit und zeigt:

- Ein Banner mit der aktuellen Abweichung – **verspätet** (rot), **vor der
  Zeit** (blau) oder **im Plan** (grün, bei bis zu ±2 Minuten)
- Je Wegpunkt die geplante Zeit und die **Prognose**, also die um die aktuelle
  Abweichung verschobene Ankunft

Die Prognose erscheint, sobald Fahrzeuge Positionen senden; ohne Live-Daten
bleibt es beim geplanten Zeitplan. Der Reiter wird nur angezeigt, wenn für den
Konvoi überhaupt ein Zeitplan hinterlegt ist.

---

## Karte bedienen

| Bedienelement | Wirkung |
|---|---|
| 🧭 **Norden** | Dreht die Karte zurück nach Norden und hebt die Neigung auf |
| ⬆️ **Fahrtrichtung** | Richtet die Karte in Fahrtrichtung des eigenen Fahrzeugs aus (Heading-up) und folgt ihm |
| **Folgen** | Sperrt die Karte auf das eigene Fahrzeug |

Die Karte lässt sich frei drehen. Die Richtungspfeile der Fahrzeuge
kompensieren die Kartendrehung und zeigen immer die echte Fahrtrichtung. Im
kurzen Querformat auf Smartphones rücken die Bedienelemente in eine größere,
besser greifbare Anordnung.

---

## Verbindungsüberwachung

Auf schwankendem Mobilfunk bleibt eine tote WebSocket-Verbindung technisch
„offen" – weder ein Fehler noch der Verbindungsstatus verraten den Abriss.
ConvoyPlan sendet deshalb alle **3 Sekunden** einen anwendungseigenen Ping und
wertet die Verbindung als tot, wenn **7 Sekunden** lang überhaupt kein Paket
mehr eintrifft.

- Bricht die Verbindung ab, erscheint ein Banner: *Deine Position wird auf der
  Karte angezeigt, aber nicht übertragen.*
- Ist sie zurück, meldet ein Banner *Wieder online*, und die Übertragung läuft
  weiter.

---

## Tracking als Planer / Beobachter

1. Konvoi öffnen → Reiter **Tracking**
2. Alle Fahrzeuge erscheinen als **Marker** mit Statusfarbe und Richtungspfeil
3. Ein Klick auf einen Marker zeigt Fahrzeugdetails (Name, Funkrufname, Status,
   letzte Meldung)
4. Der Reiter **Fahrzeuge** listet den Verband mit Status und letzter Meldung
5. Die Ansicht aktualisiert sich fortlaufend ohne Neuladen

---

## Öffentliche Lageübersicht

Über einen [Tracking-Link](Teilen) können auch Personen ohne Login mitverfolgen.
Ein **Fahrer-Link** erlaubt zusätzlich das Senden von Position und Status – mit
demselben Statusumfang inklusive technischem Halt und Ausfall.

Die Tracking-Ansicht ist als PWA installierbar und fragt beim Start nach der
Tracking-ID.

---

## Hinweise

- Die Genauigkeit hängt vom GPS-Empfang des Endgeräts ab; bei schlechter
  Verbindung wird die letzte bekannte Position angezeigt
- Positionen werden serverseitig gespeichert und sind Teil des
  Einsatzprotokolls; der Retention-Container löscht sie nach Ablauf der Frist
  (siehe [Sicherheit und Datenschutz](Sicherheit-und-Datenschutz))
- Die Karten-Kacheln der Route lassen sich für den Offline-Betrieb vorladen

---

## Nächste Schritte

- [Teilen & Öffentliche Ansicht →](Teilen)
- [Rollen & Berechtigungen →](Rollen)
- [Konvoi-Planung →](Konvoi-Planung)
