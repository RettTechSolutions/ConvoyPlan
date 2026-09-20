#!/usr/bin/env bash
# graphhopper/tests/test_entrypoint_start_phasen.sh
#
# Prueft, WIE graphhopper/entrypoint.sh Java startet: in zwei Phasen, wenn der
# Server einen Graphen erst bauen muss, sonst in einer — und mit welcher
# Zugriffsart und welchen JVM-Optionen jede Phase laeuft.
#
# Die Zusage, um die es geht: `-Xmx` in JAVA_OPTS bemisst den IMPORT (Graph im
# Heap, RAM_STORE), im BETRIEB liegt der Graph eingeblendet im Seitencache
# (MMAP) und die JVM bleibt klein. Wer die beiden Phasen wieder zu einer
# zusammenlegt, hat entweder einen Import per MMAP (ein Vielfaches der Zeit)
# oder einen Server, der den ganzen Graphen in den Heap laedt (das alte, teure
# Verhalten) — und beides sieht man einem gruenen /health nicht an.
#
# Der Test fuehrt den ECHTEN Entrypoint aus, mit einem falschen `java` vorn
# im PATH, das jeden Aufruf samt der in diesem Moment gueltigen Konfiguration
# festhaelt. OSM-Datei liegt bereit (kein Download), REGION_SOURCE_SCRIPT=
# /dev/null (kein .region), GH_JAR zeigt ins Leere — das falsche java oeffnet
# es nie. Dasselbe Muster wie in den Nachbartests: nichts nachbauen, das
# Original pruefen.
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

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

# Falsches java: schreibt je Aufruf eine Zeile "<unterbefehl>|<dataaccess>|
# <jvm-optionen>" nach $JAVA_LOG. Der Unterbefehl steht vor der Konfigdatei
# (letztes Argument), die Zugriffsart steht in ebendieser Datei. Ein Import
# legt `edges` an, wie der echte — daran erkennt der Entrypoint den fertigen
# Graphen. FAKE_IMPORT_RC laesst den Import scheitern.
mkdir -p "$TMP/bin"
cat > "$TMP/bin/java" <<'JAVA'
#!/bin/sh
opts=""
cmd=""
for a in "$@"; do
    case "$a" in
        -X*) opts="$opts $a" ;;
        import|server) cmd="$a" ;;
    esac
done
for a in "$@"; do conf="$a"; done
da="$(sed -n 's/^  graph.dataaccess.default_type: //p' "$conf")"
printf '%s|%s|%s\n' "$cmd" "$da" "${opts# }" >> "$JAVA_LOG"
if [ "$cmd" = "import" ]; then
    [ "${FAKE_IMPORT_RC:-0}" -eq 0 ] || exit "$FAKE_IMPORT_RC"
    graph="$(sed -n 's/^  graph.location: //p' "$conf")"
    printf 'x' > "$graph/edges"
fi
exit 0
JAVA
chmod +x "$TMP/bin/java"

# Fuehrt den echten Entrypoint aus. $1 = GH_COMMAND, $2 = Graph-Verzeichnis,
# weitere Argumente sind zusaetzliche Umgebungsvariablen (NAME=WERT).
# Ausgabe: Exit-Code des Entrypoints; das Protokoll steht in $JAVA_LOG.
run_entrypoint() {
    local cmd="$1" graph="$2"; shift 2
    mkdir -p "$TMP/osm" "$graph"
    : > "$TMP/osm/test.osm.pbf"
    : > "$JAVA_LOG"
    (
        export PATH="$TMP/bin:$PATH"
        export OSM_DIR="$TMP/osm" OSM_FILENAME="test.osm.pbf" GRAPH_DIR="$graph"
        export OSM_DOWNLOAD_URL="http://invalid.example/test.osm.pbf"
        export REGION_SOURCE_SCRIPT=/dev/null GH_JAR="$TMP/kein.jar" GH_COMMAND="$cmd"
        export JAVA_OPTS="-Xmx3g -Xms1g -XX:+UseG1GC"
        unset GH_DATAACCESS GH_SERVER_JAVA_OPTS
        for kv in "$@"; do export "${kv?}"; done
        sh "$ENTRYPOINT" >/dev/null 2>&1
        echo $?
    )
}

JAVA_LOG="$TMP/java.log"; export JAVA_LOG

# ── Fall 1: Erststart — Import im Heap, dann Server per MMAP ───────────────
rc="$(run_entrypoint server "$TMP/g1")"
check "Erststart: Entrypoint endet mit dem (falschen) Server, rc 0" "$rc" "0"
check "Erststart: zwei Java-Laeufe" "$(wc -l < "$JAVA_LOG" | tr -d ' ')" "2"
check "Erststart: erst import mit RAM_STORE und NUR JAVA_OPTS" \
    "$(sed -n 1p "$JAVA_LOG")" "import|RAM_STORE|-Xmx3g -Xms1g -XX:+UseG1GC"
check "Erststart: dann server per MMAP mit den Server-Optionen" \
    "$(sed -n 2p "$JAVA_LOG")" \
    "server|MMAP|-Xmx3g -Xms1g -XX:+UseG1GC -XX:G1PeriodicGCInterval=300000 -XX:+ExitOnOutOfMemoryError"

# ── Fall 2: Neustart mit fertigem Graphen — nur der Server, kein Import ────
rc="$(run_entrypoint server "$TMP/g1")"
check "Neustart: ein Java-Lauf" "$(wc -l < "$JAVA_LOG" | tr -d ' ')" "1"
check "Neustart: server per MMAP" "$(cut -d'|' -f1,2 "$JAVA_LOG")" "server|MMAP"

# ── Fall 3: GH_DATAACCESS=RAM_STORE stellt das alte Verhalten her ──────────
run_entrypoint server "$TMP/g1" GH_DATAACCESS=RAM_STORE >/dev/null
check "GH_DATAACCESS=RAM_STORE: Server haelt den Graphen im Heap" \
    "$(cut -d'|' -f1,2 "$JAVA_LOG")" "server|RAM_STORE"

# ── Fall 4: GH_SERVER_JAVA_OPTS ersetzt die Vorgabe, ergaenzt sie nicht ────
run_entrypoint server "$TMP/g1" "GH_SERVER_JAVA_OPTS=-XX:+UseStringDeduplication" >/dev/null
check "GH_SERVER_JAVA_OPTS ersetzt die Server-Vorgabe komplett" \
    "$(cut -d'|' -f3 "$JAVA_LOG")" "-Xmx3g -Xms1g -XX:+UseG1GC -XX:+UseStringDeduplication"

# ── Fall 5: leeres GH_SERVER_JAVA_OPTS (so reicht es docker-compose.yml
#            durch) heisst Vorgabe, nicht "keine Optionen" ──────────────────
run_entrypoint server "$TMP/g1" "GH_SERVER_JAVA_OPTS=" >/dev/null
check "leeres GH_SERVER_JAVA_OPTS: Vorgabe bleibt" \
    "$(cut -d'|' -f3 "$JAVA_LOG")" \
    "-Xmx3g -Xms1g -XX:+UseG1GC -XX:G1PeriodicGCInterval=300000 -XX:+ExitOnOutOfMemoryError"

# ── Fall 6: GH_COMMAND=import (Regionswechsel) bleibt einphasig ───────────
rc="$(run_entrypoint import "$TMP/g6")"
check "import: ein Java-Lauf" "$(wc -l < "$JAVA_LOG" | tr -d ' ')" "1"
check "import: RAM_STORE, keine Server-Optionen" \
    "$(cat "$JAVA_LOG")" "import|RAM_STORE|-Xmx3g -Xms1g -XX:+UseG1GC"

# ── Fall 7: scheitert der Import, startet kein Server ─────────────────────
# Sonst liefe ein Server gegen ein leeres Verzeichnis, importierte selbst
# (per MMAP, langsam) — und `restart: unless-stopped` bekaeme nie den
# Fehlschlag zu sehen, den es zum Neustart braucht.
rc="$(run_entrypoint server "$TMP/g7" FAKE_IMPORT_RC=3)"
check "Import-Fehler: Entrypoint endet mit Fehler" "$rc" "3"
check "Import-Fehler: kein Server-Start danach" "$(wc -l < "$JAVA_LOG" | tr -d ' ')" "1"
check "Import-Fehler: kein edges zurueckgelassen" "$([ -f "$TMP/g7/edges" ] && echo ja || echo nein)" "nein"

exit $FAILED
