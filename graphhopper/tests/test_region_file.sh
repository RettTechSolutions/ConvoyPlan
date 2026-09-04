#!/usr/bin/env bash
# graphhopper/tests/test_region_file.sh
#
# Testet region-source.sh isoliert (ohne Container). Wichtig: das Skript wird
# GESOURCT (". ./region-source.sh"), nicht mit "bash region-source.sh"
# ausgefuehrt — sonst landen die "export"s im Kindprozess und der Test prueft
# nichts.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
SCRIPT="$HERE/../region-source.sh"
FAILED=0

check() { if [ "$2" = "$3" ]; then echo "ok   — $1"; else echo "FAIL — $1: erwartet '$3', bekam '$2'"; FAILED=1; fi }

TMP="$(mktemp -d)"; trap 'rm -rf "$TMP"' EXIT
mkdir -p "$TMP/osm"

run_sourced() {
    # Fuehrt region-source.sh in einer Subshell per "source" aus und gibt
    # die (moeglicherweise ueberschriebenen) Variablen zurueck.
    (
        export OSM_DIR="$TMP/osm" OSM_FILENAME="dach-latest.osm.pbf" \
               OSM_DOWNLOAD_URL="https://download.geofabrik.de/europe/dach-latest.osm.pbf" \
               JAVA_OPTS="-Xmx8g"
        . "$SCRIPT"
        echo "$OSM_DOWNLOAD_URL|$OSM_FILENAME|$JAVA_OPTS"
    )
}

# Fall 1: .region vorhanden — sie gewinnt
cat > "$TMP/osm/.region" <<'EOF'
OSM_DOWNLOAD_URL=https://download.geofabrik.de/europe/germany/berlin-latest.osm.pbf
OSM_FILENAME=berlin-latest.osm.pbf
JAVA_OPTS=-Xmx3g -Xms1g -XX:+UseG1GC
EOF
out="$(run_sourced)"
check ".region gewinnt gegen Env" "$out" \
    "https://download.geofabrik.de/europe/germany/berlin-latest.osm.pbf|berlin-latest.osm.pbf|-Xmx3g -Xms1g -XX:+UseG1GC"

# Fall 2: keine .region — Env bleibt unveraendert (Regressionsschutz)
rm -f "$TMP/osm/.region"
out="$(run_sourced)"
check "ohne .region bleibt Env" "$out" \
    "https://download.geofabrik.de/europe/dach-latest.osm.pbf|dach-latest.osm.pbf|-Xmx8g"

# Fall 3: leere .region — keine Aenderung, kein Absturz
: > "$TMP/osm/.region"
out="$(run_sourced)"
check "leere .region bleibt Env" "$out" \
    "https://download.geofabrik.de/europe/dach-latest.osm.pbf|dach-latest.osm.pbf|-Xmx8g"

# Fall 4: .region mit Zeile ohne '=' — Datei gilt als beschaedigt, komplett verwerfen
cat > "$TMP/osm/.region" <<'EOF'
OSM_DOWNLOAD_URL=https://download.geofabrik.de/europe/germany/berlin-latest.osm.pbf
kaputte zeile ohne gleichheitszeichen
OSM_FILENAME=berlin-latest.osm.pbf
JAVA_OPTS=-Xmx3g -Xms1g -XX:+UseG1GC
EOF
out="$(run_sourced)"
check "Zeile ohne '=' verwirft komplette .region (kein Mischzustand)" "$out" \
    "https://download.geofabrik.de/europe/dach-latest.osm.pbf|dach-latest.osm.pbf|-Xmx8g"

# Fall 5: .region mit unbekanntem Schluessel — ebenfalls komplett verwerfen
cat > "$TMP/osm/.region" <<'EOF'
OSM_DOWNLOAD_URL=https://download.geofabrik.de/europe/germany/berlin-latest.osm.pbf
OSM_FILENAME=berlin-latest.osm.pbf
JAVA_OPTS=-Xmx3g -Xms1g -XX:+UseG1GC
UNBEKANNT=irgendwas
EOF
out="$(run_sourced)"
check "unbekannter Schluessel verwirft komplette .region" "$out" \
    "https://download.geofabrik.de/europe/dach-latest.osm.pbf|dach-latest.osm.pbf|-Xmx8g"

# Fall 6: .region mit fehlendem Schluessel (unvollstaendig) — komplett verwerfen
cat > "$TMP/osm/.region" <<'EOF'
OSM_DOWNLOAD_URL=https://download.geofabrik.de/europe/germany/berlin-latest.osm.pbf
OSM_FILENAME=berlin-latest.osm.pbf
EOF
out="$(run_sourced)"
check "unvollstaendige .region (JAVA_OPTS fehlt) verwirft komplett" "$out" \
    "https://download.geofabrik.de/europe/dach-latest.osm.pbf|dach-latest.osm.pbf|-Xmx8g"

# Fall 7: Wert enthaelt selbst ein "=" (z.B. JAVA_OPTS mit "-XX:Flag=Wert") —
# es wird nur am ERSTEN "=" getrennt, alles danach bleibt Teil des Werts
cat > "$TMP/osm/.region" <<'EOF'
OSM_DOWNLOAD_URL=https://download.geofabrik.de/europe/germany/berlin-latest.osm.pbf
OSM_FILENAME=berlin-latest.osm.pbf
JAVA_OPTS=-Xmx3g -XX:MaxRAMPercentage=75.0
EOF
out="$(run_sourced)"
check "Wert mit '=' bleibt beim Wert (nur am ersten '=' getrennt)" "$out" \
    "https://download.geofabrik.de/europe/germany/berlin-latest.osm.pbf|berlin-latest.osm.pbf|-Xmx3g -XX:MaxRAMPercentage=75.0"

# Fall 8: Kommentarzeile ("#...") — bewusst NICHT toleriert, verwirft wie ein
# unbekannter Schluessel die komplette Datei (siehe Kommentar in region-source.sh)
cat > "$TMP/osm/.region" <<'EOF'
# Region: Berlin
OSM_DOWNLOAD_URL=https://download.geofabrik.de/europe/germany/berlin-latest.osm.pbf
OSM_FILENAME=berlin-latest.osm.pbf
JAVA_OPTS=-Xmx3g -Xms1g -XX:+UseG1GC
EOF
out="$(run_sourced)"
check "Kommentarzeile verwirft komplette .region (kein Komfort-Feature)" "$out" \
    "https://download.geofabrik.de/europe/dach-latest.osm.pbf|dach-latest.osm.pbf|-Xmx8g"

# Fall 9: doppelter Schluessel — der LETZTE Wert gewinnt
cat > "$TMP/osm/.region" <<'EOF'
OSM_DOWNLOAD_URL=https://download.geofabrik.de/europe/germany/berlin-latest.osm.pbf
OSM_FILENAME=berlin-latest.osm.pbf
OSM_FILENAME=hamburg-latest.osm.pbf
JAVA_OPTS=-Xmx3g -Xms1g -XX:+UseG1GC
EOF
out="$(run_sourced)"
check "doppelter Schluessel: letzter Wert gewinnt" "$out" \
    "https://download.geofabrik.de/europe/germany/berlin-latest.osm.pbf|hamburg-latest.osm.pbf|-Xmx3g -Xms1g -XX:+UseG1GC"

# Fall 10: Reihenfolge der drei Schluessel vertauscht — spielt keine Rolle
cat > "$TMP/osm/.region" <<'EOF'
JAVA_OPTS=-Xmx3g -Xms1g -XX:+UseG1GC
OSM_FILENAME=berlin-latest.osm.pbf
OSM_DOWNLOAD_URL=https://download.geofabrik.de/europe/germany/berlin-latest.osm.pbf
EOF
out="$(run_sourced)"
check "Reihenfolge der Schluessel ist beliebig" "$out" \
    "https://download.geofabrik.de/europe/germany/berlin-latest.osm.pbf|berlin-latest.osm.pbf|-Xmx3g -Xms1g -XX:+UseG1GC"

exit $FAILED
