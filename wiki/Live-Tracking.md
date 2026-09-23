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

## Den Link weitergeben (QR)

In jeder Tracking-Ansicht steht in der Seitenleiste **📱 Link weitergeben (QR)** —
bei einem Fahrer-Link heißt derselbe Knopf **📱 Link für Mitfahrer (QR)**.
Aufgeklappt zeigt er den QR-Code der geöffneten Adresse, zum Abscannen vom
Nachbargerät, dazu **PNG herunterladen** und **Drucken**. Niemand muss eine
achtstellige Zeichenfolge diktieren.

Was der Code bedeutet, hängt an der Rolle des Links — dass es ihn gibt, nicht:

| Rolle | Wer ihn scannt … |
|---|---|
| **Nur ansehen** (Viewer) | sieht denselben Verband live: Positionen, Status, Zeitplan. Senden kann er nichts. |
| **Fahrer** | kann zusätzlich ein Fahrzeug wählen und Position und Status senden. |

> **Der Code *ist* der Link.** Bei einem Fahrer-Link gibt er damit Schreibzugriff
> weiter — nur an die eigene Besatzung, nicht an Umstehende. Ist der Link
> passwortgeschützt, braucht der Empfänger zusätzlich das Passwort; es steckt
> **nicht** im QR-Code und auch nicht auf dem Ausdruck, sondern ist getrennt
> mitzuteilen. Der Hinweis in der Ansicht sagt beides an Ort und Stelle.

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

## Mannschaftsstärke melden

Unter den Status-Schaltflächen steht **Mannschaftsstärke melden** mit drei
Feldern — *Führer*, *Unterführer*, *Mannschaften*. Die Gesamtzahl rechnet
ConvoyPlan selbst; gemeldet wird erst auf Knopfdruck, Zwischenstände bleiben im
Fahrzeug. Geschrieben wird die Stärke in der üblichen Notation:

```
0/1/8//9
│ │ │   └─ Gesamt (gerechnet)
│ │ └───── Mannschaften
│ └─────── Unterführer
└───────── Führer
```

Die Führung sieht die Meldung neben dem Fahrzeug in der Liste, dazu die
**Verbandsstärke** als Summe über alle Fahrzeuge.

### Eine Funkmeldung nachtragen

Nicht jede Besatzung hat den Fahrer-Link offen — durchgegeben wird die Stärke
dann über Funk. In der angemeldeten Tracking-Ansicht trägt die Führung sie
nach: im Reiter **Fahrzeuge** auf das **✎** neben der Stärke des Fahrzeugs,
Zahlen eintragen, **Stärke eintragen**. Die Meldung steht sofort bei allen
offenen Ansichten.

Wer selbst in einem Fahrzeug sitzt und die Ansicht angemeldet offen hat, meldet
seine eigene Stärke im Reiter **Status** unter *Mannschaftsstärke melden* —
für das Fahrzeug, das oben unter *Meine Position* gewählt ist.

Beides braucht mindestens die Rolle **Fahrer**; ein *Beobachter* sieht die
Stärke, kann sie aber nicht setzen. Wessen Meldung es war, hält ConvoyPlan
nicht fest — eingetragen ist eingetragen.

Die Felder starten bei einer bereits gemeldeten Stärke, damit sich eine
Korrektur nicht neu tippen lässt, sonst bei null — **nie** beim Soll: eine
vorausgefüllte Planzahl wird im Einsatz bestätigt statt gezählt.

Zwei Dinge hält die Anzeige auseinander:

- **Noch nichts gemeldet** steht als `–/–/–` da und zählt nicht in die Summe;
  darunter steht, wie viele Fahrzeuge noch offen sind.
- **`0/0/0//0`** ist eine Meldung — das Fahrzeug fährt unbesetzt.

Ist im Marschbefehl eine **Sollstärke** geplant (Planung → *Im Verband* →
*Sollstärke*), steht sie klein daneben, und eine Abweichung wird hervorgehoben.
Das Soll ändert nur die Planung, nie die Meldung der Besatzung.

> Die Stärke ist eine Zahl, kein Name: ConvoyPlan speichert zu keiner Meldung,
> **wer** an Bord ist.

---

## Füllstand melden (Tank/Akku)

Unter der Stärke steht **Tankstand melden** (bei E-Fahrzeugen **Akkustand
melden**). Gemeldet wird in **Prozent** — so, wie man die Tankanzeige abliest:
die Knöpfe **Reserve** (10 %), **¼**, **½**, **¾** und **Voll** füllen das Feld,
ein genauerer Wert lässt sich als ganze Zahl von 0 bis 100 eintippen. Wie bei
der Stärke geht die Meldung erst auf **Füllstand melden** hinaus; ein
versehentlich getippter Knopf ist noch keine Meldung.

Liter bzw. Kilowattstunden und die Reichweite rechnet ConvoyPlan aus den
[Fahrzeugdaten](Fahrzeuge) (Tankinhalt bzw. Akkukapazität und Verbrauch). In
der Fahrzeugliste steht dann etwa:

```
⛽ Tank 50 % · ≈ 40 l · ≈ 320 km
🔋 Akku 50 % · ≈ 38,5 kWh · ≈ 214 km
```

Fehlen Tankinhalt oder Verbrauch, entfällt die jeweilige Umrechnung, die
Prozentangabe bleibt.

Zwei Dinge hält die Anzeige auseinander:

- **Gemeldet** — was die Besatzung unterwegs angegeben hat.
- **Laut Planung** — noch keine Meldung, aber am Fahrzeug ist ein *aktueller
  Füllstand* eingetragen, etwa `Tank 45 von 80 l (56 %) · laut Planung`. Er
  stammt aus der Planung und ist nach den ersten Kilometern überholt.

Ist beides nicht da, steht beim Fahrzeug nichts. **0 %** ist dagegen eine
Meldung und heißt „leer". Unter **¼** (25 %) wird der Füllstand gelb mit ⚠
hervorgehoben — Zeit, einen Tankstopp einzuplanen.

Nachtragen funktioniert wie bei der Stärke: In der angemeldeten
Tracking-Ansicht trägt die Führung einen über Funk durchgegebenen Füllstand im
Reiter **Fahrzeuge** über das **⛽** (bzw. **🔋**) neben der Stärke ein, und
wer selbst in einem Fahrzeug sitzt, meldet den eigenen im Reiter **Status**.
Beides braucht mindestens die Rolle **Fahrer**. Das Feld startet bei einer
bereits gemeldeten Zahl, sonst leer — nie beim eingetragenen Stand aus der
Planung.

> Die Meldung ändert den *aktuellen Füllstand* in den Fahrzeugdaten nicht; der
> bleibt die Planungsgrundlage für die Kraftstoffanalyse.

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

### Die Anzeige in der Kopfzeile

Der Punkt neben dem Konvoinamen kennt vier Zustände statt zwei — ein
Verbindungsaufbau ist kein Abriss, und Stille ist keiner:

| Anzeige | Bedeutung |
|---|---|
| **Live** (grün) | Verbindung steht, Meldungen kommen an |
| **Still** (gelb) | Verbindung steht, seit über einer Minute keine Meldung — normal bei stehendem Konvoi |
| **Verbindet…** (gelb) | Aufbau läuft oder ein Abriss wird gerade überbrückt |
| **Getrennt** (rot) | Der Aufbau scheitert seit über zehn Sekunden |

Der Kanal baut sich **unabhängig von den Stammdaten** auf: hakt der Abruf von
Konvoi, Route oder Positionen, läuft die Live-Verfolgung trotzdem an. Scheitert
er, steht die Begründung in der Kopfzeile, samt Schaltfläche *Erneut laden*.

Die öffentliche Tracking-Ansicht verbindet sich nach einem Abriss selbständig
neu — mit wachsendem Abstand zwischen den Versuchen und sofort, sobald das Netz
zurück ist oder die Seite wieder in den Vordergrund kommt. Ein widerrufener
Link führt zu einem Hinweis statt zu endlosen Versuchen; bei einem abgelaufenen
Passwortlink erscheint wieder die Passwortabfrage.

---

## Tracking als Planer / Beobachter

1. Konvoi öffnen → Reiter **Tracking**
2. Alle Fahrzeuge erscheinen als **Marker** mit Statusfarbe und Richtungspfeil
3. Ein Klick auf einen Marker zeigt Fahrzeugdetails (Name, Funkrufname, Status,
   letzte Meldung)
4. Der Reiter **Fahrzeuge** listet den Verband mit Status und letzter Meldung
5. Ab der Rolle **Fahrer** lassen sich dort die [Mannschaftsstärke](#eine-funkmeldung-nachtragen)
   und der [Füllstand](#füllstand-melden-tankakku) nachtragen, die über Funk hereinkamen
6. Die Ansicht aktualisiert sich fortlaufend ohne Neuladen

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
