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

# Image mit osmium-tool, aus diesem Repo gebaut (docker/osmium/Dockerfile) und
# neben den uebrigen vier Images in die eigene GHCR veroeffentlicht.
#
# Bewusst ein fertiges Image statt `apt-get install` zur Laufzeit: Der Wechsel
# soll nicht von einem Paket-Spiegel abhaengen, der gerade nicht antwortet.
#
# Und bewusst ein EIGENES: Der naheliegende Kandidat `stefda/osmium-tool:latest`
# stammt vom 19.12.2017, ist 492 MB gross, laeuft als root, traegt die komplette
# Build-Toolchain mit sich und hat nur den Tag `latest` — also keinen, auf den
# sich pinnen liesse, ohne dass er unter einem wegwandern kann. Ein Container,
# der Schreibzugriff auf das OSM-Volume bekommt, sollte nichts davon sein.
# Das eigene Image bringt osmium-tool 1.18 aus Debian trixie statt der
# 2017er-Version.
MERGE_IMAGE="${REGION_MERGE_IMAGE:-ghcr.io/retttechsolutions/convoyplan/osmium:latest}"

# Volume-NAME, nicht Containerpfad: Ein Pfad wie /data/osm waere aus Sicht des
# Docker-Daemons ein Host-Pfad, und er legte dort ein leeres Verzeichnis an.
OSM_VOLUME="${OSM_VOLUME:?Volume-Name fehlt}"

TARGET_NAME="$(basename "$TARGET")"
TMP_NAME=".merge-$$.osm.pbf"

# Quellen paarweise verschieden — und zwar auch in ihren DATEINAMEN: Im
# Container liegen alle Extracts flach unter /data/osm, dort faellt jede
# Verzeichnisstruktur weg. Zwei Quellen mit demselben Dateinamen waeren fuer
# osmium dieselbe Datei, es verschmoelze sie mit sich selbst und lieferte ein
# Ergebnis, das jede Groessenpruefung besteht und trotzdem ein Gebiet weniger
# enthaelt als bestellt. Der Aufrufer verhindert das bereits beim Benennen der
# Downloads; das hier ist die letzte Linie, die auch ein kuenftiger zweiter
# Aufrufer nicht umgehen kann.
if [ "$(printf '%s\n' "${SOURCES[@]}" | sort -u | wc -l)" -ne "${#SOURCES[@]}" ]; then
    echo "FEHLER: dieselbe Quelle mehrfach angegeben" >&2; exit 1
fi
if [ "$(for s in "${SOURCES[@]}"; do basename "$s"; done | sort -u | wc -l)" -ne "${#SOURCES[@]}" ]; then
    echo "FEHLER: zwei Quellen tragen denselben Dateinamen — sie waeren im Container dieselbe Datei" >&2; exit 1
fi

src_args=""
total_bytes=0
largest_bytes=0
for s in "${SOURCES[@]}"; do
    [ -s "$s" ] || { echo "FEHLER: Quelle fehlt oder ist leer: $s" >&2; exit 1; }
    src_args="$src_args /data/osm/$(basename "$s")"
    sz=$(stat -c%s "$s" 2>/dev/null || stat -f%z "$s" 2>/dev/null || echo 0)
    total_bytes=$((total_bytes + sz))
    [ "$sz" -gt "$largest_bytes" ] && largest_bytes=$sz
done

echo "Führe ${#SOURCES[@]} Extracts zusammen (${total_bytes} Bytes roh)…"

# shellcheck disable=SC2086
# --network none: Der Merge liest und schreibt ausschliesslich im Volume.
# Ein Container, der fremde Kartendaten verarbeitet, braucht dafuer keinen
# Netzzugang — und ohne ihn kann er auch keinen herstellen.
if ! docker run --rm --network none -v "${OSM_VOLUME}:/data/osm" "$MERGE_IMAGE" \
        osmium merge $src_args -o "/data/osm/$TMP_NAME"; then
    rm -f "$(dirname "$TARGET")/$TMP_NAME"
    echo "FEHLER: osmium merge fehlgeschlagen" >&2
    exit 1
fi

TMP_PATH="$(dirname "$TARGET")/$TMP_NAME"
merged_bytes=$(stat -c%s "$TMP_PATH" 2>/dev/null || stat -f%z "$TMP_PATH" 2>/dev/null || echo 0)

# Plausibilitaetspruefung — und ihre Grenzen.
#
# Untergrenze: die groesste EINZELQUELLE. Obergrenze: 105 % der Rohsumme.
#
# Was eine Groessenpruefung grundsaetzlich NICHT kann: einen legitimen Merge
# von einem unterscheiden, der eine Quelle verloren hat. Waehlt jemand
# `europe/germany` zusammen mit `europe/dach`, ist das Ergebnis bitgleich zu
# einem Merge, bei dem Deutschland unter den Tisch fiel. Das ist kein Zufall,
# sondern die Regel: Faellt ein fehlender Bestandteil an der Groesse nicht auf,
# war sein Inhalt im Ergebnis ohnehin enthalten — der Verlust ist dann
# folgenlos. Umgekehrt ist der Fehlbetrag bei einem SCHAEDLICHEN Verlust zwar
# gross, aber nicht im Voraus bekannt; jede Anteilsgrenze verwirft deshalb
# irgendwann einen richtigen Merge, und zwar erst, nachdem alle Gigabyte
# geladen wurden. Eine schaerfere Schwelle loest das nicht, sie verschiebt nur,
# in welche Richtung man falsch liegt.
#
# Die Groessenpruefung traegt deshalb NICHT die Last, einen stillen Teilmerge
# zu erkennen. Das tun strukturelle Zusicherungen:
#   * jede Quelle existiert und ist nicht leer (oben),
#   * die Quellen sind paarweise verschieden, auch im Dateinamen (oben),
#   * die Bestandteile werden kollisionsfrei benannt — voller Pfad statt
#     basename, sonst treffen sich `europe/georgia` und
#     `north-america/us/georgia` (switch-region.sh),
#   * der Aufrufer vergleicht die Zahl geladener Dateien gegen die Zahl
#     angeforderter Bestandteile (ebenda),
#   * und `osmium merge` bricht mit Fehlercode ab, wenn es eine angegebene
#     Datei nicht lesen kann — es ueberspringt sie nicht still.
# Sind die erfuellt, hat osmium jede Quelle gesehen.
#
# Was die Groessenpruefung danach noch abfaengt, ist das, wofuer sie taugt:
# ein abgeschnittenes Ergebnis (Untergrenze) und eines, in dem gar nicht
# dedupliziert wurde (Obergrenze) — dann zerfaellt der Graph an den Grenzen.
# Die Untergrenze ist bewusst so gewaehlt, dass sie nie einen richtigen Merge
# verwirft: Das Ergebnis enthaelt jede Quelle vollstaendig und kann deshalb nie
# kleiner sein als die groesste von ihnen.
min_bytes="$largest_bytes"
max_bytes=$(( total_bytes * 105 / 100 ))
if [ "$merged_bytes" -lt "$min_bytes" ] || [ "$merged_bytes" -gt "$max_bytes" ]; then
    rm -f "$TMP_PATH"
    echo "FEHLER: zusammengeführte Datei unplausibel (${merged_bytes} Bytes," \
         "erwartet ${min_bytes}–${max_bytes}) — vermutlich unvollständig." >&2
    exit 1
fi

mv -f "$TMP_PATH" "$TARGET" || { echo "FEHLER: Ergebnis konnte nicht abgelegt werden" >&2; exit 1; }
echo "Zusammengeführt: $TARGET_NAME (${merged_bytes} Bytes, $(( merged_bytes * 100 / total_bytes )) % der Rohsumme)"
