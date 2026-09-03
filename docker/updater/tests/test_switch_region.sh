#!/usr/bin/env bash
# Test fuer docker/updater/switch-region.sh — ohne laufenden Docker-Daemon.
#
# Ein `docker`- und ein `curl`-Stub im PATH protokollieren Aufrufe, statt sie
# auszufuehren. Damit sind Phasenreihenfolge, Rollback-Pfad und das Aufraeumen
# der Sperrdateien pruefbar. Die Stubs sind ueber STUB_*-Variablen steuerbar,
# sodass jeder Fehlerfall gezielt ausgeloest werden kann.
set -uo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
SCRIPT="$HERE/../switch-region.sh"
FAILED=0
ROOT="$(mktemp -d)"; trap 'rm -rf "$ROOT"' EXIT

ok()   { echo "ok   — $1"; }
bad()  { echo "FAIL — $1"; FAILED=1; }
check(){ if [ "$1" = 0 ]; then ok "$2"; else bad "$2"; fi; }

# ── Stubs ───────────────────────────────────────────────────────────────────
BIN="$ROOT/bin"; mkdir -p "$BIN"

cat > "$BIN/docker" <<'EOF'
#!/usr/bin/env bash
echo "docker $*" >> "$DOCKER_CALLS"
sub="${1:-}"
case "$sub" in
  compose) exit "${STUB_COMPOSE_RC:-0}" ;;
  ps)      echo "ghcid0000" ; exit 0 ;;
  inspect)
      fmt=""; prev=""
      for a in "$@"; do [ "$prev" = "--format" ] && fmt="$a"; prev="$a"; done
      case "$fmt" in
        *Health*)       echo "${STUB_HEALTH:-healthy}" ;;
        *RestartCount*) echo "${STUB_RESTARTS:-0}" ;;
        *State.Status*) echo "running" ;;
        *Mounts*)       echo "${STUB_VOLUME:-}" ;;
        *)              echo "" ;;
      esac
      exit 0 ;;
  run)
      detached=0
      for a in "$@"; do [ "$a" = "-d" ] && detached=1; done
      if [ "${STUB_UNRECOGNIZED:-0}" = 1 ] && printf '%s\n' "$@" | grep -q 'GH_COMMAND=import'; then
          echo "Unrecognized command: import" >&2
          echo "usage: java -jar graphhopper.jar {server,check}" >&2
          exit 1
      fi
      if [ "${STUB_IMPORT_FAIL:-0}" = 1 ]; then
          echo "java.lang.OutOfMemoryError: Java heap space" >&2
          exit 1
      fi
      if [ -n "${STUB_STAGING_DIR:-}" ]; then
          mkdir -p "$STUB_STAGING_DIR"
          echo "NEU" > "$STUB_STAGING_DIR/edges"
          printf '%s' "neu|ev" > "$STUB_STAGING_DIR/.graph_fingerprint"
      fi
      [ "$detached" = 1 ] && echo "importcid00"
      exit 0 ;;
  *) exit 0 ;;
esac
EOF

cat > "$BIN/curl" <<'EOF'
#!/usr/bin/env bash
out=""; prev=""
for a in "$@"; do [ "$prev" = "-o" ] && out="$a"; prev="$a"; done
if [ -n "$out" ]; then
    echo "dummy-inhalt" > "$out"
    exit "${STUB_CURL_DL_RC:-0}"
fi
echo "HTTP/1.1 200 OK"
echo "Content-Length: ${STUB_SIZE:-1000}"
exit "${STUB_CURL_HEAD_RC:-0}"
EOF

chmod +x "$BIN/docker" "$BIN/curl"
export PATH="$BIN:$PATH"

REQ_JSON='{"url": "https://download.geofabrik.de/europe/germany/berlin-latest.osm.pbf", "filename": "berlin-latest.osm.pbf", "java_opts": "-Xmx3g -XX:MaxRAMPercentage=75.0", "requested_by": "a@b.c", "requested_at": "2026-09-03T10:00:00+00:00"}'

# Legt eine frische Ablage an und gibt ihr Wurzelverzeichnis aus.
setup_case() {
    local name="$1"
    local d="$ROOT/$name"
    mkdir -p "$d/status" "$d/osm" "$d/graph"
    # Bestehender Graph der ALTEN Region — muss jeden Fehlschlag ueberleben.
    echo "ALT" > "$d/graph/edges"
    printf '%s' "dach-latest.osm.pbf|ev" > "$d/graph/.graph_fingerprint"
    printf 'OSM_DOWNLOAD_URL=%s\nOSM_FILENAME=%s\nJAVA_OPTS=%s\n' \
        "https://download.geofabrik.de/europe/dach-latest.osm.pbf" \
        "dach-latest.osm.pbf" "-Xmx8g" > "$d/osm/.region"
    : > "$d/osm/dach-latest.osm.pbf"
    # Compose-Datei, damit das Skript einen Stack findet (nur Existenz zaehlt —
    # `docker` ist gestubbt).
    echo "services: {}" > "$d/docker-compose.yml"
    echo "$d"
}

run_case() {  # $1 = Ablage; weitere Env kommt vom Aufrufer
    local d="$1"; shift
    env DOCKER_CALLS="$d/calls.txt" \
        STATUS_DIR="$d/status" OSM_DIR="$d/osm" GRAPH_DIR="$d/graph" \
        STUB_STAGING_DIR="$d/graph/.staging" REPO_DIR="$d" \
        SKIP_CHECKSUM=1 REGION_POLL_SLEEP=0 REGION_HEALTH_TIMEOUT=10 \
        "$@" bash "$SCRIPT" >"$d/out.txt" 2>&1
    echo $? > "$d/rc"
}

phase_of() { sed -nE 's/.*"phase"[[:space:]]*:[[:space:]]*"([^"]*)".*/\1/p' "$1" 2>/dev/null | head -1; }

echo "── Fall 1: Erfolgspfad ─────────────────────────────────────────────────"
D="$(setup_case case1)"; printf '%s' "$REQ_JSON" > "$D/status/region_request.json"
run_case "$D"
[ "$(cat "$D/rc")" = 0 ]; check $? "Exit 0"
[ "$(phase_of "$D/status/region_status.json")" = "done" ]; check $? "Endphase done"
grep -q -- "-p convoyplan" "$D/calls.txt"; check $? "compose mit -p Projektname"
grep -qE "docker compose .* -f [^ ]+ .*up -d --force-recreate graphhopper" "$D/calls.txt"; check $? "Schwenk ruft compose up mit -f"
[ -f "$D/osm/.region" ]; check $? ".region geschrieben"
grep -q "^JAVA_OPTS=-Xmx3g -XX:MaxRAMPercentage=75.0$" "$D/osm/.region"; check $? "Heap wandert mit (Leerzeichen und = im Wert)"
grep -q "^OSM_FILENAME=berlin-latest.osm.pbf$" "$D/osm/.region"; check $? "Dateiname in .region"
grep -q "^OSM_DOWNLOAD_URL=https://download.geofabrik.de/europe/germany/berlin-latest.osm.pbf$" "$D/osm/.region"; check $? "URL in .region"
[ "$(wc -l < "$D/osm/.region" | tr -d ' ')" = 3 ]; check $? ".region hat genau drei Zeilen"
[ "$(cat "$D/graph/edges" 2>/dev/null)" = "NEU" ]; check $? "neuer Graph ist aktiv"
[ ! -e "$D/graph/.staging" ] && [ ! -e "$D/graph/.old" ]; check $? "Staging und alter Graph aufgeraeumt"
[ ! -e "$D/osm/dach-latest.osm.pbf" ]; check $? "altes Extract geloescht"
[ -f "$D/osm/berlin-latest.osm.pbf" ]; check $? "neues Extract vorhanden"
[ ! -e "$D/status/region_request.json" ] && [ ! -e "$D/status/region.lock" ]; check $? "Sperrdateien entfernt"
grep -q "REGION_SOURCE_SCRIPT=/dev/null" "$D/calls.txt"; check $? "Import ignoriert die alte .region"
grep -q "OSM_FILENAME=berlin-latest.osm.pbf" "$D/calls.txt"; check $? "Import bekommt die neue Region"
grep -q "GRAPH_DIR=/data/graph/.staging" "$D/calls.txt"; check $? "Import baut ins Staging-Verzeichnis"
# Phasenreihenfolge im Log
ORDER="$(grep -oE 'Phase [1-5]/5' "$D/status/region.log" | tr '\n' ' ')"
[ "$ORDER" = "Phase 1/5 Phase 2/5 Phase 3/5 Phase 4/5 Phase 5/5 " ]; check $? "Phasenreihenfolge stimmt ($ORDER)"
grep -q "Regionswechsel abgeschlossen: berlin-latest.osm.pbf" "$D/status/region.log"; check $? "Abschlussmeldung im Log"

echo "── Fall 2: Fehlschlag in Phase 3 (Graph-Bau) ───────────────────────────"
D="$(setup_case case2)"; printf '%s' "$REQ_JSON" > "$D/status/region_request.json"
run_case "$D" STUB_IMPORT_FAIL=1
[ "$(cat "$D/rc")" != 0 ]; check $? "Exit ungleich 0"
[ "$(phase_of "$D/status/region_status.json")" = "failed" ]; check $? "Endphase failed"
[ "$(cat "$D/graph/edges")" = "ALT" ]; check $? "alter Graph unangetastet"
grep -q "^OSM_FILENAME=dach-latest.osm.pbf$" "$D/osm/.region"; check $? "alte .region unveraendert"
[ ! -e "$D/graph/.staging" ]; check $? "Staging aufgeraeumt"
[ ! -e "$D/status/region_request.json" ] && [ ! -e "$D/status/region.lock" ]; check $? "Sperrdateien entfernt"
! grep -q "up -d --force-recreate graphhopper" "$D/calls.txt"; check $? "kein Schwenk stattgefunden"

echo "── Fall 3: Rollback (neuer Graph wird nicht gesund) ────────────────────"
D="$(setup_case case3)"; printf '%s' "$REQ_JSON" > "$D/status/region_request.json"
run_case "$D" STUB_HEALTH=starting
[ "$(cat "$D/rc")" != 0 ]; check $? "Exit ungleich 0"
[ "$(phase_of "$D/status/region_status.json")" = "failed" ]; check $? "Endphase failed"
[ "$(cat "$D/graph/edges")" = "ALT" ]; check $? "alter Graph zurueckgeholt"
grep -q "^OSM_FILENAME=dach-latest.osm.pbf$" "$D/osm/.region"; check $? "alte .region wiederhergestellt"
[ "$(grep -c "up -d --force-recreate graphhopper" "$D/calls.txt")" = 2 ]; check $? "zweimal geschwenkt (hin und zurueck)"
[ ! -e "$D/graph/.old" ] && [ ! -e "$D/graph/.staging" ]; check $? "keine Reste im Graph-Volume"
[ ! -e "$D/status/region_request.json" ] && [ ! -e "$D/status/region.lock" ]; check $? "Sperrdateien entfernt"

echo "── Fall 4: URL nicht auf der Allowlist ─────────────────────────────────"
D="$(setup_case case4)"
printf '%s' '{"url": "https://evil.example.com/europe/berlin-latest.osm.pbf", "filename": "berlin-latest.osm.pbf", "java_opts": "-Xmx3g", "requested_by": "a@b.c"}' > "$D/status/region_request.json"
run_case "$D"
[ "$(phase_of "$D/status/region_status.json")" = "failed" ]; check $? "Endphase failed"
[ ! -e "$D/status/region_request.json" ] && [ ! -e "$D/status/region.lock" ]; check $? "Sperrdateien entfernt"
[ ! -e "$D/osm/berlin-latest.osm.pbf" ]; check $? "nichts heruntergeladen"
[ "$(cat "$D/graph/edges")" = "ALT" ]; check $? "alter Graph unangetastet"

echo "── Fall 5: keine Anforderung ───────────────────────────────────────────"
D="$(setup_case case5)"; : > "$D/status/region.lock"
run_case "$D"
[ "$(cat "$D/rc")" = 0 ]; check $? "Exit 0"
[ -f "$D/status/region.lock" ]; check $? "fremdes Lock nicht angefasst"
[ ! -e "$D/status/region_status.json" ]; check $? "kein Status geschrieben"

echo "── Fall 6: Abbruch durch den Nutzer ────────────────────────────────────"
D="$(setup_case case6)"; printf '%s' "$REQ_JSON" > "$D/status/region_request.json"
: > "$D/status/region.cancel"
run_case "$D"
[ "$(phase_of "$D/status/region_status.json")" = "failed" ]; check $? "Endphase failed"
[ "$(cat "$D/graph/edges")" = "ALT" ]; check $? "alter Graph unangetastet"
[ ! -e "$D/status/region.cancel" ]; check $? "Abbruchdatei entfernt"
[ ! -e "$D/status/region_request.json" ] && [ ! -e "$D/status/region.lock" ]; check $? "Sperrdateien entfernt"

echo "── Fall 7: 'import' unbekannt → Rückfall auf 'server' ──────────────────"
D="$(setup_case case7)"; printf '%s' "$REQ_JSON" > "$D/status/region_request.json"
run_case "$D" STUB_UNRECOGNIZED=1
[ "$(phase_of "$D/status/region_status.json")" = "done" ]; check $? "Endphase done"
grep -q "GH_COMMAND=server" "$D/calls.txt"; check $? "Rückfall startet den Server-Weg"
[ "$(cat "$D/graph/edges")" = "NEU" ]; check $? "neuer Graph ist aktiv"

echo "── Fall 8: Download schlaegt fehl ──────────────────────────────────────"
D="$(setup_case case8)"; printf '%s' "$REQ_JSON" > "$D/status/region_request.json"
run_case "$D" STUB_CURL_DL_RC=7
[ "$(phase_of "$D/status/region_status.json")" = "failed" ]; check $? "Endphase failed"
[ ! -e "$D/osm/berlin-latest.osm.pbf" ]; check $? "kein halbes Extract zurueckgelassen"
[ "$(cat "$D/graph/edges")" = "ALT" ]; check $? "alter Graph unangetastet"
[ ! -e "$D/status/region_request.json" ] && [ ! -e "$D/status/region.lock" ]; check $? "Sperrdateien entfernt"

echo "── Fall 9: zu wenig Plattenplatz ───────────────────────────────────────"
D="$(setup_case case9)"; printf '%s' "$REQ_JSON" > "$D/status/region_request.json"
run_case "$D" STUB_SIZE=999999999999999
[ "$(phase_of "$D/status/region_status.json")" = "failed" ]; check $? "Endphase failed"
grep -q "Plattenplatz" "$D/status/region.log"; check $? "Meldung nennt den Plattenplatz"
[ ! -e "$D/status/region_request.json" ] && [ ! -e "$D/status/region.lock" ]; check $? "Sperrdateien entfernt"

echo "── Fall 10: JAVA_OPTS mit Zeilenumbruch wird abgelehnt ─────────────────"
D="$(setup_case case10)"
printf '%s' '{"url": "https://download.geofabrik.de/europe/germany/berlin-latest.osm.pbf", "filename": "berlin-latest.osm.pbf", "java_opts": "-Xmx3g\nOSM_FILENAME=boese.pbf", "requested_by": "a@b.c"}' > "$D/status/region_request.json"
run_case "$D"
[ "$(phase_of "$D/status/region_status.json")" = "failed" ]; check $? "Endphase failed"
grep -q "^OSM_FILENAME=dach-latest.osm.pbf$" "$D/osm/.region"; check $? ".region nicht manipuliert"

echo
[ "$FAILED" = 0 ] && echo "ALLE TESTS GRUEN" || echo "TESTS FEHLGESCHLAGEN"
exit $FAILED
