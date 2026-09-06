# Geodaten

Eine Datei, erzeugt — nicht von Hand gepflegt. Das Bauskript liegt unter
`scripts/geo/`, die Quelldaten (soweit nicht heruntergeladen) unter
`scripts/geo/sources/`.

| Datei | Zweck | Erzeugt von |
|---|---|---|
| `gebiete.geojson` | wählbare Zuständigkeitsgebiete im Leitstellen-Dialog | `scripts/geo/build_gebiete.py` |

```sh
python3 scripts/geo/build_gebiete.py   # lädt AT und CH/LI herunter
```

## Kein Umriss mehr in diesem Verzeichnis

Bis v2026.5.2 lag hier `dach.geojson`: der Umriss des Routing-Raums, aus dem
alle Karten ihre Maske bauen (alles außerhalb wird abgedunkelt, weil dort keine
Route berechenbar ist). Die Datei war fest DACH — und bekam den Regionswechsel
im Admin-Panel nicht mit. Nach einem Wechsel behauptete die Karte weiterhin
DACH, während GraphHopper längst etwas anderes geladen hatte.

Der Umriss kommt jetzt zur Laufzeit vom Backend (`GET /api/region/outline`),
das ihn aus der aktiven Region in `.region` und den Geometrien des
Geofabrik-Index ableitet — also immer aus genau dem Extract, das GraphHopper
tatsächlich geladen hat. Siehe `backend/app/api/routes/region.py` und
`frontend/src/lib/map/region.ts`.

Damit entfällt auch `scripts/geo/build_umriss.sh`.
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
