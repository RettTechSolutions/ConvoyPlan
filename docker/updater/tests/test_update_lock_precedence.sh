#!/usr/bin/env bash
# Test fuer docker/updater/update.sh UND docker/updater/update-images.sh:
# Ein aktives region.lock muss die reguläre Update-Ausführung blockieren —
# auch wenn zeitgleich /update_status/trigger gesetzt ist ("Jetzt updaten").
#
# Deckt den Fehler ab, dass der Trigger-Zweig in update-images.sh region.lock
# gar nicht prüfte und per `continue` in do_update() sprang, BEVOR der
# Regionswechsel-Block erreicht wurde — ein manueller Trigger konnte so
# während eines laufenden Regionswechsels denselben Compose-Stack anfassen.
#
# Beide Updater-Skripte hart-kodieren reale Root-Pfade (/update_status,
# /stack, /workspace) — anders als switch-region.sh (STATUS_DIR-Override,
# siehe test_switch_region.sh) lassen sie sich nicht einfach mit einem
# Temp-Verzeichnis umleiten. Der Test läuft deshalb, genau wie die Skripte
# selbst in Produktion, in einem Linux-Container mit echtem Root-Dateisystem.
# docker/git/curl sind darin durch Stubs ersetzt, die Aufrufe nur protokollieren
# statt sie auszuführen — derselbe Ansatz wie in test_switch_region.sh.
set -uo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
UPDATER_DIR="$(cd "$HERE/.." && pwd)"

if ! docker info >/dev/null 2>&1; then
    echo "SKIP — Docker-Daemon nicht erreichbar, Test übersprungen."
    exit 0
fi

docker run --rm \
    -v "${UPDATER_DIR}/region-hook.sh:/region-hook.sh:ro" \
    -v "${UPDATER_DIR}/update.sh:/update.sh:ro" \
    -v "${UPDATER_DIR}/update-images.sh:/update-images.sh:ro" \
    bash:5.2 bash -s <<'INNER'
set -uo pipefail
FAILED=0
ok()   { echo "ok   — $1"; }
bad()  { echo "FAIL — $1"; FAILED=1; }
check(){ if [ "$1" = 0 ]; then ok "$2"; else bad "$2"; fi; }

BIN=/stubbin; mkdir -p "$BIN"

# ── Stubs: protokollieren statt ausführen ────────────────────────────────────
cat > "$BIN/git" <<'EOF'
#!/usr/bin/env bash
echo "git $*" >> "$GIT_CALLS"
case "${1:-}" in
  -C)
      sub="${3:-}"
      case "$sub" in
        rev-parse) echo "1111111111111111111111111111111111111111" ;;
      esac
      exit 0 ;;
  *) exit 0 ;;
esac
EOF

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

chmod +x "$BIN"/*
export PATH="$BIN:$PATH"

echo "── Fall 1: update.sh — Trigger und Lock gleichzeitig gesetzt ───────────"
mkdir -p /update_status /workspace/.git
: > /update_status/trigger
: > /update_status/region.lock
export GIT_CALLS=/update_status/git_calls.txt
export DOCKER_CALLS=/update_status/docker_calls.txt
export CURL_CALLS=/update_status/curl_calls.txt
export GITHUB_TOKEN=dummy
bash /update.sh >/update_status/stdout.log 2>&1 &
pid=$!
sleep 3
kill "$pid" 2>/dev/null; wait "$pid" 2>/dev/null

grep -q "Regionswechsel-Lock aktiv" /update_status/update.log 2>/dev/null
check $? "update.sh: Lock-Meldung im update.log"
[ ! -s /update_status/docker_calls.txt ]
check $? "update.sh: kein einziger docker-Aufruf (kein Update ausgefuehrt)"

echo "── Fall 2: update-images.sh — Trigger und Lock gleichzeitig gesetzt ────"
rm -rf /update_status
mkdir -p /update_status /stack
echo "services: {}" > /stack/docker-compose.yml
: > /update_status/trigger
: > /update_status/region.lock
export STACK_FILE_PATH=/stack/docker-compose.yml
export GIT_CALLS=/update_status/git_calls.txt
export DOCKER_CALLS=/update_status/docker_calls.txt
export CURL_CALLS=/update_status/curl_calls.txt
bash /update-images.sh >/update_status/stdout.log 2>&1 &
pid=$!
sleep 8
kill "$pid" 2>/dev/null; wait "$pid" 2>/dev/null

grep -q "Regionswechsel-Lock aktiv" /update_status/update.log 2>/dev/null
check $? "update-images.sh: Lock-Meldung im update.log"
! grep -qE "compose.*(pull|up -d --no-build)" /update_status/docker_calls.txt 2>/dev/null
check $? "update-images.sh: kein Update-Deploy trotz Trigger (Lock respektiert)"
[ -f /update_status/trigger ]
check $? "update-images.sh: Trigger-Anforderung bleibt erhalten (nicht stillschweigend verworfen)"

echo
[ "$FAILED" = 0 ] && echo "ALLE TESTS GRUEN" || echo "TESTS FEHLGESCHLAGEN"
exit "$FAILED"
INNER
exit $?
