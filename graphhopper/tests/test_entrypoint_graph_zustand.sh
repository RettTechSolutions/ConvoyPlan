#!/usr/bin/env bash
# graphhopper/tests/test_entrypoint_graph_zustand.sh
#
# Prueft die Wipe-Entscheidung in graphhopper/entrypoint.sh: Wann wird ein
# vorhandenes Graph-Verzeichnis weggeworfen und neu gebaut?
#
# Anlass ist der Ausfall vom 2026-09-19. Im Volume lag ein TORSO: ein
# location_index aus einem abgebrochenen Import, kein Graph, dazu ein PASSENDER
# .graph_fingerprint — der Entrypoint schreibt ihn, bevor der Import beginnt,
# er beweist also nichts ueber Vollstaendigkeit. Der Entrypoint sah "Fingerprint
# stimmt", liess alles liegen, GraphHopper importierte 13 Minuten neu, las danach
# den fremden location_index und starb an
#   "location index was opened with incorrect graph: 6730092 vs. 30456657".
# `restart: unless-stopped` startete neu — Endlosschleife ohne Routing.
#
# Der Test schneidet den ECHTEN Block zwischen den Marken GRAPH_ZUSTAND_ANFANG
# und GRAPH_ZUSTAND_ENDE aus entrypoint.sh heraus und sourct ihn, statt ihn
# nachzubauen: ein Nachbau prueft nur, ob die Kopie stimmt. Gleiches Vorgehen
# wie in test_entrypoint_region.sh und test_first_start_composed.sh.
set -uo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
ENTRYPOINT="$HERE/../entrypoint.sh"
FAILED=0

check() {
    if [ "$2" = "$3" ]; then
        echo "ok   — $1"
    else
        echo "FAIL — $1: erwartet '$3', bekam '$2'"
        FAILED=1
    fi
}

for marke in GRAPH_ZUSTAND_ANFANG GRAPH_ZUSTAND_ENDE; do
    if ! grep -q "$marke" "$ENTRYPOINT"; then
        echo "FAIL — Marke $marke fehlt in entrypoint.sh (siehe Kommentar oben)"
        exit 1
    fi
done

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

BLOCK="$TMP/graph_zustand.sh"
sed -n '/^# ── GRAPH_ZUSTAND_ANFANG/,/^# ── GRAPH_ZUSTAND_ENDE/p' "$ENTRYPOINT" > "$BLOCK"

FP='dach-latest.osm.pbf|car_access, car_average_speed, road_class, max_speed, max_height'

# Fuehrt den echten Block gegen ein vorbereitetes Verzeichnis aus und gibt den
# gewaehlten REBUILD_REASON zurueck ("KEINER", wenn nicht neu gebaut wird).
run_block() {
    local dir="$1" downloaded="${2:-0}" filename="${3:-dach-latest.osm.pbf}"
    (
        export GRAPH_DIR="$dir" OSM_FILENAME="$filename" DOWNLOADED="$downloaded"
        # shellcheck source=/dev/null
        . "$BLOCK" >/dev/null 2>&1
        echo "${REBUILD_REASON:-KEINER}"
    )
}

# ── Fall 1: Torso — location_index ohne edges, Fingerprint passt ─────────────
# Der Kern dieses Tests: genau die Lage, die in die Crash-Schleife fuehrte.
D1="$TMP/torso"; mkdir -p "$D1"
printf 'x' > "$D1/location_index"
: > "$D1/gh.lock"
printf '%s' "$FP" > "$D1/.graph_fingerprint"
grund="$(run_block "$D1")"
case "$grund" in
    *Unvollstaendig*) r=ja ;;
    *)                r="nein ($grund)" ;;
esac
check "Torso (location_index ohne edges) loest den Neuaufbau aus" "$r" "ja"
[ -e "$D1/location_index" ] && r=liegt_noch || r=weg
check "der fremde location_index wird weggeraeumt" "$r" "weg"
[ -e "$D1/gh.lock" ] && r=liegt_noch || r=weg
check "die verwaiste gh.lock wird weggeraeumt" "$r" "weg"
check "der Fingerprint steht danach wieder da" "$(cat "$D1/.graph_fingerprint")" "$FP"

# ── Fall 2: vollstaendiger Graph, Fingerprint passt — nichts anfassen ───────
# Regressionsschutz: Diese Pruefung laeuft bei JEDEM Start. Wuerde sie hier
# anspringen, baute jede Installation ihren Graphen bei jedem Neustart neu.
D2="$TMP/vollstaendig"; mkdir -p "$D2"
for f in edges nodes geometry location_index properties; do printf 'x' > "$D2/$f"; done
printf '%s' "$FP" > "$D2/.graph_fingerprint"
check "vollstaendiger Graph wird nicht neu gebaut" "$(run_block "$D2")" "KEINER"
[ -e "$D2/edges" ] && r=da || r=weg
check "vollstaendiger Graph bleibt unangetastet" "$r" "da"

# ── Fall 3: leeres Verzeichnis (Erststart) ──────────────────────────────────
D3="$TMP/leer"; mkdir -p "$D3"
check "leeres Verzeichnis ist kein Neuaufbau, sondern ein Erstbau" "$(run_block "$D3")" "KEINER"
check "der Erstbau hinterlaesst den Fingerprint" "$(cat "$D3/.graph_fingerprint")" "$FP"

# ── Fall 4: Regionswechsel — bestehendes Verhalten bleibt ───────────────────
D4="$TMP/andere_region"; mkdir -p "$D4"
printf 'x' > "$D4/edges"
printf '%s' "berlin-latest.osm.pbf|car_access" > "$D4/.graph_fingerprint"
grund="$(run_block "$D4")"
case "$grund" in
    *Kartenregion*) r=ja ;;
    *)              r="nein ($grund)" ;;
esac
check "geaenderter Fingerprint schlaegt weiter durch (und nicht der neue Zweig)" "$r" "ja"

# ── Fall 5: frisch geladene OSM-Datei — bestehendes Verhalten bleibt ───────
D5="$TMP/neu_geladen"; mkdir -p "$D5"
printf 'x' > "$D5/edges"
printf '%s' "$FP" > "$D5/.graph_fingerprint"
grund="$(run_block "$D5" 1)"
case "$grund" in
    *"Neue OSM-Daten"*) r=ja ;;
    *)                  r="nein ($grund)" ;;
esac
check "frisch geladene OSM-Datei schlaegt weiter durch" "$r" "ja"

# ── Fall 6: der Wipe laesst die Regionswechsel-Verzeichnisse stehen ────────
# switch-region.sh baut den neuen Graphen in $GRAPH_DIR/.staging und legt den
# alten nach $GRAPH_DIR/.old. Beide beginnen mit einem Punkt, und `rm -rf
# "$GRAPH_DIR"/*` fasst Punktdateien in der POSIX-Shell nicht an — darauf
# verlaesst sich switch-region.sh ausdruecklich (siehe Kommentar dort um
# Zeile 770). Wer den Wipe auf `find -delete` oder dotglob umstellt, loescht
# einem laufenden Regionswechsel den halb gebauten Graphen unter den Fuessen.
D6="$TMP/mit_staging"; mkdir -p "$D6/.staging" "$D6/.old"
printf 'x' > "$D6/location_index"
printf 'NEU' > "$D6/.staging/edges"
printf 'ALT' > "$D6/.old/edges"
printf '%s' "$FP" > "$D6/.graph_fingerprint"
run_block "$D6" >/dev/null
check ".staging bleibt beim Wipe erhalten" "$(cat "$D6/.staging/edges" 2>/dev/null)" "NEU"
check ".old bleibt beim Wipe erhalten"     "$(cat "$D6/.old/edges" 2>/dev/null)"     "ALT"

exit $FAILED
