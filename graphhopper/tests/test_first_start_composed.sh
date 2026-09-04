#!/usr/bin/env bash
# Prueft den Erstdownload-Pfad von graphhopper/entrypoint.sh bei einer
# ZUSAMMENGESETZTEN Region (mehrere Geofabrik-Extracts zu einer Karte).
#
# Der Kern: Ist OSM_SOURCES gesetzt, darf der Entrypoint NICHT selbst laden —
# er kennt nur OSM_DOWNLOAD_URL, also den ersten Bestandteil, und startete
# sonst mit halber Karte. Routen liefen dann still an den Grenzen ins Leere.
#
# Der Test schneidet den ECHTEN Kopf von entrypoint.sh an der Kommentarmarke
# COMPOSED_WAIT_ENDE heraus und fuehrt ihn aus — er baut ihn nicht nach. Ein
# nachgebauter Kopf wuerde nur pruefen, ob die Kopie stimmt, nicht ob das
# Original noch tut, was es soll. Gleiches Vorgehen wie in
# test_entrypoint_region.sh.
set -uo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
ENTRYPOINT="$HERE/../entrypoint.sh"
REGION_SOURCE="$HERE/../region-source.sh"
FAILED=0

check() {
    if [ "$2" = "$3" ]; then
        echo "ok   — $1"
    else
        echo "FAIL — $1: erwartet '$3', bekam '$2'"
        FAILED=1
    fi
}

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

# Den echten Kopf bis zur Marke herausschneiden.
HEAD_SH="$TMP/head.sh"
sed -n '1,/COMPOSED_WAIT_ENDE/p' "$ENTRYPOINT" > "$HEAD_SH"
if ! grep -q "COMPOSED_WAIT_ENDE" "$HEAD_SH"; then
    echo "FAIL — Marke COMPOSED_WAIT_ENDE nicht in entrypoint.sh gefunden"
    exit 1
fi

run_head() {
    # Laeuft in einer Subshell mit eigenem OSM_DIR; REGION_COMPOSED_WAIT_ONCE
    # verlaesst die Warteschleife nach einem Durchlauf.
    ( set +e
      # GRAPH_DIR mitsetzen: der Kopf legt beide Verzeichnisse an, und /data/graph
      # ist ausserhalb eines Containers nicht anlegbar — unter `set -e` waere der
      # Lauf dort wortlos zu Ende, und der Test pruefte nichts.
      export OSM_DIR="$1" GRAPH_DIR="$1/graph" \
             REGION_SOURCE_SCRIPT="$REGION_SOURCE" REGION_COMPOSED_WAIT_ONCE=1
      shift
      for kv in "$@"; do export "${kv?}"; done
      sh "$HEAD_SH" 2>&1 )
}

# ── Fall 1: OSM_SOURCES gesetzt, Datei fehlt -> warten statt laden ──────────
D1="$TMP/d1"; mkdir -p "$D1"
cat > "$D1/.region" <<'EOF'
OSM_DOWNLOAD_URL=https://download.geofabrik.de/europe/germany-latest.osm.pbf
OSM_FILENAME=merged-a3f9c21e.osm.pbf
JAVA_OPTS=-Xmx6g -Xms1g -XX:+UseG1GC
OSM_SOURCES=europe/germany|europe/poland
EOF
out1="$(run_head "$D1")"
echo "$out1" | grep -q "Zusammengesetzte Kartenregion" && r=wartet || r=anderes
check "mit OSM_SOURCES wird gewartet statt geladen" "$r" "wartet"

echo "$out1" | grep -qi "updater" && r=ja || r=nein
check "Meldung nennt den Updater als Zustaendigen" "$r" "ja"

echo "$out1" | grep -q "Download wird gestartet" && r=ja || r=nein
check "der Download-Pfad wird NICHT betreten" "$r" "nein"

echo "$out1" | grep -q "europe/germany|europe/poland" && r=ja || r=nein
check "Meldung nennt die Bestandteile" "$r" "ja"

# ── Fall 2: ohne OSM_SOURCES bleibt alles wie bisher ────────────────────────
# Regressionsschutz fuer jede Bestandsinstallation. Hier wird der Kopf GESOURCT
# statt ausgefuehrt, damit die resultierenden Variablen pruefbar sind — der
# Download-Block selbst liegt hinter der Marke und ist nicht Teil des Kopfes.
D2="$TMP/d2"; mkdir -p "$D2/graph"
vals2="$( set +e
    export OSM_DIR="$D2" GRAPH_DIR="$D2/graph" \
           REGION_SOURCE_SCRIPT="$REGION_SOURCE" REGION_COMPOSED_WAIT_ONCE=1 \
           OSM_FILENAME=berlin-latest.osm.pbf \
           OSM_DOWNLOAD_URL=https://download.geofabrik.de/europe/germany/berlin-latest.osm.pbf
    # shellcheck source=/dev/null
    . "$HEAD_SH" >/dev/null 2>&1
    echo "${OSM_FILENAME}|${OSM_SOURCES:-LEER}" )"
check "ohne OSM_SOURCES bleibt der Dateiname aus der Env" "${vals2%%|*}" "berlin-latest.osm.pbf"
check "ohne .region bleibt OSM_SOURCES leer" "${vals2##*|}" "LEER"

out2="$(run_head "$D2" \
        "OSM_FILENAME=berlin-latest.osm.pbf" \
        "OSM_DOWNLOAD_URL=https://download.geofabrik.de/europe/germany/berlin-latest.osm.pbf")"
echo "$out2" | grep -q "Zusammengesetzte Kartenregion" && r=ja || r=nein
check "ohne OSM_SOURCES kein Warte-Hinweis" "$r" "nein"

# ── Fall 3: .region ohne OSM_SOURCES wird weiterhin akzeptiert ──────────────
# OSM_SOURCES ist der einzige OPTIONALE Schluessel — sein Fehlen darf die
# Alles-oder-nichts-Regel nicht ausloesen.
D3="$TMP/d3"; mkdir -p "$D3/graph"
cat > "$D3/.region" <<'REGEOF'
OSM_DOWNLOAD_URL=https://download.geofabrik.de/europe/germany/berlin-latest.osm.pbf
OSM_FILENAME=berlin-latest.osm.pbf
JAVA_OPTS=-Xmx3g -Xms1g -XX:+UseG1GC
REGEOF
vals3="$( set +e
    export OSM_DIR="$D3" GRAPH_DIR="$D3/graph" \
           REGION_SOURCE_SCRIPT="$REGION_SOURCE" REGION_COMPOSED_WAIT_ONCE=1
    # shellcheck source=/dev/null
    . "$HEAD_SH" >/dev/null 2>&1
    echo "${OSM_FILENAME}|${JAVA_OPTS}|${OSM_SOURCES:-LEER}" )"
check ".region ohne OSM_SOURCES: Dateiname greift" "$(echo "$vals3" | cut -d'|' -f1)" "berlin-latest.osm.pbf"
check ".region ohne OSM_SOURCES: JAVA_OPTS greift"  "$(echo "$vals3" | cut -d'|' -f2)" "-Xmx3g -Xms1g -XX:+UseG1GC"
check ".region ohne OSM_SOURCES: OSM_SOURCES leer"  "$(echo "$vals3" | cut -d'|' -f3)" "LEER"

out3="$(run_head "$D3")"
echo "$out3" | grep -q "WARNUNG" && r=verworfen || r=akzeptiert
check ".region ohne OSM_SOURCES wird akzeptiert" "$r" "akzeptiert"

# ── Fall 4: .region MIT OSM_SOURCES setzt die Variable ──────────────────────
D4="$TMP/d4"; mkdir -p "$D4/graph"
cp "$D1/.region" "$D4/.region"
# Die erwartete Datei anlegen, damit der Wartezweig NICHT betreten wird: dessen
# Test-Ausstieg ist ein `exit 0`, und beim Sourcen wuerde das die pruefende
# Shell beenden, bevor sie die Variablen ausgeben kann.
touch "$D4/merged-a3f9c21e.osm.pbf"
vals4="$( set +e
    export OSM_DIR="$D4" GRAPH_DIR="$D4/graph" \
           REGION_SOURCE_SCRIPT="$REGION_SOURCE" REGION_COMPOSED_WAIT_ONCE=1
    # shellcheck source=/dev/null
    . "$HEAD_SH" >/dev/null 2>&1
    echo "${OSM_SOURCES:-LEER}" )"
check "OSM_SOURCES aus .region wird exportiert" "$vals4" "europe/germany|europe/poland"

exit $FAILED
