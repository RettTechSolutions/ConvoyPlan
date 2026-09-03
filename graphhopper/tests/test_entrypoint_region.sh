#!/usr/bin/env bash
# graphhopper/tests/test_entrypoint_region.sh
#
# region-source.sh isoliert zu testen (test_region_file.sh) reicht nicht:
# den Regionswechsel wirksam macht erst die Neuberechnung von OSM_FILE und
# DOWNLOAD_URL in entrypoint.sh NACH dem Sourcen. Dieser Test fuehrt genau
# diesen Skriptkopf tatsaechlich aus (nicht nachgebaut) und prueft die beiden
# abgeleiteten Variablen.
#
# Der Kopf wird per Marker (ENTRYPOINT_HEADER_ENDE-Kommentarzeile in
# entrypoint.sh) inhaltlich herausgeschnitten, nicht ueber eine Zeilennummer
# — das bleibt stabil, auch wenn oberhalb oder unterhalb Zeilen eingefuegt
# werden. Der Download-/Graph-Bau-Teil danach wird bewusst nicht mitgesourct.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
ENTRYPOINT="$HERE/../entrypoint.sh"
FAILED=0

check() { if [ "$2" = "$3" ]; then echo "ok   — $1"; else echo "FAIL — $1: erwartet '$3', bekam '$2'"; FAILED=1; fi }

if ! grep -q 'ENTRYPOINT_HEADER_ENDE' "$ENTRYPOINT"; then
    echo "FAIL — Marker ENTRYPOINT_HEADER_ENDE fehlt in entrypoint.sh (siehe Kommentar oben)"
    exit 1
fi

TMP="$(mktemp -d)"; trap 'rm -rf "$TMP"' EXIT
mkdir -p "$TMP/osm"

HEADER="$TMP/entrypoint_header.sh"
sed -n '1,/ENTRYPOINT_HEADER_ENDE/p' "$ENTRYPOINT" > "$HEADER"

run_header() {
    # REGION_SOURCE_SCRIPT lenkt das Sourcen im echten entrypoint.sh (Default
    # dort: /region-source.sh, existiert ausserhalb des Containers nicht) auf
    # die Datei im Repo um — ausschliesslich fuer Tests gedacht.
    (
        export OSM_DIR="$TMP/osm" OSM_FILENAME="dach-latest.osm.pbf" JAVA_OPTS="-Xmx8g" \
               OSM_DOWNLOAD_URL="https://download.geofabrik.de/europe/dach-latest.osm.pbf" \
               REGION_SOURCE_SCRIPT="$HERE/../region-source.sh"
        # shellcheck source=/dev/null
        . "$HEADER"
        echo "$OSM_FILE|$DOWNLOAD_URL|$JAVA_OPTS"
    )
}

# Fall 1: .region vorhanden — OSM_FILE und DOWNLOAD_URL zeigen auf die neue Region
cat > "$TMP/osm/.region" <<'EOF'
OSM_DOWNLOAD_URL=https://download.geofabrik.de/europe/germany/berlin-latest.osm.pbf
OSM_FILENAME=berlin-latest.osm.pbf
JAVA_OPTS=-Xmx3g -Xms1g -XX:+UseG1GC
EOF
out="$(run_header)"
check "entrypoint-Kopf: .region setzt OSM_FILE/DOWNLOAD_URL/JAVA_OPTS neu" "$out" \
    "$TMP/osm/berlin-latest.osm.pbf|https://download.geofabrik.de/europe/germany/berlin-latest.osm.pbf|-Xmx3g -Xms1g -XX:+UseG1GC"

# Fall 2: keine .region — bitgleich zum bisherigen Verhalten (Regressionsschutz)
rm -f "$TMP/osm/.region"
out="$(run_header)"
check "entrypoint-Kopf: ohne .region bleibt OSM_FILE/DOWNLOAD_URL/JAVA_OPTS bitgleich" "$out" \
    "$TMP/osm/dach-latest.osm.pbf|https://download.geofabrik.de/europe/dach-latest.osm.pbf|-Xmx8g"

# Fall 3: GRAPH_DIR und GH_COMMAND sind ueberschreibbar. Der Regionswechsel
# (docker/updater/switch-region.sh, Phase 3) baut den neuen Graphen damit in
# ein Staging-Verzeichnis, ohne den aktiven Graphen anzufassen — verschwindet
# der Default-Fallback hier, faellt der Import still zurueck auf /data/graph
# und ueberschreibt den laufenden Graphen.
run_dirs() {
    (
        export OSM_DIR="$TMP/osm" REGION_SOURCE_SCRIPT="$HERE/../region-source.sh"
        # shellcheck source=/dev/null
        . "$HEADER"
        echo "$GRAPH_DIR|$GH_COMMAND"
    )
}
out="$(GRAPH_DIR=/data/graph/.staging GH_COMMAND=import run_dirs)"
check "entrypoint-Kopf: GRAPH_DIR/GH_COMMAND ueberschreibbar" "$out" "/data/graph/.staging|import"

out="$(run_dirs)"
check "entrypoint-Kopf: ohne Vorgabe bleibt es /data/graph + server" "$out" "/data/graph|server"

exit $FAILED
