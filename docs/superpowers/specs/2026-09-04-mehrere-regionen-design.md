# Design-Spec: Mehrere Regionen zu einer Karte kombinieren

Status: **Entwurf zur Abstimmung** · Stand: 2026-09-04

Seit `v2026.4.0` lässt sich die Kartenregion im Admin-Panel wechseln — aber immer
nur auf **eine** vorgefertigte Geofabrik-Region. Wer Konvois nach Polen fährt,
muss zwischen DACH (5,8 GB, ohne Polen) und ganz Europa (32,5 GB, unbezahlbar
auf üblicher Hardware) wählen. Diese Spezifikation beschreibt, wie mehrere
Regionen zu einer Karte zusammengeführt werden.

Der Gewinn ist der Grund für das Vorhaben: Deutschland + Polen + Tschechien
liegen bei rund 7 GB und ~12 GB Import-Heap. Ganz Europa bräuchte 32,5 GB und
~42 GB Heap — auf einer 16-GB-Maschine unerreichbar, auf einer 32-GB-Maschine
gerade so.

---

## 1. Die Vorbedingung — beantwortet

Vor dem Entwurf stand eine Frage, die das Vorhaben hätte beenden können:
**Routet GraphHopper über die Grenze zwischen zwei getrennt heruntergeladenen
Extracts?**

Geofabrik schneidet Länder mit Überlappung. Eine Straße von Görlitz nach
Zgorzelec besteht aus Knoten und Wegen, die in beiden Dateien vorkommen. Baut
GraphHopper daraus zwei getrennte Graphkomponenten, liefert das Feature genau
an den Grenzen keine Route — also dort, wo es gebraucht wird.

Ein Wegwerf-CI-Job hat es gemessen (Sachsen 256 MB + Niederschlesien 172 MB,
`osmium merge`, Import, drei Routenanfragen):

| Route | Ergebnis |
|---|---|
| Dresden → Leipzig (Kontrolle, nur DE) | 108,8 km ✓ |
| **Görlitz → Zgorzelec** (1,5 km über die Neiße) | **2,30 km ✓** |
| **Dresden → Wrocław** (~270 km) | **268,3 km ✓** |

**Die Deduplizierung ist nachgewiesen:** Sachsen 24.334.281 Knoten +
Niederschlesien 19.478.781 = 43.813.062 roh; die zusammengeführte Datei hat
43.518.881 — **294.181 Knoten weniger**. Das sind die 0,67 % Überlappung im
Grenzstreifen, die `osmium merge` korrekt verschmolzen statt verdoppelt hat.
Genau das ist die Voraussetzung dafür, dass GraphHopper eine durchgehende
Straße sieht.

**Das Zusammenführen ist billig:** 19,5 Sekunden für 428 MB. Hochgerechnet auf
vier Länder wären das wenige Minuten gegenüber Stunden Graph-Import.

---

## 2. Datenmodell

### Die Zusammensetzung wandert in den Dateinamen

`graphhopper/entrypoint.sh:90` bildet den Fingerprint, der einen Graph-Neubau
auslöst:

```sh
FINGERPRINT="$OSM_FILENAME|$ENCODED_VALUES"
```

Er hängt am **Dateinamen**. Die zusammengeführte Datei wird deshalb nach einem
Kurz-Hash der *sortierten* Bestandteilsliste benannt:

```
merged-a3f9c21e.osm.pbf
```

Damit erledigt sich die Neubau-Erkennung von selbst: Wechselt jemand von
„Deutschland + Polen" auf „Deutschland + Tschechien", ändert sich der Hash,
damit der Dateiname, damit der Fingerprint — und der Mechanismus aus #420
greift unverändert. **Kein neuer Code, keine zweite Wahrheit.** Die Sortierung
stellt sicher, dass „DE, PL" und „PL, DE" denselben Hash ergeben und kein
überflüssiger Neubau ausgelöst wird.

### `.region` bekommt einen vierten Schlüssel

```
OSM_DOWNLOAD_URL=https://download.geofabrik.de/europe/germany-latest.osm.pbf
OSM_FILENAME=merged-a3f9c21e.osm.pbf
JAVA_OPTS=-Xmx12g -Xms1g -XX:+UseG1GC
OSM_SOURCES=europe/czech-republic|europe/germany|europe/poland
```

`OSM_SOURCES` ist neu: `|`-getrennt, **sortiert**, enthält Geofabrik-Pfade ohne
Schema und Suffix. Für eine Einzelregion fehlt der Schlüssel — dann verhält
sich alles exakt wie heute.

**Das ist der Regressionsschutz: Bestandsinstallationen sehen keinen
Unterschied.** `region-source.sh` behält seine Alles-oder-nichts-Semantik für
die drei bisherigen Schlüssel; `OSM_SOURCES` ist der einzige optionale und
darf fehlen, ohne die Datei zu verwerfen. Das ist die einzige Aufweichung der
bestehenden Strenge und braucht einen eigenen Test.

### Der Erstdownload-Fall — der unsicherste Punkt

`OSM_DOWNLOAD_URL` bleibt auf dem **ersten** Bestandteil stehen, damit der
Erstdownload-Pfad in `entrypoint.sh` (greift bei leerem Volume) nicht ins Leere
läuft. Das ist ein Kompromiss mit einem Haken: Ein frisch aufgesetzter
Container würde nur die erste Region laden und mit **unvollständiger Karte**
starten — stillschweigend, mit Routen, die an der Grenze enden.

**Festlegung:** Ist `OSM_SOURCES` gesetzt und die zusammengeführte Datei fehlt,
lädt `entrypoint.sh` **nichts** selbst. Er schreibt eine unmissverständliche
Meldung und wartet, bis der Updater die Datei bereitgestellt hat. Ein Container,
der sichtbar wartet, ist besser als einer, der mit halber Karte routet.

Damit ist die Zuständigkeit sauber getrennt: Einzelregion → Entrypoint darf
laden; Kombination → nur der Updater erzeugt die Datei. **Dieser Punkt ist der
erste, den der Implementierungsplan verifizieren muss** — hier greifen
Entrypoint und Updater ineinander, und beide könnten sich für zuständig halten.

---

## 3. Ablauf: aus fünf Phasen werden sechs

| | Phase | Änderung |
|---|---|---|
| 1 | Prüfen | Summe über alle Bestandteile |
| 2 | Laden | N Downloads statt einem |
| 3 | **Zusammenführen** | **neu** |
| 4 | Importieren | unverändert |
| 5 | Schwenken | unverändert |
| 6 | Aufräumen | alle Quelldateien |

### Woher `osmium` kommt

**Nicht ins GraphHopper-Image**, sondern als eigener Wegwerf-Container aus
einem schlanken Debian-Image mit `osmium-tool`. Begründung: Das
GraphHopper-Image ist das einzige, das dauerhaft läuft und von außen erreichbar
ist — jedes zusätzliche Paket vergrößert seine Angriffsfläche für einen
Schritt, der einmal pro Regionswechsel läuft. Der Merge-Container lebt Sekunden
und verschwindet.

### Teilerfolge gibt es nicht

**Scheitert einer von N Downloads, scheitert der ganze Wechsel.** Phase 2 bricht
ab, nichts wurde angefasst, die alte Region läuft weiter. Kein teilweises
Zusammenführen: Eine Karte, der ein Land fehlt, ist schlimmer als kein Wechsel,
weil sie stillschweigend falsche Routen liefert statt sichtbar zu fehlen.

Dieselbe Regel für Phase 3: Ist die zusammengeführte Datei unplausibel klein
(deutlich unter der Summe der Quellen abzüglich erwarteter Überlappung), gilt
sie als verstümmelt und der Wechsel bricht ab.

### Plattenbedarf

Während des Wechsels liegen gleichzeitig auf der Platte: N Quelldateien, die
zusammengeführte Datei, der Staging-Graph, der alte Graph, das alte Extract.
Das ergibt das **4,5-fache der Quellsumme** — für DE+PL+CZ (~7 GB Quellen)
also rund **32 GB**. Das muss die Vorab-Rechnung
ausweisen — nicht im Nachhinein überraschen.

### Sicherheit unverändert

**Jeder Bestandteil durchläuft `validate_region_url` einzeln**, beidseitig
(Backend und Updater), wie bisher. Nichts an der Grenze aus den vier Fix-Runden
wird gelockert. Die zusammengeführte Datei entsteht ausschließlich aus URLs,
die diese Prüfung bestanden haben.

---

## 4. Oberfläche

### Auswahl wird zur Liste

Ein Klick auf einen Suchtreffer **fügt hinzu** statt zu ersetzen; gewählte
Regionen erscheinen als entfernbare Marken über dem Suchfeld. Die vier
Schnellwahl-Knöpfe (DACH, Deutschland, Bayern, Berlin) **ersetzen** die Auswahl
— sie sind gedacht als „einfach DACH". Das Suchfeld ergänzt.

### Die Rechnung läuft live mit

Bei jeder Hinzunahme aktualisieren sich Extract-Summe, RAM- und Plattenbedarf,
geschätzte Dauer und das Urteil. Wer beim zwölften Land ankommt, sieht „reicht
nicht" und einen gesperrten Knopf — **bevor** etwas passiert, nicht nach drei
Stunden. Das ist der Schutz gegen die Gefahr, die freie Mehrfachauswahl
mitbringt.

### Zwei Hinweise, die kein Urteil sind

**Überlappende Auswahl:** Wählt jemand Deutschland *und* Bayern, ist das nicht
falsch — `osmium merge` dedupliziert —, verschwendet aber Download und Zeit.
Das Panel weist darauf hin und bietet an, die Unterregion zu entfernen.

**Sinnlose Kombination:** Übersteigt die Summe die nächstgrößere fertige
Geofabrik-Region, sollte der Operator das erfahren. Wer Frankreich, Spanien,
Italien und Portugal wählt, bekommt den Hinweis, dass `europe` kleiner wäre —
plus den direkten Weg dorthin.

---

## 5. Fehlerfälle

Zusätzlich zu den bestehenden aus `2026-09-03-kartenregion-im-adminpanel-design.md`:

| Fall | Phase | Folge |
|---|---|---|
| Einer von N Downloads scheitert | 2 | Abbruch, alte Region unberührt |
| `osmium merge` scheitert | 3 | Abbruch, Quelldateien verworfen, alte Region unberührt |
| Zusammengeführte Datei unplausibel klein | 3 | Abbruch — ein stiller Teilmerge ist der gefährlichste Ausgang |
| Nur eine Region gewählt | — | kein Merge, exakt der heutige Pfad |
| `OSM_SOURCES` gesetzt, Datei fehlt, Volume leer | Start | Entrypoint lädt **nicht**, wartet sichtbar mit Meldung |

---

## 6. Teststrategie

**Der Spike wird zum wiederkehrenden Job.** Der Ablauf, der die Machbarkeit
belegt hat — zwei kleine Nachbarregionen zusammenführen, importieren, über die
Grenze routen —, gehört in die CI. Er hat bewiesen, dass es geht; er soll
beweisen, dass es so bleibt.

**Fingerprint-Stabilität:** Dieselbe Auswahl in anderer Reihenfolge ergibt
denselben Hash und löst **keinen** Neubau aus.

**Regressionsschutz:** `region-source.sh` mit und ohne `OSM_SOURCES`. Ohne den
Schlüssel muss sich das Verhalten bitgleich zu heute verhalten.

**Plausibilitätsprüfung:** ein absichtlich verstümmelter Merge muss abgelehnt
werden.

**Nicht automatisierbar** bleibt der Pfad mit großen Kombinationen — Laufzeit
und Speicher sprengen jeden Runner. Der CI-Job `region-merge` prüft Sachsen +
Niederschlesien (428 MB, ~2 Minuten Merge); DACH plus mehrere Nachbarländer
liegen bei mehreren Gigabyte und Stunden Import.

**Benannte Lücke — manueller Prüfschritt vor jedem Release:** Einmal auf einer
echten Instanz eine große Kombination wechseln (etwa DACH + Polen +
Tschechien) und prüfen, dass der Merge durchläuft, der Import nicht am Heap
scheitert und eine Route über die Grenze zurückkommt. Was CI abdeckt, ist der
*Mechanismus*; was sie nicht abdecken kann, sind Laufzeit und Speicherbedarf
in realer Größenordnung.

---

## 7. Offene Punkte für den Implementierungsplan

1. **Der Erstdownload-Fall** (Abschnitt 2) — greifen Entrypoint und Updater
   sauber ineinander, oder halten sich beide für zuständig? Zuerst zu klären.
2. Welches schlanke Image `osmium-tool` mitbringt, ohne selbst gebaut werden zu
   müssen.
3. Ab welcher Abweichung eine zusammengeführte Datei als verstümmelt gilt —
   die 0,67 % Überlappung aus dem Spike sind ein Datenpunkt, kein Gesetz.
4. Ob `OSM_SOURCES` in `.region` das richtige Format ist oder ob eine eigene
   Datei sauberer wäre, sobald die Liste lang wird.
