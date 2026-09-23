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

## Ein Fahrzeug, ein Gerät

Wer ein Fahrzeug wählt — in der Begleit-App, über den Fahrer-Link im Browser
oder in der angemeldeten Tracking-Ansicht —, **belegt** es. Auf allen anderen
Geräten steht es danach in der Fahrzeugwahl mit dem Zusatz **„belegt"** und lässt
sich nicht mehr wählen. So senden nie zwei Geräte für dasselbe Fahrzeug, und die
Karte springt nicht zwischen zwei Standorten.

Frei wird ein Fahrzeug,

- sobald das Gerät ein anderes Fahrzeug oder keins mehr wählt, die Seite schließt
  oder den Konvoi verlässt,
- nach **fünf Minuten**, in denen von diesem Gerät nichts mehr kam — etwa nach
  einem leeren Akku. Ein kurzes Funkloch gibt es **nicht** frei,
- sofort, wenn die Führung für das Fahrzeug **„GPS-Freigabe zurücksetzen"** wählt.

War ein anderes Gerät schneller, nimmt die Ansicht die Wahl zurück und sagt es:
*„Dieses Fahrzeug sendet bereits von einem anderen Gerät."* Dann ein anderes
Fahrzeug wählen oder die Besatzung fragen, wer schon sendet.

> Ältere Fassungen der Begleit-App kennen die Belegung noch nicht. Sie werden
> nicht abgewiesen, und was sie senden, belegt das Fahrzeug für alle anderen —
> sie selbst sehen aber nicht, welche Fahrzeuge schon vergeben sind.

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

## Betriebsstofflage

Die Besatzung meldet über die **Companion-App** (Reiter *Melden*), wie es um
den Kraftstoff steht: **Füllstand** in Prozent, dazu auf Wunsch **Verbrauch**
(l/100 km) und **Tankvolumen** (l). In der Fahrzeugliste steht dann neben der
Stärke ein **⛽** mit dem Füllstand; der Tooltip nennt Liter im Tank, Verbrauch
und die **Reichweite**. Ab 25 % wird die Anzeige gelb.

Lässt die Meldung Tank oder Verbrauch offen, rechnet die Reichweite mit den
**Stammdaten** des Fahrzeugs und sagt das dazu. Umgekehrt ändert eine Meldung
die Stammdaten nicht: Die Planung der Tankstopps rechnet weiter mit dem, was am
Fahrzeug eingetragen ist. Bei E-Fahrzeugen steht nur der gemeldete Füllstand da —
Prozent gegen Liter gerechnet ergäbe eine erfundene Reichweite.

Ohne Meldung steht nichts da. Eine neue Meldung ersetzt die vorige ganz; ein
leerer Tank (0 %) ist eine Meldung und keine Lücke.

### Eine Funkmeldung nachtragen

Meldet eine Besatzung ihren Füllstand über Funk, trägt die Konvoiführung ihn
nach: im Reiter **Fahrzeuge** auf das **✎** neben dem Fahrzeug — dasselbe Feld,
in dem auch die Stärke nachgetragen wird. Tank und Verbrauch stehen aus der
letzten Meldung oder aus den Stammdaten schon drin; meist genügt ein Griff auf
**¼**, **½**, **¾** oder **Voll** und **Betriebsstoff eintragen**. Die Meldung
steht sofort bei allen Beteiligten, auch in der Companion-App.

Wie bei der Stärke braucht es dafür mindestens die Rolle **Fahrer**; ein
Beobachter sieht die Lage, kann sie aber nicht setzen.

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
5. Ab der Rolle **Fahrer** lässt sich dort die [Mannschaftsstärke](#eine-funkmeldung-nachtragen)
   nachtragen, die über Funk hereinkam
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
