# Geodaten — Kreisgrenzen

## `landkreise.geojson`

Grenzen der deutschen Landkreise und kreisfreien Städte (400 Kreise), genutzt
für die Landkreis-Auswahl bei der Anlage von Leitstellen-Zuständigkeitsgebieten.

- **Quelle:** Bundesamt für Kartographie und Geodäsie (BKG), Verwaltungsgebiete
  (VG2500, Stand 2023), bereitgestellt über das OpenDataSoft-Dataset
  `georef-germany-kreis`.
- **Lizenz:** Datenlizenz Deutschland – Namensnennung 2.0 (**dl-de/by-2-0**),
  <https://www.govdata.de/dl-de/by-2-0>. Kommerzielle Nutzung erlaubt bei
  Namensnennung.
- **Namensnennung:** `© GeoBasis-DE / BKG (dl-de/by-2-0)` — wird im Auswahl-Dialog
  unter der Karte angezeigt und ist als `attribution`-Feld in der GeoJSON enthalten.

### Eigenschaften pro Feature

| Feld        | Beschreibung                              |
|-------------|-------------------------------------------|
| `krs_code`  | Amtlicher Gemeindeschlüssel (AGS, 5-stellig) |
| `krs_name`  | Name des Kreises                          |
| `lan_name`  | Bundesland                                |

### Aufbereitung / Regenerierung

Die Originaldaten (~16 MB) wurden mit
[mapshaper](https://github.com/mbloch/mapshaper) topologie-erhaltend vereinfacht
(geteilte Grenzen werden nur einmal vereinfacht, damit benachbarte Kreise beim
Verschmelzen keine Lücken/Slivers erzeugen) und auf die benötigten Felder
reduziert:

```sh
curl -o kreise.geojson \
  "https://public.opendatasoft.com/api/explore/v2.1/catalog/datasets/georef-germany-kreis/exports/geojson"

npx mapshaper kreise.geojson \
  -filter-fields krs_code,krs_name,lan_name \
  -simplify 8% keep-shapes \
  -o precision=0.0001 format=geojson landkreise.geojson
```

Anschließend die Property-Arrays zu Skalaren geflacht und das `attribution`-Feld
ergänzt. Ergebnis: ~0,7 MB, wird im Auswahl-Dialog erst bei Bedarf nachgeladen.

## `dach.geojson`

Umriss des abgedeckten Routing-Gebiets: Deutschland, Österreich, Schweiz und
Liechtenstein als **eine** zusammenhängende Fläche. Genutzt für den
**Regionsfokus** der Karten: Alles außerhalb wird abgedunkelt bzw. ausgegraut,
weil die Routenberechnung nur innerhalb der geladenen OSM-Daten möglich ist
(GraphHopper-Standard = Geofabrik-Extract `europe/dach`). Die Maske selbst
(Welt minus Region) wird zur Laufzeit aus dieser Datei gebaut — siehe
`src/lib/map/region.ts`.

Die Datei ist reine **Anzeige**. Verbindlich ist allein, welches OSM-Extract
GraphHopper geladen hat: Wer über `OSM_DOWNLOAD_URL` eine andere Region fährt,
sollte diese Datei passend austauschen — sonst zeigt die Karte ein Gebiet als
routingfähig an, das GraphHopper gar nicht kennt (oder umgekehrt).

- **Quellen:**
  - Deutschland: BKG VG2500 — aus `landkreise.geojson` verschmolzen, also
    identisch zur Landkreis-Ebene. Deshalb passen Kreisgrenzen und Außengrenze
    im Leitstellen-Dialog exakt aufeinander.
  - Österreich, Schweiz, Liechtenstein:
    [Natural Earth](https://www.naturalearthdata.com/) 1:10m
    (`ne_10m_admin_0_countries`), Public Domain.
- **Namensnennung:** `© GeoBasis-DE / BKG (dl-de/by-2-0) · Natural Earth` —
  steht als `attribution`-Feld in der GeoJSON und wird über die GeoJSON-Quelle
  an MapLibres AttributionControl gemeldet (siehe `src/lib/map/region.ts`).

### Aufbereitung / Regenerierung

Zwei Quellen, ein Umriss — deshalb reicht kein simples `-dissolve`:

1. Deutschland aus `landkreise.geojson` verschmelzen (keine weitere
   Vereinfachung, damit die Grenzlinie auch bei hohem Zoom sauber bleibt).
   `-filter-slivers` gehört hier dazu: es räumt den Verschnitt zwischen den
   Kreisgrenzen weg. **Auf das fertige DACH-Mosaik darf es nicht angewendet
   werden** — dort läge der Schwellwert bei 3,4 km² und würde echte Inseln
   (Helgoland, Hiddensee) verschlucken.
2. AT/CH/LI aus Natural Earth herausfiltern.
3. Beides in *eine* FeatureCollection legen und mit `-clean gap-width=3km`
   zusammenführen. Die beiden Quellen ziehen die gemeinsame Grenze um bis zu
   ~2 km unterschiedlich; ohne diesen Schritt bleiben dunkle Nahtstreifen quer
   durch das Alpenvorland stehen.
4. Innenringe verwerfen. Übrig bleibt nach Schritt 3 nur der Bodensee (die
   Quellen enden dort unterschiedlich); innerhalb von DACH gibt es keine echten
   Enklaven mehr — Jungholz und Büsingen sind jetzt Binnenland.

```sh
# 1) Deutschland
npx mapshaper landkreise.geojson \
  -dissolve2 \
  -filter-slivers \
  -o precision=0.0001 format=geojson de.geojson

# 2) AT/CH/LI
curl -sSLo ne10m.geojson \
  "https://raw.githubusercontent.com/nvkelso/natural-earth-vector/master/geojson/ne_10m_admin_0_countries.geojson"
npx mapshaper ne10m.geojson \
  -filter '["AT","CH","LI"].indexOf(ISO_A2) > -1' \
  -o precision=0.0001 format=geojson atchli.geojson

# 3) + 4) zusammenführen, Naht schließen, Innenringe verwerfen
npx mapshaper -i combine-files de.geojson atchli.geojson \
  -merge-layers force \
  -clean gap-width=3km close-outer-gaps \
  -dissolve \
  -o precision=0.0001 format=geojson dach.geojson
```

Anschließend als einzelnes `Feature` mit `name`/`attribution` speichern.
Ergebnis: ~62 kB, wird beim Kartenstart einmalig geladen.

Kontrolle nach der Regenerierung: Die Bounding-Box muss ungefähr
`lon 5,87…17,15 / lat 45,82…55,06` sein, es dürfen keine Innenringe übrig
bleiben, und der Bodensee darf kein Loch sein.
