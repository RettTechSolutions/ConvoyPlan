#!/usr/bin/env bash
# Test fuer die Signaturpruefung in docker/updater/update-images.sh.
#
# Der Updater haelt den nackten Docker-Socket: was er zieht und startet, laeuft
# als root auf dem Host. Die Pruefung, ob ein Image wirklich aus einem Workflow
# dieses Repositories stammt, ist damit die letzte Tuer vor genau diesem
# Zugriff. Ein Fehler, der sie still ueberspringt, ist unsichtbar — hier wird
# er sichtbar.
#
# Geprueft werden vier Faelle:
#   1. gueltige Signatur   → es wird gezogen
#   2. ungueltige Signatur → es wird NICHT gezogen, Alarm-Datei liegt vor
#   3. Pruefung aus        → cosign wird gar nicht erst aufgerufen
#   4. cosign fehlt        → NICHT gezogen (kein stiller Fallback)
#
# update-images.sh hart-kodiert reale Root-Pfade (/update_status, /stack), laesst
# sich also nicht mit einem Temp-Verzeichnis umleiten. Der Test laeuft deshalb,
# genau wie das Skript in Produktion, in einem Linux-Container mit echtem
# Root-Dateisystem; docker/curl/cosign sind darin durch Stubs ersetzt, die
# Aufrufe nur protokollieren. Gleicher Ansatz wie
# test_update_lock_precedence.sh.
set -uo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
UPDATER_DIR="$(cd "$HERE/.." && pwd)"

if ! docker info >/dev/null 2>&1; then
    echo "SKIP — Docker-Daemon nicht erreichbar, Test übersprungen."
    exit 0
fi

# -i ist zwingend: ohne offenes stdin liest `bash -s` das Here-Document gar
# nicht und der Container endet sofort mit 0 — der Test galt dann als
# bestanden, ohne eine einzige Zusicherung geprueft zu haben.
docker run --rm \
    -v "${UPDATER_DIR}/region-hook.sh:/region-hook.sh:ro" \
    -v "${UPDATER_DIR}/update-images.sh:/update-images.sh:ro" \
    -i bash:5.2 bash -s <<'INNER'
set -uo pipefail
FAILED=0
ok()   { echo "ok   — $1"; }
bad()  { echo "FAIL — $1"; FAILED=1; }
check(){ if [ "$1" = 0 ]; then ok "$2"; else bad "$2"; fi; }

BIN=/stubbin; mkdir -p "$BIN"

cat > "$BIN/curl" <<'EOF'
#!/usr/bin/env bash
echo "curl $*" >> "$CURL_CALLS" 2>/dev/null
exit 1
EOF

cat > "$BIN/docker" <<'EOF'
#!/usr/bin/env bash
echo "docker $*" >> "$DOCKER_CALLS"
case "${1:-}" in
  compose)
      shift
      sub=""
      for a in "$@"; do
          case "$a" in version|config|pull|up) sub="$a" ;; esac
      done
      case "$sub" in
        config) printf 'backend\nfrontend\ncaddy\ngraphhopper\ndb\nupdater\n' ;;
      esac
      exit 0 ;;
  ps)    echo "backendcid00"; exit 0 ;;
  image) echo "sha256:fakeimageid"; exit 0 ;;
  inspect)
      fmt=""; prev=""
      for a in "$@"; do [ "$prev" = "--format" ] && fmt="$a"; prev="$a"; done
      case "$fmt" in
        *Health*)       echo "healthy" ;;
        *RestartCount*) echo "0" ;;
        *State.Status*) echo "running" ;;
        *.Image*)       echo "sha256:fakebackendimage" ;;
      esac
      exit 0 ;;
  *) exit 0 ;;
esac
EOF

# cosign-Stub: protokolliert und liefert den in COSIGN_EXIT verlangten Code.
cat > "$BIN/cosign" <<'EOF'
#!/usr/bin/env bash
echo "cosign $*" >> "$COSIGN_CALLS"
exit "${COSIGN_EXIT:-0}"
EOF

chmod +x "$BIN"/*
export PATH="$BIN:$PATH"

# Einen Trigger-Durchlauf von update-images.sh fahren und wieder abraeumen.
run_updater() {
    rm -rf /update_status /stack
    mkdir -p /update_status /stack
    echo "services: {}" > /stack/docker-compose.yml
    : > /update_status/trigger
    export STACK_FILE_PATH=/stack/docker-compose.yml
    export DOCKER_CALLS=/update_status/docker_calls.txt
    export CURL_CALLS=/update_status/curl_calls.txt
    export COSIGN_CALLS=/update_status/cosign_calls.txt
    : > "$DOCKER_CALLS"; : > "$CURL_CALLS"; : > "$COSIGN_CALLS"
    bash /update-images.sh >/update_status/stdout.log 2>&1 &
    local pid=$!
    sleep 8
    kill "$pid" 2>/dev/null; wait "$pid" 2>/dev/null
}

pulled() { grep -qE "compose.*pull" /update_status/docker_calls.txt 2>/dev/null; }

echo "── Fall 1: gueltige Signatur ──────────────────────────────────────────"
export UPDATE_VERIFY_SIGNATURES=true
export COSIGN_EXIT=0
run_updater

grep -q "Signatur ok:" /update_status/update.log
check $? "Fall 1: jede Signatur wird als gueltig protokolliert"
grep -c "^cosign verify" /update_status/cosign_calls.txt | grep -qx 5
check $? "Fall 1: alle fuenf Images werden geprueft"
grep -q -- "--certificate-oidc-issuer https://token.actions.githubusercontent.com" \
    /update_status/cosign_calls.txt
check $? "Fall 1: der erwartete OIDC-Aussteller wird verlangt"
pulled
check $? "Fall 1: das Update wird ausgefuehrt"
[ ! -f /update_status/deploy_alert.json ]
check $? "Fall 1: kein Alarm"

echo "── Fall 2: ungueltige Signatur ────────────────────────────────────────"
export UPDATE_VERIFY_SIGNATURES=true
export COSIGN_EXIT=1
run_updater

grep -q "Update abgebrochen" /update_status/update.log
check $? "Fall 2: der Abbruch steht im Log"
! pulled
check $? "Fall 2: NICHTS wird gezogen — die Installation bleibt auf dem alten Stand"
grep -q '"event":"image_signature_invalid"' /update_status/deploy_alert.json 2>/dev/null
check $? "Fall 2: Alarm-Datei fuer die Superadmin-Mail liegt vor"

echo "── Fall 3: Pruefung abgeschaltet (Air-Gapped) ─────────────────────────"
export UPDATE_VERIFY_SIGNATURES=false
export COSIGN_EXIT=1   # wuerde fehlschlagen, darf aber nie aufgerufen werden
run_updater

grep -q "Signaturpruefung abgeschaltet" /update_status/update.log
check $? "Fall 3: die Abschaltung wird protokolliert, nicht verschwiegen"
[ ! -s /update_status/cosign_calls.txt ]
check $? "Fall 3: cosign wird gar nicht erst aufgerufen"
pulled
check $? "Fall 3: das Update laeuft trotzdem durch"

echo "── Fall 4: cosign fehlt, Pruefung aber an ─────────────────────────────"
export UPDATE_VERIFY_SIGNATURES=true
export COSIGN_EXIT=0
mv "$BIN/cosign" "$BIN/cosign.disabled"
run_updater
mv "$BIN/cosign.disabled" "$BIN/cosign"

grep -q "cosign nicht im Updater-Image gefunden" /update_status/update.log
check $? "Fall 4: das fehlende Werkzeug wird benannt"
! pulled
check $? "Fall 4: kein stiller Fallback auf ungeprueftes Ziehen"
grep -q '"event":"image_signature_invalid"' /update_status/deploy_alert.json 2>/dev/null
check $? "Fall 4: Alarm-Datei liegt vor"

echo
[ "$FAILED" = 0 ] && echo "ALLE TESTS GRUEN" || echo "TESTS FEHLGESCHLAGEN"
exit "$FAILED"
INNER
exit $?
