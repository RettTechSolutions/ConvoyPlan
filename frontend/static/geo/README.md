# Geodaten

Zwei Dateien, beide erzeugt — nicht von Hand gepflegt. Die Bauskripte liegen
unter `scripts/geo/`, die Quelldaten (soweit nicht heruntergeladen) unter
`scripts/geo/sources/`.

| Datei | Zweck | Erzeugt von |
|---|---|---|
| `gebiete.geojson` | wählbare Zuständigkeitsgebiete im Leitstellen-Dialog | `scripts/geo/build_gebiete.py` |
| `dach.geojson` | Umriss des Routing-Raums (Maske auf allen Karten) | `scripts/geo/build_umriss.sh` |

Reihenfolge zählt: `dach.geojson` wird aus `gebiete.geojson` abgeleitet.

```sh
python3 scripts/geo/build_gebiete.py   # lädt AT und CH/LI herunter
sh      scripts/geo/build_umriss.sh    # braucht mapshaper (via npx)
```

---

## `gebiete.geojson`

521 Gebiete: 400 deutsche Landkreise und kreisfreie Städte, 94 österreichische
politische Bezirke, 26 Schweizer Kantone, Liechtenstein. Genutzt für die
Gebietsauswahl bei der Anlage von Leitstellen-Zuständigkeitsgebieten; wird im
Auswahl-Dialog erst bei Bedarf nachgeladen (~950 kB).

Die Ebenen sind bewusst **nicht** einheitlich: In Deutschland und Österreich
hängt die Leitstellen-Zuständigkeit an der Kreis- bzw. Bezirksebene, in der
Schweiz am Kanton. Schweizer Bezirke wären dafür zu klein und existieren in
mehreren Kantonen gar nicht.

### Eigenschaften pro Feature

| Feld | Beschreibung |
|---|---|
| `code` | ISO-Land + Landesschlüssel: `DE-08115` (AGS), `AT-322` (Bezirkskennziffer), `CH-040` (NUTS-3), `LI-000` |
| `name` | Name des Gebiets |
| `country` | `DE` \| `AT` \| `CH` \| `LI` |
| `region` | Bundesland (DE/AT). `null` bei Kantonen und Liechtenstein — dort gibt es unterhalb des Bundes keine weitere Verwaltungsebene |

Das Länderpräfix im `code` ist nicht kosmetisch: Die Nummernkreise überschneiden
sich sonst (eine dreistellige österreichische Bezirkskennziffer gegen den Anfang
eines deutschen AGS). Bestandsdaten wurden mit Alembic-Migration `0039`
umgestellt.

### Quellen und Lizenzen

| Land | Ebene | Quelle | Lizenz |
|---|---|---|---|
| DE | Landkreise | BKG VG2500 über `scripts/geo/sources/landkreise.geojson` | dl-de/by-2-0 |
| AT | Politische Bezirke | [Statistik Austria](https://data.statistik.gv.at) über [ginseng666](https://github.com/ginseng666/GeoJSON-TopoJSON-Austria) | CC BY 4.0 |
| CH, LI | Kantone / Land | Eurostat NUTS-3 2024 über [Nuts2json](https://github.com/eurostat/Nuts2json) | © EuroGeographics |

**Namensnennung:** `© GeoBasis-DE / BKG (dl-de/by-2-0) · © Statistik Austria (CC BY 4.0) · © EuroGeographics / Eurostat`
— steht als `attribution`-Feld in der Datei und wird im Auswahl-Dialog unter der
Karte angezeigt.

### Fallstricke

- Die österreichische Quelle enthält **Wien doppelt**: einmal als Ganzes
  (`iso` 900) und einmal in 23 Gemeindebezirken (901–923), deckungsgleich
  übereinander. Das Bauskript wirft die 23 weg — für die Zuständigkeit zählt
  Wien als eine Einheit.
- Nuts2json liefert **TopoJSON**. Das Bauskript dekodiert es selbst (Delta-
  Kodierung, Quantisierung, Arc-Verweise), damit für die Regenerierung keine
  zusätzliche Abhängigkeit nötig ist.

### Kontrolle nach der Regenerierung

Das Skript bricht bei doppelten Schlüsseln ab und meldet die Gebietszahl je
Land. Erwartet: **DE 400, AT 94, CH 26, LI 1**. Die Landesflächen sollten auf
rund ein halbes Prozent an die amtlichen Werte herankommen (DE 357.596,
AT 83.879, CH 41.291, LI 160 km²) — größere Abweichungen heißen, dass eine
Quelle ihre Struktur geändert hat.

---

## `dach.geojson`

Umriss des abgedeckten Routing-Gebiets: Deutschland, Österreich, Schweiz und
Liechtenstein als **eine** zusammenhängende Fläche (~54 kB). Alles außerhalb
wird auf den Karten abgedunkelt bzw. ausgegraut, weil die Routenberechnung nur
innerhalb der geladenen OSM-Daten möglich ist (GraphHopper-Standard =
Geofabrik-Extract `europe/dach`). Die Maske selbst (Welt minus Region) wird zur
Laufzeit gebaut — siehe `src/lib/map/region.ts`.

Der Umriss ist exakt die Außengrenze von `gebiete.geojson`. Das ist der Grund
für die Ableitung statt einer eigenen Quelle: Kämen beide aus verschiedenen
Datensätzen, ragten im Leitstellen-Dialog Gebiete sichtbar über den Maskenrand
hinaus.

Die Datei ist reine **Anzeige**. Verbindlich ist allein, welches OSM-Extract
GraphHopper geladen hat: Wer über `OSM_DOWNLOAD_URL` eine andere Region fährt,
sollte sie passend austauschen — sonst zeigt die Karte ein Gebiet als
routingfähig an, das GraphHopper gar nicht kennt (oder umgekehrt).

### Fallstricke

- Die drei Landesdatensätze ziehen ihre gemeinsamen Grenzen um bis zu ~2 km
  unterschiedlich. Ohne `-clean gap-width=3km` blieben dunkle Nahtstreifen quer
  durch das Alpenvorland stehen.
- **Kein `-filter-slivers`** auf dem fertigen Mosaik: Der Verschnitt zwischen
  Gebietsgrenzen taucht als Loch auf und wird schon von `-clean` erledigt.
  `-filter-slivers` würde stattdessen kleine Außenflächen entfernen — und das
  sind hier echte Exklaven und Inseln (Vennbahn-Gebiet bei Aachen, Elbinseln,
  Halligen) zwischen 1,2 und 3 km².
- Innenringe werden verworfen. Übrig bleibt dort nur der Bodensee, an dem die
  Quellen unterschiedlich enden; echte Enklaven gibt es innerhalb von DACH nicht
  mehr — Jungholz und Büsingen sind Binnenland.

### Kontrolle nach der Regenerierung

Das Skript bricht ab, wenn die Fläche mehr als 2 % von der amtlichen Summe
abweicht, und meldet Teilflächen und Bounding-Box. Erwartet: **29 Teilflächen,
0 Innenringe, `lon 5,87…17,15 / lat 45,82…55,06`, rund 481.000 km²**.

Wichtig bei eigenen Prüfungen: Eine planare Shoelace-Formel mit festem
cos(Breite)-Faktor ist hier wertlos — der Hauptring spannt neun Breitengrade,
jede feste Bezugsbreite liegt um Prozente daneben. Das Skript rechnet deshalb
mit dem sphärischen Exzess.
