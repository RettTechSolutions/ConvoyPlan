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
