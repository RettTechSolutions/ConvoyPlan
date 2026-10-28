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
#
# Steht profiles_lm in der Konfiguration, heisst der Unterbefehl "<cmd>+lm".
# Ein Import mit LM ist die Landmark-Berechnung: sie legt landmarks_car an
# (FAKE_LM_RC laesst sie scheitern, nach einem halben landmarks_car), und der
# Eintrag sagt mit "+marke", ob .lm_vorbereitung dabei lag, und mit "+alt", ob
# schon ein landmarks_car da war.
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
graph="$(sed -n 's/^  graph.location: //p' "$conf")"
if grep -q '^  profiles_lm:' "$conf"; then
    cmd="$cmd+lm"
    if [ "$cmd" = "import+lm" ]; then
        [ -f "$graph/.lm_vorbereitung" ] && cmd="$cmd+marke"
        [ -f "$graph/landmarks_car" ] && cmd="$cmd+alt"
    fi
fi
printf '%s|%s|%s\n' "$cmd" "$da" "${opts# }" >> "$JAVA_LOG"
cp "$conf" "$JAVA_LOG.conf"
case "$cmd" in
    import+lm*)
        printf 'halb' > "$graph/landmarks_car"
        [ "${FAKE_LM_RC:-0}" -eq 0 ] || exit "$FAKE_LM_RC"
        printf 'x' > "$graph/landmarks_car"
        ;;
    import)
        [ "${FAKE_IMPORT_RC:-0}" -eq 0 ] || exit "$FAKE_IMPORT_RC"
        printf 'x' > "$graph/edges"
        ;;
esac
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
        unset GH_DATAACCESS GH_SERVER_JAVA_OPTS GH_IMPORT_JAVA_OPTS GH_LM
        for kv in "$@"; do export "${kv?}"; done
        sh "$ENTRYPOINT" >/dev/null 2>&1
        echo $?
    )
}

JAVA_LOG="$TMP/java.log"; export JAVA_LOG

# ── Fall 1: Erststart — Import im Heap, Landmarks im Heap, Server per MMAP ─
rc="$(run_entrypoint server "$TMP/g1")"
check "Erststart: Entrypoint endet mit dem (falschen) Server, rc 0" "$rc" "0"
check "Erststart: drei Java-Laeufe" "$(wc -l < "$JAVA_LOG" | tr -d ' ')" "3"
check "Erststart: erst import OHNE Landmarks, mit RAM_STORE, JAVA_OPTS und der Heap-Messung" \
    "$(sed -n 1p "$JAVA_LOG")" "import|RAM_STORE|-Xmx3g -Xms1g -XX:+UseG1GC -Xlog:gc+heap+exit"
check "Erststart: dann die Landmarks als eigener Lauf, ebenso im Heap, mit Marke" \
    "$(sed -n 2p "$JAVA_LOG")" "import+lm+marke|RAM_STORE|-Xmx3g -Xms1g -XX:+UseG1GC -Xlog:gc+heap+exit"
check "Erststart: dann server mit Landmarks per MMAP mit den Server-Optionen" \
    "$(sed -n 3p "$JAVA_LOG")" \
    "server+lm|MMAP|-Xmx3g -Xms1g -XX:+UseG1GC -XX:G1PeriodicGCInterval=300000 -XX:+ExitOnOutOfMemoryError"
check "Erststart: Marke nach der Berechnung weg" \
    "$([ -f "$TMP/g1/.lm_vorbereitung" ] && echo da || echo weg)" "weg"
check "Erststart: Landmarks nur fuer car" \
    "$(sed -n '/^  profiles_lm:/,/^server:/p' "$JAVA_LOG.conf" | grep -c 'profile: ')" "1"

# ── Fall 1b: jedes Profil beachtet Abbiegeverbote ──────────────────────────
# Ohne turn_costs ignoriert GraphHopper OSM-Abbiegeverbote vollstaendig — an
# der B 472 bei Peissenberg fuehrte das per Haarnadel von der Auffahrt in die
# Gegenrichtung (siehe Kommentar an TURN_COSTS_VEHICLES im Entrypoint). Geprueft
# an der Konfiguration, die der Server tatsaechlich bekommen hat.
profile="$(sed -n '/^  profiles:/,/^server:/p' "$JAVA_LOG.conf")"
check "Erststart: zwei Profile (car, truck)" \
    "$(echo "$profile" | grep -c '^    - name: ')" "2"
check "Erststart: jedes Profil hat turn_costs fuer motorcar und motor_vehicle" \
    "$(echo "$profile" | grep -c '^        vehicle_types: \[motorcar, motor_vehicle\]$')" "2"

# ── Fall 1c: keine Contraction Hierarchies ─────────────────────────────────
# Mit turn_costs waere CH fuer car kantenbasiert — die mit Abstand teuerste
# Phase des Imports an Speicher und Zeit. Genutzt haette sie nur „schnell"
# ohne Fahrzeughoehe; alles andere schickt ein Custom Model und damit
# ch.disable (backend/app/services/routing.py). Siehe Kommentar im Entrypoint.
check "Erststart: keine CH-Profile in der Konfiguration" \
    "$(grep -c 'profiles_ch' "$JAVA_LOG.conf")" "0"

# ── Fall 2: Neustart mit fertigem Graphen — nur der Server, kein Import ────
rc="$(run_entrypoint server "$TMP/g1")"
check "Neustart: ein Java-Lauf" "$(wc -l < "$JAVA_LOG" | tr -d ' ')" "1"
check "Neustart: server mit Landmarks per MMAP" "$(cut -d'|' -f1,2 "$JAVA_LOG")" "server+lm|MMAP"

# ── Fall 3: GH_DATAACCESS=RAM_STORE stellt das alte Verhalten her ──────────
run_entrypoint server "$TMP/g1" GH_DATAACCESS=RAM_STORE >/dev/null
check "GH_DATAACCESS=RAM_STORE: Server haelt den Graphen im Heap" \
    "$(cut -d'|' -f1,2 "$JAVA_LOG")" "server+lm|RAM_STORE"

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

# ── Fall 6: GH_COMMAND=import (Regionswechsel) rechnet die Landmarks mit ──
# Nach dem Tausch wartet switch-region.sh nur REGION_HEALTH_TIMEOUT auf einen
# gesunden Server; rechnete erst der die Landmarks, liefe ein grosser Graph in
# diese Frist und der Wechsel wuerde zurueckgerollt.
rc="$(run_entrypoint import "$TMP/g6")"
check "import: rc 0" "$rc" "0"
check "import: Import, dann Landmarks, beides im Heap mit Heap-Messung" \
    "$(cat "$JAVA_LOG" | tr '\n' ' ')" \
    "import|RAM_STORE|-Xmx3g -Xms1g -XX:+UseG1GC -Xlog:gc+heap+exit import+lm+marke|RAM_STORE|-Xmx3g -Xms1g -XX:+UseG1GC -Xlog:gc+heap+exit "
check "import: Landmarks liegen danach" "$([ -f "$TMP/g6/landmarks_car" ] && echo ja || echo nein)" "ja"

# ── Fall 6b: die Heap-Messung gehoert nur dem Import ───────────────────────
# Der Server liefe sonst Tage und schriebe sie erst beim Herunterfahren — ins
# Container-Log, das dann niemand mehr liest.
run_entrypoint server "$TMP/g1" >/dev/null
check "Server: keine Heap-Messung" \
    "$(grep -c 'Xlog' "$JAVA_LOG" | tr -d ' ')" "0"

# ── Fall 7: scheitert der Import, startet kein Server ─────────────────────
# Sonst liefe ein Server gegen ein leeres Verzeichnis, importierte selbst
# (per MMAP, langsam) — und `restart: unless-stopped` bekaeme nie den
# Fehlschlag zu sehen, den es zum Neustart braucht.
rc="$(run_entrypoint server "$TMP/g7" FAKE_IMPORT_RC=3)"
check "Import-Fehler: Entrypoint endet mit Fehler" "$rc" "3"
check "Import-Fehler: kein Server-Start danach" "$(wc -l < "$JAVA_LOG" | tr -d ' ')" "1"
check "Import-Fehler: kein edges zurueckgelassen" "$([ -f "$TMP/g7/edges" ] && echo ja || echo nein)" "nein"

# Ein fertiger Graph von vor LM: Fingerprint und edges, keine Landmarks.
bestand() { run_entrypoint server "$1" GH_LM=false >/dev/null; }

# ── Fall 8: Bestand ohne Landmarks — nachgerechnet, nicht neu importiert ───
# Das ist das Update jeder bestehenden Installation: der Graph bleibt, nur die
# Landmarks kommen dazu.
bestand "$TMP/g8"
rc="$(run_entrypoint server "$TMP/g8")"
check "Bestand: kein OSM-Import, nur Landmarks, dann Server mit LM" \
    "$(cut -d'|' -f1,2 "$JAVA_LOG" | tr '\n' ' ')" "import+lm+marke|RAM_STORE server+lm|MMAP "

# ── Fall 9: abgebrochene Berechnung wird verworfen und wiederholt ──────────
bestand "$TMP/g9"
printf 'halb' > "$TMP/g9/landmarks_car"; : > "$TMP/g9/.lm_vorbereitung"
rc="$(run_entrypoint server "$TMP/g9")"
check "abgebrochen: halbes landmarks_car weg, bevor neu gerechnet wird" \
    "$(cut -d'|' -f1 "$JAVA_LOG" | tr '\n' ' ')" "import+lm+marke server+lm "
check "abgebrochen: danach vollstaendig" "$(cat "$TMP/g9/landmarks_car")" "x"

# ── Fall 10: scheitert die Berechnung, laeuft der Server ohne LM ───────────
# Ohne LM ist die Lage wie vor LM; ein Container, der deshalb im Kreis
# neu startete, haette gar kein Routing.
bestand "$TMP/g10"
rc="$(run_entrypoint server "$TMP/g10" FAKE_LM_RC=1)"
check "LM-Fehler: Entrypoint endet mit dem Server, rc 0" "$rc" "0"
check "LM-Fehler: Server ohne Landmarks" \
    "$(cut -d'|' -f1 "$JAVA_LOG" | tr '\n' ' ')" "import+lm+marke server "
check "LM-Fehler: kein halbes landmarks_car, keine Marke" \
    "$(ls -A "$TMP/g10" | grep -cE '^(landmarks_car|\.lm_vorbereitung)$')" "0"
rc="$(run_entrypoint server "$TMP/g10")"
check "LM-Fehler: kein zweiter Versuch fuer denselben Graphen" \
    "$(cut -d'|' -f1 "$JAVA_LOG" | tr '\n' ' ')" "server "
# Auch nicht mit anderen JAVA_OPTS: der Import-Container eines Regionswechsels
# laeuft mit anderen als der Server danach, und dessen Versuch fiele in die
# Gesundheitsfrist von switch-region.sh.
rc="$(run_entrypoint server "$TMP/g10" "JAVA_OPTS=-Xmx6g")"
check "LM-Fehler: auch mit anderen JAVA_OPTS kein Versuch" \
    "$(cut -d'|' -f1 "$JAVA_LOG" | tr '\n' ' ')" "server "
rm -f "$TMP/g10/.lm_gescheitert"
rc="$(run_entrypoint server "$TMP/g10")"
check "LM-Fehler: Vermerk geloescht, neuer Versuch" \
    "$(cut -d'|' -f1 "$JAVA_LOG" | tr '\n' ' ')" "import+lm+marke server+lm "

# ── Fall 10b: Regionswechsel — gescheitert im Import-Container, kein Versuch
#             im Server danach ────────────────────────────────────────────────
rc="$(run_entrypoint import "$TMP/g10b" FAKE_LM_RC=1 "JAVA_OPTS=-Xmx9g")"
check "Wechsel: Import gelingt trotz LM-Fehler (rc 0)" "$rc" "0"
rc="$(run_entrypoint server "$TMP/g10b")"
check "Wechsel: Server danach startet ohne neuen LM-Versuch" \
    "$(cut -d'|' -f1 "$JAVA_LOG" | tr '\n' ' ')" "server "

# ── Fall 11: GH_LM=false — keine Landmarks, nirgends ───────────────────────
rc="$(run_entrypoint server "$TMP/g11" GH_LM=false)"
check "GH_LM=false: Import und Server, kein LM-Lauf" \
    "$(cut -d'|' -f1 "$JAVA_LOG" | tr '\n' ' ')" "import server "
check "GH_LM=false: Server-Konfiguration ohne profiles_lm" \
    "$(grep -c 'profiles_lm' "$JAVA_LOG.conf")" "0"

exit $FAILED
