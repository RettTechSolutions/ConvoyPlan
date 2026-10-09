# Fahrzeugtracker — die Position kommt vom Fahrzeug, nicht vom Telefon

Anlass: Fahrzeuge mit fest verbautem Ortungsgerät (GPS-Tracker am Bordnetz).
Die Besatzung soll sich in der App weiter **zum Fahrzeug anmelden** können —
Status, Stärke, Betriebsstoff, Alarm quittieren —, aber **keine Position mehr
senden**. Die Position liefert das Gerät, und der **Server** setzt das durch,
nicht die App.

Dieses Dokument hält fest, was dafür fehlt, was man dabei falsch machen kann
und in welcher Reihenfolge gebaut wird.

---

## 1. Ausgangslage

Positionen kommen heute über genau drei Schreibstellen herein, alle von
Menschen mit einem Telefon oder Browser:

| Schreibstelle | Wer |
|---|---|
| `api/routes/track.py` — `_ingest_driver_position` (WebSocket `/api/ws/track/{slug}`) | Fahrer-Link, App und Web |
| `api/routes/tracking.py` — `POST /convoys/{id}/positions` | angemeldete Ansicht, REST |
| `api/routes/tracking.py` — WebSocket `/ws/tracking/{convoy_id}` | angemeldete Ansicht, live |

Alle drei schreiben `VehiclePosition` (eine Zeile je Konvoi und Fahrzeug,
Upsert) und rufen `positionsverlauf.aufzeichnen()`. `tests/test_positionsverlauf.py`
hält per AST fest, dass keine Schreibstelle das vergisst.

Ein Ortungsgerät kennt ConvoyPlan **nicht**: kein Modell, kein Endpunkt, keine
Zuordnung zu einem Fahrzeug. Das ist der größere Teil dieses Plans; die Sperre
für Telefone ist der kleinere.

`services/belegung.py` löst schon ein verwandtes Problem — zwei Geräte auf
einem Fahrzeug, die Karte springt — und zwar **am Server, für alle Kanäle
zugleich**. Daran knüpft dieser Plan an, statt eine zweite Logik daneben zu
stellen.

## 2. Zwei Rechte statt einem

Heute heißt „ein Gerät belegt ein Fahrzeug": es darf **alles** für dieses
Fahrzeug senden. Mit einem Tracker zerfällt das in zwei Rechte:

| Recht | Wer, ohne Tracker | Wer, mit Tracker |
|---|---|---|
| **Melden** — Status, Stärke, Betriebsstoff, Alarm quittieren | das belegende Telefon | das belegende Telefon (unverändert) |
| **Position** | das belegende Telefon | **nur der Tracker** |

Ein Telefon belegt das Fahrzeug also weiter wie bisher (Frame `belegen`,
Ablauf nach fünf Minuten, „GPS-Freigabe zurücksetzen" durch die Führung). Nur
seine **Positionsframes** werden verworfen, solange das Fahrzeug einen aktiven
Tracker hat.

**Verworfen heißt: mit Antwort.** Der Absender bekommt
`{"result": "rejected", "reason": "position-vom-tracker"}` (Muster `_rejected`
in `track.py`), REST eine `409` mit demselben Grund. Die App schaltet daraufhin
das Senden ab und zeigt „Position kommt vom Fahrzeugtracker" — statt weiter
GPS zu verbrauchen und Akku zu leeren, und statt dass sich jemand wundert,
warum sein Punkt nicht wandert. Stilles Verwerfen wäre hier falsch.

## 3. Die Sperre gehört dem Server

Wie bei Belegung und Verzögerung: Die Entscheidung fällt **im Backend**. Ein
Schalter in der App wäre einer, den eine alte App aus dem Store nicht kennt —
und genau die sendet dann weiter, und die Karte springt zwischen Tracker und
Telefon.

- **Eine** Funktion entscheidet, ob eine Position angenommen wird:
  `services/positionsquelle.py: annehmen(db, convoy_id, vehicle_id, quelle) -> bool`
  mit `quelle ∈ {"telefon", "tracker"}`.
- Aufgerufen von **allen drei** Telefon-Schreibstellen und vom neuen
  Tracker-Endpunkt, **vor** dem Upsert in `VehiclePosition` und vor
  `positionsverlauf.aufzeichnen()`.
- Ein AST-Test wie in `test_positionsverlauf.py`: jede Funktion, die
  `VehiclePosition` schreibt, ruft auch `positionsquelle.annehmen`. Die fünfte
  Schreibstelle vergisst sonst jemand.
- Die Entscheidung selbst ist rein (ohne Datenbank und Uhr von außen) und
  bekommt die Tests, die zählen (Abschnitt 10).

**Clients ohne Gerätekennung** (`?client=` fehlt, App-Fassungen aus dem
Store): Ihre Positionsframes werden trotzdem verworfen — das ist der Punkt.
Den Grund erfahren sie nicht, weil neue Nachrichtentypen nur an Verbindungen
mit Kennung gehen (`broadcast_neu`, siehe CLAUDE.md „Fahrzeugbelegung"); für
sie ist es stilles Verwerfen. Bei der Belegung wurde bewusst anders entschieden
(alte Clients gehen durch), weil dort sonst ein Einsatz stehen bleibt; hier
bleibt nichts stehen, die Position kommt ja vom Gerät.

Das Protokoll gibt es zweimal — `frontend/src/lib/tracking/belegung.ts` und in
Convoyplan-Companion `packages/track-api/src/belegung.ts`. Den neuen Grund und
`position_quelle` (Abschnitt 9) ziehen beide mit.

## 4. Datenmodell

```
vehicle_trackers
  id, organization_id
  vehicle_id        (unique — ein Fahrzeug, höchstens ein Tracker)
  name              („Teltonika FMC130 KdoW")
  protokoll         ('osmand'  — zunächst nur das)
  geraete_kennung   (IMEI bzw. OsmAnd-id; unique je Organisation)
  token_hash        (SHA-256, wie fetch_token_hash der Aktionsseite)
  enabled
  letzte_meldung_at (für Anzeige und Ausfallerkennung)
  created_by_id, created_at
```

- **Ein Tracker gehört zum Fahrzeug, nicht zum Konvoi.** Fahrzeuge sind
  Stammdaten der Organisation; ein Konvoi ist ein Einsatz. Das Gerät ist fest
  im Fahrzeug, also hängt es am Fahrzeug.
- Kein Klartext-Token in der Datenbank. Angezeigt wird es nur beim Anlegen und
  Erneuern — wie beim Abruf-Token der Aktionsseite.
- Migration `0057` (oder die nächste freie Nummer).

## 5. Wohin eine Tracker-Position gehört

`VehiclePosition` ist je **(Konvoi, Fahrzeug)**. Das Gerät meldet aber nur
„Fahrzeug X". Der Server muss also den Konvoi finden:

1. Alle `ConvoyVehicle` mit `vehicle_id = X` in Konvois der Organisation, die
   **im Einsatz** sind (Abschnitt 6).
2. **Keiner** → Position verwerfen (Abschnitt 6, Datenschutz).
3. **Einer** → dorthin schreiben, wie eine Telefonposition.
4. **Mehrere** (Fahrzeug steckt in Verband *und* Unterkonvoi über
   `parent_convoy_id`) → in alle schreiben. Es ist dasselbe Fahrzeug am selben
   Ort; jede Ansicht soll es sehen. Eine Auswahl „der richtige Konvoi" gibt es
   hier nicht.

Danach dieselbe Kette wie bei einer Telefonposition: Upsert,
`positionsverlauf.aufzeichnen()`, `tracking_manager.broadcast(...)`.
**Nicht** übernommen wird der Automatismus `planned → en_route` auf der ersten
Bewegung: Mit der engen Regel aus Abschnitt 6 nimmt der Server von einem
geplanten Fahrzeug gar keine Trackerposition an — der Tracker kann den Status,
der ihn freischaltet, nicht selbst setzen. Sonst schaltete jede Fahrt zur
Tankstelle das Fahrzeug in den Einsatz.

**Messzeitpunkt:** Anders als die Telefonpfade (Serverzeit, siehe Plan
Aktionsseite, Abschnitt 2) liefern Tracker einen Zeitstempel, und sie puffern
im Funkloch zuverlässig. Den Zeitstempel übernehmen, mit Plausibilitätsgrenze:
nicht in der Zukunft (Toleranz 2 min), nicht älter als 12 h. Ältere gepufferte
Punkte gehen nur in den Verlauf, nicht in `VehiclePosition` — sonst springt der
Live-Punkt beim Nachsenden rückwärts.

## 6. Datenschutz: Ein Tracker sendet immer

Das Telefon sendet, solange jemand den Fahrer-Link offen hat. Ein fest
verbautes Gerät sendet **immer** — aus der Fahrzeughalle, nachts, im Urlaub
des Fahrers, der das Fahrzeug privat nutzen darf. Ohne Regel entsteht genau das
Bewegungsprofil, das `positionsverlauf.py` für die Aktionsseite bewusst
vermeidet.

Deshalb: **Angenommen wird nur, solange das Fahrzeug im Einsatz ist.** Alles
andere wird verworfen, ohne es zu speichern — auch nicht „kurz zum Debuggen".
Nur `letzte_meldung_at` wird gesetzt, damit die Verwaltung sieht, dass das
Gerät lebt.

„Im Einsatz" heißt (Vorschlag, zu entscheiden):

- das Fahrzeug steckt in einem Konvoi der Organisation, **und**
- dessen `ConvoyVehicle.vehicle_status` ist nicht `planned` und nicht
  `arrived` — **oder** die Führung hat das Fahrzeug ausdrücklich „zum Tracken
  freigegeben".

Die zweite Bedingung ist die engere und die bessere Wahl: Ein Fahrzeug, das nur
*eingeplant* ist, wird nicht verfolgt. Der Übergang `planned → en_route`
braucht dann aber einen Auslöser, der nicht die Tracker-Position selbst ist —
entweder das Telefon der Besatzung (Status „unterwegs") oder die Führung. Das
ist ein Ablauf, den die Anwender kennen müssen; er gehört in `wiki/`.

## 7. Endpunkt für Geräte

Zuerst genau **ein** Protokoll: **OsmAnd über HTTP** (wie Traccar es auf Port
5055 spricht). Es ist das, was die meisten Geräte und Apps können, und es ist
ein einfacher `GET`/`POST` mit Query-Parametern — kein eigener TCP-Dienst,
keine neue Firewall-Regel, läuft hinter dem vorhandenen Caddy.

```
POST /api/geraete/osmand?id=<geraete_kennung>&lat=…&lon=…&timestamp=…&speed=…&bearing=…
Authorization: Bearer <token>        (oder ?token=…, viele Geräte können keine Header)
```

- **Unbekannt, abgeschaltet, falsches Token → dieselbe 401.** Keine
  Unterscheidung, die verrät, welche Kennungen es gibt.
- In `_EXEMPT_PREFIXES` des Lizenzwächters, wie `/api/track/` — ein Gerät kann
  keine Lizenz eingeben, und eine abgelaufene Lizenz darf nicht die Ortung
  eines laufenden Einsatzes abschneiden. (Zu prüfen: ob das zur
  Lizenzlogik passt oder Tracker ein lizenzpflichtiges Merkmal sind.)
- Rate-Limit je Gerät (ein Punkt pro Sekunde ist reichlich), Antwort immer
  sofort `200` an das Gerät, sobald angenommen *oder* datenschutzbedingt
  verworfen — sonst puffert das Gerät endlos und sendet beim nächsten Einsatz
  die ganze Nacht nach.
- Binäre Protokolle (Teltonika, Queclink) **nicht** in diesem Plan. Wer sie
  braucht, schaltet einen Traccar davor und lässt ihn per Forwarding auf
  diesen Endpunkt weiterleiten. Das hält ConvoyPlan frei von
  Geräteprotokollen.

## 8. Ausfall des Trackers

Fällt das Gerät aus (Sicherung, Antenne, Tunnel über Stunden), hat das
Fahrzeug **keine** Position, und das Telefon darf nicht.

**Kein automatisches Zurückfallen auf das Telefon.** Ein „nach 10 min ohne
Trackermeldung nimmt der Server wieder Telefonpositionen" bringt das Springen
zurück, sobald das Gerät wieder meldet — genau dann, wenn der Konvoi durch ein
Funkloch fährt, abwechselnd. Stattdessen:

- Die Führung sieht „Tracker meldet seit 25 min nicht" am Fahrzeug
  (`letzte_meldung_at`, Schwelle Vorschlag 15 min).
- Ein Knopf **„Tracker übersteuern"** für die Führung, analog zu
  „GPS-Freigabe zurücksetzen": Für diesen Einsatz nimmt der Server wieder
  Telefonpositionen an, der Tracker wird ignoriert. Rückgängig mit demselben
  Knopf. Audit-Eintrag in beide Richtungen.
- Übersteuert wird je (Konvoi, Fahrzeug) und endet mit dem Einsatz, nicht am
  Gerät dauerhaft.

## 9. Oberfläche

**Org-Admin → Fahrzeuge → Tracker:** anlegen (Name, Kennung), Token anzeigen
(einmalig), erneuern, abschalten, letzte Meldung. Eine Kurzanleitung für
OsmAnd/Traccar-Client mit der fertigen Adresse zum Kopieren.

**Planungsansicht:** Fahrzeuge mit Tracker tragen ein Symbol; der Punkt auf der
Karte zeigt die Quelle („vom Fahrzeugtracker, vor 40 s"). Ausfall und
Übersteuern wie in Abschnitt 8.

**App (Begleit-App und Fahrer-Link im Browser):** Beim Belegen eines Fahrzeugs
mit Tracker kommt das schon in der Antwort mit (`position_quelle: "tracker"`),
die App startet das GPS dann gar nicht erst. Die eigene Position zeigt sie
lokal weiter an (Navigation), klar getrennt von „so sieht die Führung euch".

**EventTracker / Aktionsseite:** nichts zu tun. Der Verlauf kommt über
`positionsverlauf.aufzeichnen()` wie bisher; mit einem Tracker im
Spitzenfahrzeug wird er nur gleichmäßiger.

## 10. Tests, die zählen

- **Rein, ohne Datenbank** (`positionsquelle.entscheiden(...)`):
  - Fahrzeug ohne Tracker: Telefon angenommen.
  - Fahrzeug mit aktivem Tracker: Telefon verworfen, Tracker angenommen.
  - Tracker abgeschaltet: Telefon angenommen.
  - Übersteuert: Telefon angenommen, Tracker verworfen.
  - Fahrzeug nicht im Einsatz: Tracker verworfen (Datenschutz).
- **Schreibstellen** (AST): Jede Funktion, die `VehiclePosition` schreibt, ruft
  `positionsquelle.annehmen`.
- **Ende zu Ende** je Telefon-Kanal (Fahrer-Link-WS, REST, Tracking-WS): Frame
  verworfen mit `position-vom-tracker`, keine Zeile geändert, kein Verlaufspunkt,
  kein Broadcast. **Status-, Stärke- und Betriebsstoff-Frames desselben Geräts
  gehen durch.** Das ist der eigentliche Kern der Anforderung und darf nicht
  nur nebenbei mitgetestet werden.
- **Tracker-Endpunkt:** falsches Token = unbekannte Kennung = abgeschaltet
  (dieselbe 401); Zeitstempel in der Zukunft und älter als 12 h abgewiesen;
  gepufferter Punkt landet im Verlauf, nicht im Live-Punkt; Fahrzeug in
  Verband und Unterkonvoi bekommt beide Zeilen.
- **Datenschutz:** Tracker meldet für ein Fahrzeug ohne Einsatz → keine Zeile
  in `vehicle_positions` und `vehicle_position_trail`, nur
  `letzte_meldung_at`.

## 11. Reihenfolge

1. Modell, Migration, Verwaltung im Org-Admin (ohne Wirkung auf Positionen).
2. `positionsquelle.py` mit den reinen Tests; Einbau in die drei
   Telefon-Schreibstellen; AST-Test. Ab hier gilt die Sperre — aber es gibt
   noch keinen Tracker, der sendet, also nur hinter einem Schalter
   `FAHRZEUGTRACKER_ENABLED` (Standard aus).
3. OsmAnd-Endpunkt, Zuordnung zum Konvoi, Datenschutzregel.
4. Ausfallanzeige und „Tracker übersteuern".
5. App: `position_quelle` beim Belegen auswerten, Hinweis statt GPS.
6. `wiki/Fahrzeugtracker.md` (Einrichtung mit OsmAnd/Traccar, Ablauf „im
   Einsatz", Übersteuern), Verweis aus `wiki/Live-Tracking.md` („Ein
   Fahrzeug, ein Gerät"), Abschnitt in CLAUDE.md, CHANGELOG, Schalter
   standardmäßig an.

Schritt 2 vor 3, weil die Sperre allein harmlos ist (ohne Tracker greift sie
nie) und sich so getrennt prüfen lässt; Schritt 5 kann parallel laufen, die App
muss den neuen Grund nur anzeigen.

## 12. Offen

- **„Im Einsatz"** — enge Variante (Status ≠ geplant/angekommen) oder weite
  (Fahrzeug steckt in irgendeinem Konvoi)? Empfehlung: eng (Abschnitt 6).
- **Lizenz:** Tracker-Endpunkt lizenzfrei wie `/api/track/` oder Merkmal eines
  Plans?
- **Mehrere Organisationen, ein Fahrzeug** (Leihfahrzeug, überörtliche Hilfe):
  heute gehört ein Fahrzeug genau einer Organisation. Bleibt so; ein
  Leihfahrzeug bekommt dort einen eigenen Tracker-Eintrag mit eigenem Token.
- **Akku statt Bordnetz** (magnetischer Tracker für Mietfahrzeuge): sendet
  seltener (alle 2–10 min). Die Ausdünnung im Verlauf verträgt das; die
  Stehen-Erkennung der Aktionsseite (20 min im 300-m-Radius) auch, solange
  das Intervall unter 20 min bleibt. In der Anleitung festhalten.
