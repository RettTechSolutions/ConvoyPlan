# Öffentliche Aktionsseite — Konvois verzögert zeigen

Anlass: Eine Hilfsorganisation will ihre Weihnachts-Hilfskonvois (mehrere
Marschverbände, mehrere Zielländer, Abfahrt nach Weihnachten) öffentlich
verfolgbar machen — eine Seite, die man teilen, in die Presse geben und bei
Veranstaltungen auf einen Bildschirm legen kann. Positionen nur **verzögert**
(1–2 Stunden), Gestaltung festlich.

Dieses Dokument hält fest, was dafür fehlt, was man dabei falsch machen kann und
in welcher Reihenfolge gebaut wird.

---

## 1. Warum der vorhandene Tracking-Link nicht reicht

Den Share-Link (`/track/{slug}`, Scope `track`) gibt es schon. Ihn öffentlich zu
streuen wäre trotzdem falsch, aus drei Gründen:

| | Share-Link heute | Aktionsseite |
|---|---|---|
| Zeit | live, über WebSocket | verzögert, nur Abruf |
| Inhalt | Fahrzeugnamen, Rufnamen, Stärke, Betriebsstoff, Alarme, Status | ein Punkt je Konvoi, gefahrene Strecke, Fortschritt |
| Umfang | ein Konvoi | mehrere Konvois auf einer Karte |

`_build_payload` in `api/routes/track.py` ist für Leute gebaut, die zum Einsatz
gehören. Jedes Feld, das dort künftig dazukommt, landete bei einem dritten Scope
`public` automatisch in der Öffentlichkeit. Die Aktionsseite bekommt deshalb
**einen eigenen Endpunkt mit eigenem Schema als Positivliste** — dasselbe Muster
wie `PUBLIC_OPERATIONS` in `public_meta.py`.

## 2. Was fehlt: ein Positionsverlauf

`vehicle_positions` hält **nur die letzte Position** je Fahrzeug (Upsert) und
wird nach `retention_positions_hours` (24 h) geräumt. „Wo war der Konvoi vor
zwei Stunden" lässt sich daraus nicht beantworten. Nötig ist eine neue Tabelle:

```
vehicle_position_trail
  convoy_id, vehicle_id, recorded_at (PK zusammen)
  lat, lon
```

- **Nur für Konvois, die an einer aktiven Aktionsseite hängen.** Ein
  allgemeiner Verlauf für jeden Einsatz wäre ein Bewegungsprofil, das niemand
  bestellt hat — datenschutzrechtlich und vom Volumen her.
- **Ausgedünnt**: höchstens ein Punkt je Fahrzeug alle 2 min oder nach 500 m.
  Bei 30 Fahrzeugen über 4 Tage sind das grob 90 000 Zeilen — harmlos.
- **Eine** Funktion (`services/positionsverlauf.py: aufzeichnen()`), aufgerufen
  von allen **drei** Stellen, die heute `VehiclePosition` schreiben:
  `track.py` (Fahrer-Link), `tracking.py` REST und `tracking.py` WebSocket. Ein
  Test hält das per AST fest, wie bei `mcp_context(werkzeug=…)` — die vierte
  Schreibstelle vergisst sonst jemand.
- **Löschung**: `retention.py` räumt den Verlauf X Tage nach `valid_until` der
  Aktionsseite (Vorschlag: 30 Tage, danach bleibt nur, was jemand exportiert).

Bekannte Einschränkung: Positionen tragen heute die **Serverzeit**
(`recorded_at=datetime.now()`), nicht den Messzeitpunkt am Gerät. Puffert die
Begleit-App im Funkloch und sendet später, landen die Punkte gestaucht am
Ende. Mit 2 h Verzögerung fällt das kaum auf; sauber wäre ein `ts` vom Gerät
(Plausibilitätsgrenze: nicht in der Zukunft, nicht älter als 12 h). Eigener
Punkt, nicht Voraussetzung.

## 3. Die Verzögerung gehört dem Server

Die Verzögerung wird **im Backend** angewendet, nie im Browser. Ein Filter im
Frontend wäre einer, den jeder mit den Entwicklertools aushebelt — und genau die
Echtzeitposition eines beladenen Lkw ist das, was nicht öffentlich sein soll.

- `delay_minutes` je Aktionsseite, **Untergrenze 60 serverseitig erzwungen**
  (Schema *und* Abfrage, nicht nur der Schieberegler).
- Der Endpunkt liefert nur Verlaufspunkte mit `recorded_at <= now - delay`.
  Nicht „die letzte Position minus Zeitstempel-Kosmetik".
- Die Seite zeigt den Stand offen an: „Stand 14:05 Uhr — aus Sicherheitsgründen
  zwei Stunden verzögert". Das erklärt auch, warum der Punkt „hinterherhängt".

### Der Teil, den die Verzögerung nicht löst: Rast und Übernachtung

Zwei Stunden Verzögerung schützen einen fahrenden Konvoi. Einen **stehenden**
schützen sie nicht: Parkt der Konvoi um 20 Uhr für die Nacht, zeigt die Seite
ab 22 Uhr den Parkplatz metergenau — acht Stunden lang, bis er weiterfährt.
Beladene Lkw auf einem bekannten Autohof sind genau das Szenario, das die
Verzögerung verhindern soll.

Deshalb: **Steht ein Konvoi zum verzögerten Zeitpunkt länger als 20 min, wird
seine Position vergröbert** (auf ein ~10-km-Raster oder auf den nächsten
größeren Ort: „Pause bei Györ"). Die gefahrene Linie endet entsprechend vor dem
Halt. Das ist eine reine Funktion (`services/aktionsseite.py`), ohne Datenbank
prüfbar, und sie ist der wichtigste Test dieses Plans.

Aus demselben Grund ist die **geplante Route standardmäßig aus**: Sie zeigt mit
Wegpunkten und Zeiten, wo der Konvoi heute Nacht stehen wird. Anzeigen lässt
sich wahlweise nur das Zielland/der Zielort.

## 4. Datenmodell und Schnittstelle

```
public_trackers                      public_tracker_convoys
  id, organization_id                  tracker_id, convoy_id
  slug         (≥ 22 Zeichen, zufällig) display_name   („Konvoi Rumänien")
  title, subtitle                      destination_label
  theme        ('weihnachten'|'neutral') color
  delay_minutes (≥ 60)                 position
  show_route   (none|destination|planned)
  valid_from, valid_until, enabled
  created_by_id, created_at
```

- `display_name` statt Konvoiname: intern heißt so etwas „KV 3 / Los B
  Ladeliste 2", öffentlich „Konvoi Bosnien".
- **Unbekannt, abgelaufen, abgeschaltet → dieselbe 404.** Keine Unterscheidung,
  die verrät, dass es den Slug gibt.
- `GET /api/public/aktion/{slug}` liefert je Konvoi: Anzeigename, Ziel, Status
  (`vor_abfahrt`, `unterwegs`, `pause`, `angekommen`), einen Punkt, die
  gefahrene Linie (vereinfacht, Douglas-Peucker), gefahrene/gesamte km.
  **Nichts sonst** — keine Fahrzeuge, Rufnamen, Telefonnummern, Stärke,
  Betriebsstoff, Alarme.
- **Ein Punkt je Konvoi**: das Fahrzeug mit `sonderfunktion = spitzenführer`,
  sonst das erste in der Reihenfolge mit Position. Dreißig Punkte, die sich über
  50 km verteilen, erklären nichts und verraten mehr.
- Fortschritt über `cumulative_along_route` (schon vorhanden, monoton). Ohne
  berechnete Route entfällt die km-Anzeige, die Seite funktioniert trotzdem.
- **Cache**: Antwort je Slug höchstens einmal pro Minute berechnen (Muster aus
  `status.py`, `_public_cache`), `Cache-Control: public, max-age=60`. Weil die
  Daten ohnehin verzögert sind, kostet das nichts — und wenn die Seite in einem
  Radiobeitrag genannt wird, trifft der Andrang den Cache, nicht PostGIS.
- Rate-Limit je IP wie bei den Kacheln. `/api/public/aktion` in
  `_EXEMPT_PREFIXES` des Lizenzwächters prüfen.

**Nicht** in `PUBLIC_OPERATIONS`, `llms.txt`, `sitemap.xml` oder sonst einer
Auskunft für Agenten: Die Seite ist „versteckt", also nur über den Link
erreichbar, mit `noindex`. Versteckt ist dabei kein Schutz, sondern nur
Unauffälligkeit — der Schutz sind Verzögerung und Vergröberung.

## 5. Oberfläche

**Öffentliche Seite** `/aktion/[slug]` (SvelteKit, eigene Route, ohne Org-Layout):

- Vollbildkarte mit allen Konvois, Seitenleiste/Unterkarte je Konvoi:
  Name, Ziel, Status, „noch 640 km", Stand-Zeitpunkt.
- Abruf alle 60 s, kein WebSocket.
- `?anzeige=1` für Bildschirme bei Veranstaltungen: kein Bedienelement,
  automatisches Durchschalten der Konvois, große Schrift.
- **Vorschaubild** für WhatsApp, Facebook & Co.: `og:image` aus
  `static_map.py` (gibt es schon), serverseitig gerendert und gecacht.
  Bei einer Seite, die geteilt werden soll, ist das der erste Eindruck.
- Datenschutzhinweis und Impressum verlinkt.

**Thema „weihnachten"** (reines CSS/SVG, keine Abhängigkeit):

- Nachtblauer Hintergrund, warmes Rot/Gold, Schneefall (Canvas, ≤ 60
  Flocken, **aus bei `prefers-reduced-motion`** und im Anzeigemodus wählbar).
- Konvoi-Marker als Lkw mit Geschenk, gefahrene Strecke als Lichterkette
  (gestrichelte Linie mit leuchtenden Punkten), Ziel als Stern.
- Kurzer Jubel (Sterne) beim Statuswechsel auf `angekommen`.
- Dazu eine Zeile Fakten, wenn die Organisation sie pflegt („12 Lkw,
  ~6 000 Päckchen") — Freitext, nicht berechnet.

**Logo und Markenauftritt** kommen über das bestehende Org-Branding
(`branding/org/{slug}`), **nicht ins Repo**. Name und Logo einer fremden
Organisation gehören nicht in ein AGPL-Repository, und für die Nutzung braucht es
deren ausdrückliches Einverständnis samt Dateien von ihrer Öffentlichkeitsarbeit.

**Verwaltung** im Org-Admin, Reiter „Aktionsseiten": anlegen, Konvois wählen und
benennen, Verzögerung (60–180 min), Routenanzeige, Zeitraum, Vorschau
**mit der echten Verzögerung**, QR-Code (vorhanden für Share-Links),
Sofort-Aus. Anlegen, Ändern und Abschalten ins Audit-Log.

## 6. Was außerhalb des Codes stimmen muss

Diese Punkte entscheiden mehr über den Erfolg als die Seite selbst:

- **GPS-Quelle über Tage.** Mindestens das Spitzenfahrzeug jedes Konvois
  braucht ein Gerät mit Begleit-App oder Fahrer-Link, Dauerstrom (12/24 V) und
  Halterung. Ein Handy in der Jackentasche hält keine 18 Stunden Fahrt durch.
  Ein Ersatzgerät im Schlussfahrzeug.
- **Roaming.** Die EU-Regelung endet an der EU-Grenze. Albanien, Bosnien,
  Serbien, Moldau, Ukraine kosten je nach Vertrag pro MB. Datenpaket oder lokale
  SIM einplanen — sonst endet die Linie an der Grenze, und die Rechnung kommt
  im Januar.
- **Routing-Region.** Der GraphHopper-Graph der Instanz muss die Strecken bis
  ins Zielland abdecken (`2026-09-04-mehrere-regionen.md`). Für Deutschland bis
  Südosteuropa ist das ein großer Import mit entsprechendem RAM. Ohne Route
  funktioniert die Seite, nur ohne km-Fortschritt.
- **Instanz.** Läuft die Seite auf derselben Instanz wie der Einsatzbetrieb,
  trifft ein Ansturm aus der Presse beide. Cache (oben) plus ggf. Caddy-Cache
  für `/api/public/aktion/*` reichen voraussichtlich; die Alternative ist eine
  eigene kleine Instanz nur für die Seite.
- **Datenschutz.** Die Fahrerinnen und Fahrer werden vorab informiert, dass die
  Position ihres Konvois verzögert und vergröbert öffentlich gezeigt wird. Ein
  Absatz im Datenschutzhinweis der Seite.
- **Nightly ist kein Kanal für diesen Zeitraum.** Die Instanz läuft vom
  Abfahrtstag bis zur Rückkehr auf `latest` und mit angehaltenem Auto-Update —
  ein Deploy, der GraphHopper neu laden lässt (siehe CLAUDE.md, 2026-09-19),
  braucht während der Fahrt niemand.

## 7. Tests

Backend (`backend/tests/`):

- `test_aktionsseite_verzoegerung.py` — kein ausgelieferter Punkt ist jünger
  als `now - delay`; `delay_minutes < 60` wird abgewiesen; unbekannt,
  abgelaufen und abgeschaltet ergeben dieselbe Antwort.
- `test_aktionsseite_rast.py` — ein stehender Konvoi wird vergröbert, ein
  fahrender nicht; die Linie endet vor dem Halt. Reine Funktion, ohne DB.
- `test_aktionsseite_felder.py` — das öffentliche Schema enthält genau die
  freigegebenen Felder; ein neues Feld in `TrackVehicle` erscheint dort nicht.
- `test_positionsverlauf.py` — Ausdünnung; aufgezeichnet wird nur für Konvois
  an aktiven Aktionsseiten; alle drei Schreibstellen rufen `aufzeichnen()` (AST).

Frontend (`frontend/e2e/aktionsseite.spec.ts`):

- weder DOM noch Netzwerkantworten enthalten Rufnamen oder Fahrzeugnamen;
- `noindex` ist gesetzt;
- bei `prefers-reduced-motion` fällt kein Schnee;
- der Stand-Zeitpunkt ist sichtbar.

## 8. Reihenfolge und Zeitplan

Heute ist der 2. Oktober; Abfahrt der Konvois ist nach Weihnachten. Das sind
gut zwölf Wochen, und die letzten zwei davon sind für Proben, nicht für Code.

| Bis | Schritt |
|---|---|
| 24.10. | Migration `0052` (Aktionsseite + Verlauf), `aufzeichnen()` an allen drei Stellen, Endpunkt mit Verzögerung, Vergröberung und Cache; Backend-Tests |
| 14.11. | Öffentliche Seite inkl. Thema, Anzeigemodus, Vorschaubild; Verwaltung im Org-Admin; E2E-Tests |
| 28.11. | **Probefahrt**: ein echtes Fahrzeug, ein Tag, mit Pause und Übernachtung. Prüfen: Verzögerung, Vergröberung, Akku, Linie |
| 12.12. | Abnahme mit der Organisation (Texte, Logo, Konvoinamen, Ziele), Roaming und Geräte geklärt, Region importiert |
| 15.12. | Code-Freeze, Instanz auf `latest`, Auto-Update für den Zeitraum aus |
| Abfahrt bis Rückkehr | Betrieb; Sofort-Aus griffbereit |
| Rückkehr + 30 Tage | Seite aus, Verlauf gelöscht (Retention) |

## 9. Offene Fragen an die Organisation

Beantwortet am 2. Oktober (Folgen in Abschnitt 10):

1. ~~Wie viele Konvois, welche Zielländer?~~ 2–3 parallel, Start jeweils in
   Deutschland, Ziele Rumänien, Albanien, Bosnien und Herzegowina.
2. ~~Eine Instanz der Organisation oder die gehostete?~~ Offen; im Gespräch
   ist ein eigener Server für die öffentliche Seite, angebunden per API.
3. ~~Wer stellt die Geräte?~~ Die Fahrer mit ihren eigenen Handys, über den
   Fahrer-Link im Browser oder die Begleit-App.

Weiter offen:

4. 1 oder 2 Stunden Verzögerung? (Empfehlung: 2 h — kostet nichts, und die
   Vergröberung bei Halt bleibt trotzdem nötig.)
5. Ziel genau (Lagerhalle) oder nur Ort/Land anzeigen?
6. Logo und Freigabe der Öffentlichkeitsarbeit — wer liefert, wer gibt frei?
7. Ist Presse eingebunden? Mit dem abgesetzten Server (10.1) entscheidet das
   nur noch über dessen Größe, nicht mehr über die Einsatzinstanz.
8. Auf welcher Instanz läuft die Planung der Konvois? Die Aktionsseite
   braucht eine, von der sie abfragt.

## 10. Stand 2. Oktober: Antworten und Folgen

### 10.1 Die öffentliche Seite auf einem eigenen Server

Der Vorschlag, die Seite abgesetzt zu betreiben und per API anzubinden, ist
besser als der ursprüngliche Plan — vorausgesetzt, die Richtung stimmt:

```
Einsatzinstanz                         Öffentlicher Server
(Planung, Tracking, Verlauf)           (nur Anzeige)
  GET /api/public/aktion/{slug}  ◀──── holt jede Minute, mit API-Schlüssel
  → schon verzögert, vergröbert,       → legt die Antwort ab, liefert sie
    auf die Positivliste beschnitten     samt Seite und Kacheln aus
```

- **Die Einsatzinstanz liefert nur, was öffentlich sein darf.** Verzögerung,
  Vergröberung und Feldauswahl bleiben dort (Abschnitte 3 und 4). Der
  öffentliche Server bekommt nie eine Echtzeitposition zu sehen. Wird er
  übernommen, steht dort nichts, was nicht ohnehin auf der Seite stand.
- **Abgeholt, nicht gepusht.** Die Einsatzinstanz braucht keinen Zugang zum
  öffentlichen Server, und ein ausgefallener öffentlicher Server stört den
  Einsatz nicht. Umgekehrt zeigt die Seite bei ausgefallener Einsatzinstanz
  den letzten Stand mit Zeitstempel weiter.
- **Andrang trifft die Einsatzinstanz nicht.** Sie sieht genau einen Abruf pro
  Minute, egal ob zehn oder hunderttausend Leute zuschauen. Damit erledigt
  sich auch die Frage nach Caddy-Cache und eigener Instanz aus Abschnitt 6.
- **Zugang**: ein eigener API-Schlüssel nur für diesen Endpunkt (das
  `api_key`-Modell gibt es), zusätzlich bleibt der Slug unratbar. Der
  Endpunkt antwortet ohne Schlüssel weiter für die Vorschau im Org-Admin.
- **Was auf den öffentlichen Server kommt**: die gebaute Seite (statisch,
  aus demselben Repo, eigener Build-Einstieg), ein kleiner Abholer und ein
  Kachel-Cache. Die Kacheln gehören **nicht** durch den Proxy der
  Einsatzinstanz — sonst trifft der Andrang sie doch, nur über einen Umweg.
  Entweder eigener Kachel-Cache auf dem öffentlichen Server oder ein
  Kachelanbieter mit Nutzungsbedingungen für öffentliche Seiten; die
  OSM-Standardkacheln sind für so etwas ausdrücklich nicht gedacht.

Kosten gegenüber Abschnitt 4: ein zusätzliches Deploy-Ziel und ein Abholer.
Der Endpunkt selbst bleibt gleich. Die Entscheidung muss trotzdem bis zum
24.10. fallen, weil der Seiten-Build davon abhängt.

### 10.2 Handys der Fahrer als einzige Quelle

Das funktioniert, hat aber eine Schwachstelle, die vor der Probefahrt geklärt
sein muss: **Der Fahrer-Link im Browser sendet nur, solange die Seite vorne
und der Bildschirm an ist.** Mobile Browser stellen die Ortung im Hintergrund
ein; die angemeldete Tracking-Seite hält den Bildschirm wenigstens per Wake
Lock wach, der Fahrer-Link (`routes/track/[slug]`) nicht einmal das. Ein Handy,
das in der Halterung ausgeht, liefert stundenlang nichts.

Folgen:

- **Für die Spitzenfahrzeuge die Begleit-App** (ortet im Hintergrund) und
  Dauerstrom. Der Browser ist Notlösung, nicht Plan.
- **Wake Lock auch am Fahrer-Link** nachziehen — klein, eigener PR, hilft
  allen Einsätzen, nicht nur diesem.
- Mit mehreren meldenden Fahrzeugen je Konvoi wird der „eine Punkt je
  Konvoi" (Abschnitt 4) wichtiger: Fällt das Spitzenfahrzeug aus, nimmt die
  Seite das nächste Fahrzeug mit frischer Position, statt stehen zu bleiben.
- Private Handys heißen private Datentarife: das Roaming-Thema aus Abschnitt 6
  trifft die Fahrer persönlich. Albanien und Bosnien liegen außerhalb der EU,
  ebenso Serbien und Montenegro, durch die die Strecken voraussichtlich
  führen. Rumänien ist EU. Klären, wer die Kosten trägt oder ob es
  Daten-SIMs gibt.

### 10.3 Routing-Region

Für den km-Fortschritt braucht die Einsatzinstanz einen Graphen von
Deutschland bis zu den Zielen, also mindestens: Deutschland, Österreich,
Ungarn, Rumänien, Slowenien, Kroatien, Bosnien und Herzegowina, Serbien,
Montenegro, Albanien (Tschechien/Slowakei je nach Strecke). Das geht über die
Mehrfach-Regionen (`merge-extracts.sh`), ist aber ein großer Import mit
entsprechendem RAM. Fällt er zusammen mit der GraphHopper-Hebung bis Ende
November (siehe `.trivyignore`, Review by 2026-11-30), wird nur einmal neu
importiert.

Ohne diesen Graphen funktioniert die Seite trotzdem — Punkt und gefahrene
Linie kommen aus dem Positionsverlauf, nicht aus dem Routing. Es fehlt dann
nur „noch 640 km".
