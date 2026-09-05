#!/usr/bin/env bash
# Fuehrt mehrere Geofabrik-Extracts zu EINER Karte zusammen.
#
# Aufruf:  merge-extracts.sh <ziel.osm.pbf> <quelle1.osm.pbf> <quelle2.osm.pbf> ...
#
# Warum ein eigener Wegwerf-Container statt osmium im GraphHopper-Image:
# Das GraphHopper-Image ist das einzige, das dauerhaft laeuft und von aussen
# erreichbar ist. Jedes zusaetzliche Paket darin vergroessert seine
# Angriffsflaeche fuer einen Schritt, der einmal pro Regionswechsel laeuft.
# Der Merge-Container lebt Sekunden und verschwindet.
#
# Warum die Deduplizierung noetig ist: Geofabrik schneidet Laender mit
# Ueberlappung. Eine Strasse von Goerlitz nach Zgorzelec besteht aus Knoten,
# die in beiden Dateien vorkommen. `osmium merge` verschmilzt sie ueber ihre
# IDs — der Machbarkeits-Spike mass 294.181 zusammengefuehrte Knoten (0,67 %)
# zwischen Sachsen und Niederschlesien, und Routing ueber die Grenze
# funktionierte danach (Goerlitz->Zgorzelec 2,30 km, Dresden->Wroclaw 268 km).
# Ohne Deduplizierung baute GraphHopper zwei getrennte Graphkomponenten und
# lieferte genau an den Grenzen keine Route — also dort, wo sie gebraucht wird.
set -uo pipefail

TARGET="${1:?Zieldatei fehlt}"
shift
SOURCES=("$@")
[ "${#SOURCES[@]}" -ge 2 ] || { echo "FEHLER: mindestens zwei Quellen noetig" >&2; exit 1; }

# Image mit osmium-tool. Bewusst ein Image, das das Werkzeug bereits mitbringt,
# statt zur Laufzeit `apt-get install` auszufuehren: Der Wechsel soll nicht von
# einem Paket-Spiegel abhaengen, der gerade nicht antwortet.
MERGE_IMAGE="${REGION_MERGE_IMAGE:-stefda/osmium-tool:latest}"

# Volume-NAME, nicht Containerpfad: Ein Pfad wie /data/osm waere aus Sicht des
# Docker-Daemons ein Host-Pfad, und er legte dort ein leeres Verzeichnis an.
OSM_VOLUME="${OSM_VOLUME:?Volume-Name fehlt}"

TARGET_NAME="$(basename "$TARGET")"
TMP_NAME=".merge-$$.osm.pbf"

src_args=""
total_bytes=0
for s in "${SOURCES[@]}"; do
    [ -s "$s" ] || { echo "FEHLER: Quelle fehlt oder ist leer: $s" >&2; exit 1; }
    src_args="$src_args /data/osm/$(basename "$s")"
    sz=$(stat -c%s "$s" 2>/dev/null || stat -f%z "$s" 2>/dev/null || echo 0)
    total_bytes=$((total_bytes + sz))
done

echo "Führe ${#SOURCES[@]} Extracts zusammen (${total_bytes} Bytes roh)…"

# shellcheck disable=SC2086
if ! docker run --rm -v "${OSM_VOLUME}:/data/osm" "$MERGE_IMAGE" \
        osmium merge $src_args -o "/data/osm/$TMP_NAME"; then
    rm -f "$(dirname "$TARGET")/$TMP_NAME"
    echo "FEHLER: osmium merge fehlgeschlagen" >&2
    exit 1
fi

TMP_PATH="$(dirname "$TARGET")/$TMP_NAME"
merged_bytes=$(stat -c%s "$TMP_PATH" 2>/dev/null || stat -f%z "$TMP_PATH" 2>/dev/null || echo 0)

# Plausibilitaetspruefung: Das Ergebnis muss zwischen 80 % und 105 % der
# Quellsumme liegen.
#
# Nach unten grosszuegig, weil die Ueberlappung vom Zuschnitt der gemeinsamen
# Grenze abhaengt — der Spike mass 0,67 % zwischen zwei Nachbarregionen, bei
# stark verzahnten Gebieten kann es mehr sein. Nach oben eng, weil ein
# Ergebnis GROESSER als die Summe bedeutet, dass nichts dedupliziert wurde.
#
# Der Zweck ist der stille Teilmerge: eine Datei, die formal in Ordnung ist,
# aber nur einen Teil der Daten enthaelt. Sie wuerde importieren, starten und
# an den fehlenden Stellen einfach keine Route liefern.
min_bytes=$(( total_bytes * 80 / 100 ))
max_bytes=$(( total_bytes * 105 / 100 ))
if [ "$merged_bytes" -lt "$min_bytes" ] || [ "$merged_bytes" -gt "$max_bytes" ]; then
    rm -f "$TMP_PATH"
    echo "FEHLER: zusammengeführte Datei unplausibel (${merged_bytes} Bytes," \
         "erwartet ${min_bytes}–${max_bytes}) — vermutlich unvollständig." >&2
    exit 1
fi

mv -f "$TMP_PATH" "$TARGET" || { echo "FEHLER: Ergebnis konnte nicht abgelegt werden" >&2; exit 1; }
echo "Zusammengeführt: $TARGET_NAME (${merged_bytes} Bytes, $(( merged_bytes * 100 / total_bytes )) % der Rohsumme)"
