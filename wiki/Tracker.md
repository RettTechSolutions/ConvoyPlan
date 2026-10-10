# Tracker (Ortungsgeräte)

Ein Tracker ist ein festes Ortungsgerät im Fahrzeug: GNSS, IoT-SIM, Akku. Es ist
mit **einem** Fahrzeug der Organisation gekoppelt und meldet dessen Position von
selbst — die Besatzung muss nichts tun, kein Telefon, kein Link, keine App.

Gerät und Firmware entstehen im Repo
[ConvoyPlan-Tracker](https://github.com/RettTechSolutions/ConvoyPlan-Tracker);
dort stehen Plan, Protokoll und ein Simulator, mit dem sich alles hier
Beschriebene ohne Hardware ausprobieren lässt.

Gebuchte Pakete (Hosting) können Tracker begrenzen; gezählt werden nur nicht
gesperrte, und die Grenze ist weich — siehe [Lizenz und Demo-Modus](Lizenz-und-Demo-Modus#pläne-je-organisation-hosting).

## Wann ein Tracker sendet

Nur, solange sein Fahrzeug in einem **laufenden** Konvoi eingeplant ist — Status
*aktiv* oder *läuft*. In der Planung, nach dem Abschluss oder ohne Konvoi bleibt
das Gerät stumm; es fragt bei Bewegung alle fünf Minuten nach, ob sich das
geändert hat. Das entscheidet die Instanz, nicht das Gerät: Ein Tracker ist
keine Ortung rund um die Uhr, sondern Tracking für den Marsch.

Steht das Fahrzeug in zwei laufenden Konvois (Hauptkonvoi und Unterkonvoi),
erscheint es in beiden.

Positionen vom Tracker tragen die **Zeit der Messung**, nicht die des Eingangs.
Fährt das Fahrzeug durch ein Funkloch, reicht das Gerät die Punkte danach nach,
und die Linie auf der Aktionsseite bleibt eine Linie. Ein nachgereichter Punkt
setzt die aktuelle Position auf der Karte nie zurück.

Beim ersten Punkt wechselt ein Fahrzeug im Status *geplant* auf *unterwegs*, wie
beim Fahrer-Link. Statusmeldungen, Stärke und Betriebsstoff kommen weiter aus der
App oder vom Fahrer-Link — der Tracker meldet nur, wo das Fahrzeug ist.

## Tracker und Telefon am selben Fahrzeug

Sendet ein Tracker, gehört ihm die Position. Meldet daneben die Besatzung mit
App oder Fahrer-Link für dasselbe Fahrzeug, wird ihre Position verworfen, und
nur sie erfährt es: „Die Position kommt vom Fahrzeugtracker. Status und
Meldungen gehen weiter von hier." Genau das bleibt ihr: Status, Stärke,
Betriebsstoff, Quittung. Sonst sprängen zwei Punkte auf der Karte hin und her.

Fällt der Tracker aus, gilt fünf Minuten nach seinem letzten Bündel wieder das
Telefon — von selbst, niemand muss neu starten. In der Fahrzeugliste steht
**TRACKER** statt **LIVE**, solange die Position vom Gerät kommt.

Will die Führung sofort das Telefon gelten lassen (Tracker defekt, falsches
Fahrzeug gekoppelt), übersteuert sie den Tracker: **Org-Admin → GPS-Freigaben →
„Tracker übersteuern"** (Rolle *Planer*). Danach wird verworfen, was der Tracker
für dieses Fahrzeug in diesem Konvoi sendet, bis jemand „Tracker wieder nutzen"
drückt. Das nimmt die Instanz nicht von selbst zurück, auch nicht nach einem
Neustart.

## Einrichten

**Org-Admin → Tracker → „+ Neuer Tracker"** (Rolle *Admin*):

1. Name vergeben, Fahrzeug wählen, Update-Kanal lassen (*Stabil*).
2. **Anlegen.** Die Seite zeigt einen Einmal-Code (`K7Q2-M9XD`) — **nur jetzt**,
   24 Stunden gültig. Gespeichert ist er nicht.
3. Gerät per USB an den Rechner und **Per USB einrichten** klicken, dann das
   Gerät in der Liste des Browsers wählen. Die Seite schreibt die Adresse dieser
   Instanz und den Code aufs Gerät. Der Tracker meldet sich danach **selbst über
   sein Mobilfunknetz** an und tauscht den Code gegen seinen Zugang. Damit ist
   zugleich geprüft, dass er Netz hat und die Instanz von außen erreicht. Der
   Code ist danach verbraucht.

Das geht in **Chrome oder Edge am Rechner** (Web Serial). In anderen Browsern
steht stattdessen ein Hinweis, und der Code wird am Gerät eingegeben.

Schlägt das Einrichten fehl, bleibt der Code stehen, und die Seite sagt, woran
es lag: kein Netz, Code abgelaufen oder Zertifikat nicht prüfbar. Ein Tracker,
der schon für eine andere Instanz eingerichtet war, behält diese Einrichtung,
bis die neue gelungen ist.

**Eigene Zertifizierungsstelle:** Ein Tracker kennt die öffentlichen Wurzeln
von Let's Encrypt. Hat diese Instanz ein Zertifikat einer eigenen oder internen
Stelle, gehört deren Wurzelzertifikat (PEM) beim Einrichten unter *Eigene
Zertifizierungsstelle* dazu, höchstens drei. Wechselt die Stelle später, muss
jedes Gerät einmal neu per USB eingerichtet werden.

In der Liste steht danach *bereit*, mit dem letzten Lebenszeichen, Akku, Empfang
und Firmwarestand. Meldet sich ein Gerät länger als einen Tag nicht, steht dort
*nicht erreichbar* — ein Tracker meldet sich auch ohne Bewegung alle zwölf
Stunden. Hat der Akku weniger als 20 % und hängt das Gerät nicht am Bordnetz,
steht dort *Akku schwach*.

### Akku und Empfang

Akku und Empfang stehen als kleine Symbole, wie man sie vom Telefon kennt: in der
Tracker-Liste und in der **Konvoi-Ansicht direkt am Fahrzeug**, damit die Führung
einen schwachen Akku oder ein Funkloch bemerkt, bevor die Position ausbleibt. Mit
der Maus über dem Symbol stehen die genauen Werte.

- **Batterie:** Füllung nach Ladestand. Ein gelber Blitz heißt *am Bordnetz*, das
  Gerät lädt. Rot mit Zahl heißt *Akku schwach*: unter 20 % und ohne Bordnetz. Der
  Tooltip nennt, seit wann das Gerät auf Akku läuft („auf Akku seit 3 Tagen").
- **Empfangsbalken:** vier Balken nach der zuletzt gemeldeten Signalstärke (RSRP:
  ab −90 dBm vier, ab −100 drei, ab −110 zwei, ab −120 einer). Ist die letzte
  Meldung älter als zehn Minuten, sind die Balken grau — alter Empfang ist kein
  Empfang. Das ist kein Fehler: Steht das Fahrzeug länger als fünf Minuten, schläft
  der Tracker bis zur nächsten Bewegung.

Die Konvoi-Ansicht fragt die Werte einmal pro Minute ab.

Hängt ein Tracker nicht am Bordnetz, steht dort **auf Akku seit …**, ab einem
Tag hervorgehoben. Über Nacht ohne Strom ist normal, wenn die Steckdose an der
Zündung hängt. Mehrere Tage heißen meist: Stecker gezogen oder Steckdose ohne
Strom, und der Akku hält nicht ewig. Gezählt wird ab der ersten Meldung ohne
Bordnetz, der Wert heißt also „seit spätestens".

**Neu einrichten** erzeugt einen neuen Code und sperrt den bisherigen Zugang
sofort — für ein Gerät, das den Besitzer wechselt oder verloren ging.
**Bearbeiten** koppelt ein anderes Fahrzeug, wechselt den Kanal oder sperrt das
Gerät; **Löschen** entfernt es.

## Update-Kanäle

Wie bei der Instanz: *Stabil*, *Beta*, *Nightly*. Der Kanal gilt je Gerät; die
Instanz bietet dem Gerät an, was auf seinem Kanal neuer ist als sein Stand und
zu seiner Hardware passt. Eingespielt wird nur im Stand, nie während der Fahrt,
und ein Image, das nach dem Neustart die Instanz nicht erreicht, rollt sich
selbst zurück. In der Liste steht, welche Version bereitsteht und wie das letzte
Update ausging.

Die Firmware kommt aus der **Firmware-Ablage** (`https://firmware.convoyplan.de`,
gefüllt vom Tracker-Repo). Die Instanz holt stündlich das Manifest des Kanals,
lädt das Image einmal und prüft es gegen Prüfsumme und Größe; **die Geräte laden
von ihrer Instanz**, nicht aus dem Internet — ein Tracker braucht nur die
Adresse seiner Instanz zu erreichen. Mit `TRACKER_FIRMWARE_URL` zeigt eine
Instanz auf eine eigene Ablage, leer schaltet Updates ab. Ist die Ablage nicht
erreichbar, bleibt der letzte Stand gültig.

## Eigene Zertifizierungsstelle wechseln

Ein Tracker prüft das Zertifikat seiner Instanz. Let's Encrypt kennt er von Haus
aus; eine eigene oder interne Zertifizierungsstelle bekommt er beim Einrichten
per USB (Feld *Wurzelzertifikate*). Wechselt die Instanz später ihre CA, muss
dafür nicht jedes Gerät an den Rechner: die Instanz kann die Wurzeln selbst
verteilen.

Dazu legt der Betreiber eine PEM-Datei mit höchstens drei CA-Zertifikaten ab und
nennt sie in `TRACKER_WURZELN`, am besten im Volume `/certs`
(`TRACKER_WURZELN=/certs/tracker-wurzeln.pem`). Beim nächsten Kontakt bekommt jedes
Gerät das Bündel; **übernommen wird es erst, wenn eine Verbindung damit gelingt**.
Ein falsches Bündel sperrt also kein Gerät aus, es wird nur nicht übernommen.

Der Wechsel geht in drei Schritten:

1. **Alte und neue CA** in die Datei schreiben. Die Instanz liest sie ohne Neustart.
2. Warten, bis in der Tracker-Liste bei keinem Gerät mehr *Zertifikate noch nicht
   übernommen* steht. Ein Gerät meldet sich spätestens nach zwölf Stunden, mit
   Strom aus dem Fahrzeug sofort.
3. **Zertifikat der Instanz tauschen**, danach die alte CA aus der Datei nehmen.
   Bis zum Tausch lehnen die Geräte das gekürzte Bündel ab und behalten beide.

Eine Datei ohne Zertifikat heißt: keine eigenen Wurzeln mehr, etwa nach dem Umzug
auf Let's Encrypt. Ist die Datei unlesbar oder enthält sie etwas anderes als
CA-Zertifikate, verteilt die Instanz nichts und schreibt den Grund ins Log.
Ohne `TRACKER_WURZELN` behält jedes Gerät, was es beim Einrichten bekommen hat.

## Was man wissen sollte

- **Ein Fahrzeug, ein Tracker.** Ein Fahrzeug, an dem schon ein Tracker hängt,
  steht beim Koppeln nicht zur Wahl.
- **„GPS-Freigabe zurücksetzen"** (Reiter *GPS-Freigaben*) gilt auch für einen
  Tracker: die gelöschte Position kommt nicht beim nächsten Punkt zurück.
- **Jede Änderung** — Anlegen, Koppeln, Sperren, neuer Code, Löschen, und das
  Einrichten durch das Gerät — steht im Audit-Log.
- **Ortung im Dienstfahrzeug** ist bei hauptamtlichem Personal
  mitbestimmungspflichtig. Dass nur während eines laufenden Konvois gesendet
  wird und das in der Fahrzeugliste sichtbar ist, ist dafür die Grundlage.

## Für Entwickler

Die Geräte-API liegt unter `/api/geraete/` (`einloesen`, `hallo`, `positionen`,
`firmware/ergebnis`), authentifiziert mit `Authorization: Bearer cvt_…`. Das
Einrichten per USB spricht ein Zeilenprotokoll über die serielle Schnittstelle
(`frontend/src/lib/tracker/usb.ts`); der Browser sieht dabei nie ein Token. Der
Vertrag steht im Tracker-Repo unter `docs/PROTOKOLL.md`; die Regeln in
`backend/app/services/ortungsgeraet.py`.
