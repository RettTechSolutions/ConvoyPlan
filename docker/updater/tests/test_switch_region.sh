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

REAL_MV="$(command -v mv)"

cat > "$BIN/docker" <<'EOF'
#!/usr/bin/env bash
echo "docker $*" >> "$DOCKER_CALLS"
sub="${1:-}"
case "$sub" in
  compose)
      # Momentaufnahme des Graph-Verzeichnisses zum Zeitpunkt JEDES
      # Compose-Aufrufs. Damit ist beweisbar, dass `stop graphhopper` noch vor
      # dem Tausch kommt (dann steht dort der ALTE Graph) — Critical 1.
      echo "probe edges=$(cat "$STUB_PROBE_EDGES" 2>/dev/null || echo -) staging=$([ -e "${STUB_STAGING_DIR:-/nonexistent}" ] && echo ja || echo nein)" >> "$DOCKER_CALLS"
      # Der GraphHopper-Container bekommt bei jedem erfolgreichen
      # `up --force-recreate` eine NEUE ID — nur so kann der Test pruefen, dass
      # switch-region.sh den Austausch wirklich nachweist (Wichtig 3).
      rc="${STUB_COMPOSE_RC:-0}"
      if printf '%s\n' "$@" | grep -q -- '--force-recreate'; then
          rc="${STUB_COMPOSE_UP_RC:-$rc}"
          if [ "$rc" = 0 ] && [ "${STUB_COMPOSE_UP_NOOP:-0}" != 1 ]; then
              n=$(( $(cat "$GH_CID_FILE" 2>/dev/null || echo 0) + 1 ))
              echo "$n" > "$GH_CID_FILE"
          fi
      fi
      exit "$rc" ;;
  ps)      echo "ghcid$(cat "$GH_CID_FILE" 2>/dev/null || echo 0)" ; exit 0 ;;
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
      # Fehlgeschlagenes `docker run -d`: Fehlermeldung statt Container-ID.
      # Genau der Fall, in dem die alte Fassung die Meldung als ID
      # weiterverarbeitete (Wichtig 2).
      if [ "$detached" = 1 ] && [ "${STUB_RUN_D_FAIL:-0}" = 1 ]; then
          echo "docker: Error response from daemon: no such image" >&2
          exit 125
      fi
      if [ "${STUB_UNRECOGNIZED:-0}" = 1 ] && printf '%s\n' "$@" | grep -q 'GH_COMMAND=import'; then
          echo "Unrecognized command: import" >&2
          echo "usage: java -jar graphhopper.jar {server,check}" >&2
          exit 1
      fi
      if [ "${STUB_IMPORT_FAIL:-0}" = 1 ]; then
          echo "java.lang.OutOfMemoryError: Java heap space" >&2
          exit 1
      fi
      # Laufender Import, der erst endet, wenn `docker rm -f` die Marker-Datei
      # entfernt — damit ist ein Abbruch MITTEN in Phase 3 pruefbar
      # (Wichtig 4). Der Stub setzt region.cancel selbst, so als haette der
      # Operator waehrend des Imports auf "Abbrechen" gedrueckt.
      if [ -n "${STUB_CANCEL_ON_IMPORT:-}" ]; then
          : > "$STUB_CANCEL_ON_IMPORT"
          : > "$STUB_IMPORT_HANG_FILE"
          while [ -e "$STUB_IMPORT_HANG_FILE" ]; do sleep 0.2; done
          echo "Import-Container wurde entfernt." >&2
          exit 137
      fi
      if [ -n "${STUB_STAGING_DIR:-}" ]; then
          mkdir -p "$STUB_STAGING_DIR"
          echo "NEU" > "$STUB_STAGING_DIR/edges"
          printf '%s' "neu|ev" > "$STUB_STAGING_DIR/.graph_fingerprint"
      fi
      [ "$detached" = 1 ] && echo "importcid00"
      exit 0 ;;
  rm)
      # `docker rm -f <name>` beendet den haengenden Import-Stub oben.
      [ -n "${STUB_IMPORT_HANG_FILE:-}" ] && rm -f "$STUB_IMPORT_HANG_FILE"
      exit 0 ;;
  *) exit 0 ;;
esac
EOF

# `mv`-Stub: laesst alles durch, kann aber gezielt jeden Zug AUS dem
# .old-Verzeichnis scheitern lassen — so wird pruefbar, dass der Rollback
# einen misslungenen Rücktausch meldet, statt ihn (wie frueher) mit
# Rueckgabewert 0 zu verschweigen.
cat > "$BIN/mv" <<EOF
#!/usr/bin/env bash
if [ "\${STUB_MV_FAIL_FROM_OLD:-0}" = 1 ]; then
    # Nur Zuege AUS .old heraus (Rücktausch) scheitern lassen, nicht die
    # Zuege HINEIN (der Tausch selbst) — sonst kaeme der Test gar nicht erst
    # bis zum Rollback. Das letzte Argument ist das Ziel und bleibt aussen vor.
    args=("\$@"); n=\${#args[@]}
    for (( i = 0; i < n - 1; i++ )); do
        case "\${args[\$i]}" in
            */.old/*) echo "mv: simulierter Fehler: \${args[\$i]}" >&2; exit 1 ;;
        esac
    done
fi
exec "$REAL_MV" "\$@"
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

chmod +x "$BIN/docker" "$BIN/curl" "$BIN/mv"
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
    # Reichlich Speicher: die Heap-Deckelung soll in den Bestandsfaellen nichts
    # veraendern. /proc/meminfo des Testrechners waere nicht deterministisch
    # (und existiert auf macOS gar nicht).
    printf 'MemTotal:       67108864 kB\nMemAvailable:   33554432 kB\n' > "$d/meminfo"
    echo "0" > "$d/gh_cid"
    echo "$d"
}

run_case() {  # $1 = Ablage; weitere Env kommt vom Aufrufer
    local d="$1"; shift
    env DOCKER_CALLS="$d/calls.txt" GH_CID_FILE="$d/gh_cid" \
        STATUS_DIR="$d/status" OSM_DIR="$d/osm" GRAPH_DIR="$d/graph" \
        STUB_STAGING_DIR="$d/graph/.staging" REPO_DIR="$d" \
        STUB_IMPORT_HANG_FILE="$d/import-haengt" STUB_PROBE_EDGES="$d/graph/edges" \
        REGION_MEMINFO="$d/meminfo" \
        SKIP_CHECKSUM=1 REGION_POLL_SLEEP=0 REGION_HEALTH_TIMEOUT=10 \
        "$@" bash "$SCRIPT" >"$d/out.txt" 2>&1
    echo $? > "$d/rc"
}

phase_of() { sed -nE 's/.*"phase"[[:space:]]*:[[:space:]]*"([^"]*)".*/\1/p' "$1" 2>/dev/null | head -1; }

# Folge der GraphHopper-Compose-Befehle, z. B. "stop up " im Erfolgsfall.
compose_seq() {
    grep -oE '(stop|up -d --force-recreate) graphhopper' "$1" 2>/dev/null \
        | sed -e 's/^stop graphhopper$/stop/' -e 's/^up -d --force-recreate graphhopper$/up/' \
        | tr '\n' ' '
}

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

echo "── Fall 11: GraphHopper steht still, waehrend am Graphen gearbeitet wird ─"
# Critical 1: Ohne `compose stop` laeuft der Container waehrend des Tauschs im
# Neustart-Takt weiter; sein Entrypoint sieht dann eine neue .region neben dem
# alten .graph_fingerprint und raeumt das Graph-Verzeichnis leer.
D="$(setup_case case11)"; printf '%s' "$REQ_JSON" > "$D/status/region_request.json"
run_case "$D"
[ "$(phase_of "$D/status/region_status.json")" = "done" ]; check $? "Endphase done"
[ "$(compose_seq "$D/calls.txt")" = "stop up " ]; check $? "erst stop, dann up ($(compose_seq "$D/calls.txt"))"
grep -A1 -- "stop graphhopper" "$D/calls.txt" | grep -q "probe edges=ALT"; check $? "beim stop liegt noch der ALTE Graph — gestoppt wird VOR dem Tausch"
grep -A1 -- "up -d --force-recreate graphhopper" "$D/calls.txt" | grep -q "probe edges=NEU"; check $? "beim up liegt der NEUE Graph"

echo "── Fall 12: Rollback laesst sich nicht vollstaendig ausfuehren ─────────"
# _restore_old_graph lieferte frueher IMMER 0 und prueste keinen einzigen `mv`.
# Ein halb zurueckgeschobener Graph sah damit aus wie ein gelungener Rollback.
D="$(setup_case case12)"; printf '%s' "$REQ_JSON" > "$D/status/region_request.json"
run_case "$D" STUB_HEALTH=starting STUB_MV_FAIL_FROM_OLD=1
[ "$(cat "$D/rc")" != 0 ]; check $? "Exit ungleich 0"
[ "$(phase_of "$D/status/region_status.json")" = "failed" ]; check $? "Endphase failed"
grep -q "Rücktausch von Graph und .region ist fehlgeschlagen" "$D/status/region.log"; check $? "misslungener Rücktausch wird gemeldet"
[ -d "$D/graph/.old" ]; check $? "alter Bestand bleibt fuer den manuellen Eingriff erhalten"
[ "$(cat "$D/graph/.old/edges" 2>/dev/null)" = "ALT" ]; check $? "alter Graph liegt unversehrt in .old"
[ ! -e "$D/status/region_request.json" ] && [ ! -e "$D/status/region.lock" ]; check $? "Sperrdateien entfernt"

echo "── Fall 13: Import liefert 0, hinterlaesst aber keinen Graphen ─────────"
# Wichtig 1: Ohne Nachweis liefe die Tausch-Schleife nullmal durch und liesse
# das Graph-Verzeichnis LEER zurueck — der einzige unumkehrbare Schritt.
D="$(setup_case case13)"; printf '%s' "$REQ_JSON" > "$D/status/region_request.json"
run_case "$D" STUB_STAGING_DIR=
[ "$(phase_of "$D/status/region_status.json")" = "failed" ]; check $? "Endphase failed"
grep -q "keinen Graphen hinterlassen" "$D/status/region.log"; check $? "Meldung nennt den fehlenden Graphen"
[ "$(cat "$D/graph/edges" 2>/dev/null)" = "ALT" ]; check $? "alter Graph unangetastet"
grep -q "^OSM_FILENAME=dach-latest.osm.pbf$" "$D/osm/.region"; check $? "alte .region unveraendert"
[ "$(compose_seq "$D/calls.txt")" = "" ]; check $? "GraphHopper wurde nicht angefasst"
[ ! -e "$D/graph/.old" ]; check $? "kein .old angelegt"

echo "── Fall 14: 'docker run -d' schlaegt fehl ──────────────────────────────"
# Wichtig 2: Die Fehlermeldung landete frueher als \"Container-ID\" in cid, kam
# am Leer-Guard vorbei und die Warteschleife drehte bis REGION_IMPORT_TIMEOUT.
D="$(setup_case case14)"; printf '%s' "$REQ_JSON" > "$D/status/region_request.json"
run_case "$D" REGION_IMPORT_MODE=server STUB_RUN_D_FAIL=1
[ "$(phase_of "$D/status/region_status.json")" = "failed" ]; check $? "Endphase failed"
grep -q "Import-Container ließ sich nicht starten (docker run beendet mit 125)" "$D/status/region.log"; check $? "Fehlstart wird am Exit-Code erkannt"
! grep -q "docker inspect .*Error response" "$D/calls.txt"; check $? "keine Fehlermeldung als Container-ID weiterverarbeitet"
[ "$(cat "$D/graph/edges")" = "ALT" ]; check $? "alter Graph unangetastet"
[ ! -e "$D/status/region_request.json" ] && [ ! -e "$D/status/region.lock" ]; check $? "Sperrdateien entfernt"

echo "── Fall 15: 'compose up' scheitert (alter Container laeuft weiter) ─────"
# Wichtig 3: Frueher nur geloggt — _gh_cid fand den ALTEN Container, der galt
# als gesund, Phase 5 loeschte .old und das alte Extract, das Panel meldete
# \"done\" und geroutet wurde weiter die alte Region.
D="$(setup_case case15)"; printf '%s' "$REQ_JSON" > "$D/status/region_request.json"
run_case "$D" STUB_COMPOSE_UP_RC=1
[ "$(phase_of "$D/status/region_status.json")" != "done" ]; check $? "kein 'done' trotz laufendem alten Container"
grep -q "'compose up -d --force-recreate graphhopper' ist fehlgeschlagen" "$D/status/region.log"; check $? "Fehlschlag wird als Fehler behandelt"
[ "$(cat "$D/graph/edges")" = "ALT" ]; check $? "alter Graph zurueckgeholt"
grep -q "^OSM_FILENAME=dach-latest.osm.pbf$" "$D/osm/.region"; check $? "alte .region wiederhergestellt"
[ -f "$D/osm/dach-latest.osm.pbf" ]; check $? "altes Extract nicht geloescht"

echo "── Fall 16: 'compose up' meldet Erfolg, tauscht aber nichts aus ────────"
D="$(setup_case case16)"; printf '%s' "$REQ_JSON" > "$D/status/region_request.json"
run_case "$D" STUB_COMPOSE_UP_NOOP=1
[ "$(phase_of "$D/status/region_status.json")" != "done" ]; check $? "kein 'done' ohne nachweislichen Austausch"
grep -q "hat nichts ausgetauscht" "$D/status/region.log"; check $? "unveraenderte Container-ID wird erkannt"
[ "$(cat "$D/graph/edges")" = "ALT" ]; check $? "alter Graph zurueckgeholt"
grep -q "^OSM_FILENAME=dach-latest.osm.pbf$" "$D/osm/.region"; check $? "alte .region wiederhergestellt"

echo "── Fall 17: Abbruch mitten im Import ───────────────────────────────────"
# Wichtig 4 / Spec §3: \"ein laufender Import bis zum Ende ODER Abbruch des
# Wegwerf-Containers\". Vorher wirkte ein Abbruch in Phase 3 erst Stunden
# spaeter an der naechsten Phasengrenze.
D="$(setup_case case17)"; printf '%s' "$REQ_JSON" > "$D/status/region_request.json"
run_case "$D" STUB_CANCEL_ON_IMPORT="$D/status/region.cancel"
[ "$(phase_of "$D/status/region_status.json")" = "failed" ]; check $? "Endphase failed"
grep -q "Abbruch angefordert — der Import-Container wird gestoppt" "$D/status/region.log"; check $? "Abbruch wirkt waehrend des Imports"
grep -qE "docker rm -f convoyplan-region-import-[0-9]+" "$D/calls.txt"; check $? "Import-Container wird entfernt"
grep -q "Abgebrochen — die bisherige Region läuft unverändert weiter." "$D/status/region.log"; check $? "Abbruch-Meldung statt Heap-Fehlschlag"
[ "$(cat "$D/graph/edges")" = "ALT" ]; check $? "alter Graph unangetastet"
[ "$(compose_seq "$D/calls.txt")" = "" ]; check $? "kein Schwenk stattgefunden"
[ ! -e "$D/status/region.cancel" ]; check $? "Abbruchdatei entfernt"

echo "── Fall 18: Heap wird auf den verfuegbaren Host-RAM gedeckelt ──────────"
# Spec §3: Der Updater uebernimmt den vom Backend gerechneten Heap nicht
# ungeprueft. Hier: 3 GB angefordert, 2,5 GB verfuegbar, 1 GB Reserve — bleiben
# 1,5 GB, angehoben auf das Minimum von 2 GB.
D="$(setup_case case18)"; printf '%s' "$REQ_JSON" > "$D/status/region_request.json"
printf 'MemTotal:       4194304 kB\nMemAvailable:   2621440 kB\n' > "$D/meminfo"
run_case "$D"
[ "$(phase_of "$D/status/region_status.json")" = "done" ]; check $? "Endphase done"
grep -q "^JAVA_OPTS=-Xmx2048m -XX:MaxRAMPercentage=75.0$" "$D/osm/.region"; check $? "gedeckelter Heap steht in .region ($(grep '^JAVA_OPTS=' "$D/osm/.region"))"
grep -q "JAVA_OPTS=-Xmx2048m" "$D/calls.txt"; check $? "auch der Import laeuft mit gedeckeltem Heap"
grep -q "Heap gedeckelt" "$D/status/region.log"; check $? "Deckelung wird protokolliert"

echo
[ "$FAILED" = 0 ] && echo "ALLE TESTS GRUEN" || echo "TESTS FEHLGESCHLAGEN"
exit $FAILED
