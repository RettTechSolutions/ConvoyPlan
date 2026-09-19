#!/usr/bin/env bash
# docker/updater/tests/test_graphhopper_import_deploy.sh
#
# Prueft die Zusage aus docker/updater/graphhopper-deploy.sh: Ein Deploy fasst
# den graphhopper-Dienst NICHT an, solange dort ein Graph-Import laeuft — und
# zieht ihn nach, sobald der Import durch ist.
#
# Anlass ist der Ausfall vom 2026-09-19: Ein Auto-Deploy (nightly, mehrmals
# taeglich) traf einen laufenden Import und liess einen Torso im Volume zurueck,
# an dem GraphHopper danach in einer Crash-Schleife hing.
#
# Zwei Ebenen, aus demselben Grund getrennt wie die Bildentscheidung in
# .github/actions/build-or-reuse (decide.sh vs. Registry-Abfrage):
#
#   Teil 1 — die ENTSCHEIDUNG, ohne Docker-Daemon. Die Funktionen werden direkt
#            gesourct, `docker` ist ein PATH-Stub. Laeuft immer.
#   Teil 2 — die VERDRAHTUNG in update-images.sh, also der Teil, der still
#            falsch wird, wenn jemand die Deploy-Liste anfasst. Braucht einen
#            Daemon, weil das echte Skript reale Root-Pfade hart-kodiert (siehe
#            test_update_lock_precedence.sh) — ohne Daemon wird uebersprungen.
set -uo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
UPDATER_DIR="$(cd "$HERE/.." && pwd)"
FAILED=0

ok()    { echo "ok   — $1"; }
bad()   { echo "FAIL — $1"; FAILED=1; }
check() { if [ "$1" = 0 ]; then ok "$2"; else bad "$2"; fi; }
eq()    { if [ "$2" = "$3" ]; then ok "$1"; else echo "FAIL — $1: erwartet '$3', bekam '$2'"; FAILED=1; fi; }

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
# Teil 1 legt einen docker-Stub in den PATH. Der Originalpfad wird gemerkt und
# vor Teil 2 zurueckgesetzt: mit dem Stub im PATH antwortete `docker info`
# freundlich mit 0 und `docker run` tat gar nichts — Teil 2 lief dann leer durch
# und galt als bestanden, ohne eine einzige Zusicherung zu pruefen.
PATH_OHNE_STUB="$PATH"

echo "── Teil 1: die Entscheidung (ohne Docker-Daemon) ───────────────────────"

BIN="$TMP/bin"; mkdir -p "$BIN"
# docker-Stub: meldet einen laufenden graphhopper-Container, wenn
# STUB_GH_RUNNING gesetzt ist. Alles andere bleibt leer.
cat > "$BIN/docker" <<'STUB'
#!/usr/bin/env bash
if [ "${1:-}" = "ps" ] && printf '%s\n' "$@" | grep -q 'service=graphhopper'; then
    [ -n "${STUB_GH_RUNNING:-}" ] && echo "ghcid000000"
fi
exit 0
STUB
chmod +x "$BIN/docker"
export PATH="$BIN:$PATH"

GRAPH="$TMP/graph"
DEFER="$TMP/graphhopper_deferred"
LOGF="$TMP/log.txt"

# Laedt die echten Funktionen in eine Subshell und fuehrt darin `$1` aus.
# log() und gh_deploy_graphhopper() sind die beiden Voraussetzungen, die der
# Kopf von graphhopper-deploy.sh nennt — hier als Protokoll-Attrappen.
mit_funktionen() {
    ( set -uo pipefail
      : > "$LOGF"
      log() { echo "$*" >> "$LOGF"; }
      gh_deploy_graphhopper() {
          echo "DEPLOY" >> "$LOGF"
          [ -z "${STUB_DEPLOY_FAILS:-}" ]
      }
      COMPOSE_PROJECT=convoyplan
      GRAPH_DIR="$GRAPH" GH_DEFER_FILE="$DEFER" GH_IMPORT_GRACE="${GH_IMPORT_GRACE:-14400}"
      # shellcheck source=/dev/null
      . "$UPDATER_DIR/graphhopper-deploy.sh"
      eval "$1" )
}

ALLE="backend frontend caddy graphhopper db retention"

# Fall 1: Import laeuft — graphhopper raus, Marke gesetzt
rm -rf "$GRAPH" "$DEFER"; mkdir -p "$GRAPH"
out="$(STUB_GH_RUNNING=1 mit_funktionen '_plan_deploy_services "$ALLE"; echo "$DEPLOY_SERVICES"')"
eq "laufender Import: graphhopper faellt aus der Deploy-Liste" "$out" "backend frontend caddy db retention "
[ -s "$DEFER" ]; check $? "laufender Import: Marke fuer das Nachziehen wird gesetzt"
grep -q "baut gerade den Routing-Graphen" "$LOGF"; check $? "laufender Import: der Grund steht im Log"

# Fall 2: fertiger Graph — nichts wird herausgenommen, Marke verschwindet
printf 'x' > "$GRAPH/edges"
out="$(STUB_GH_RUNNING=1 mit_funktionen '_plan_deploy_services "$ALLE"; echo "$DEPLOY_SERVICES"')"
eq "fertiger Graph: alle Dienste werden deployt" "$out" "$ALLE"
[ ! -e "$DEFER" ]; check $? "fertiger Graph: eine alte Marke wird aufgeraeumt"

# Fall 3: Container gestoppt — ein gestoppter Container baut nichts
rm -f "$GRAPH/edges" "$DEFER"
out="$(mit_funktionen '_plan_deploy_services "$ALLE"; echo "$DEPLOY_SERVICES"')"
eq "gestoppter Container: alle Dienste werden deployt" "$out" "$ALLE"
[ ! -e "$DEFER" ]; check $? "gestoppter Container: keine Marke"

# Fall 4: Graph-Volume hier nicht gemountet — Altinstallation, kein Rueckschluss
# aus einer Datei, die gar nicht sichtbar ist.
rm -rf "$GRAPH"
out="$(STUB_GH_RUNNING=1 mit_funktionen '_plan_deploy_services "$ALLE"; echo "$DEPLOY_SERVICES"')"
eq "ohne Graph-Volume bleibt es beim bisherigen Verhalten" "$out" "$ALLE"

# Fall 5: Geduldsfrist abgelaufen — sonst schnitte ein Container, der aus einem
# anderen Grund nie ein `edges` schreibt, den Dienst dauerhaft von Updates ab.
mkdir -p "$GRAPH"
echo "$(( $(date +%s) - 20000 ))" > "$DEFER"
out="$(STUB_GH_RUNNING=1 GH_IMPORT_GRACE=14400 mit_funktionen '_plan_deploy_services "$ALLE"; echo "$DEPLOY_SERVICES"')"
eq "abgelaufene Geduldsfrist: graphhopper wird trotzdem getauscht" "$out" "$ALLE"
[ ! -e "$DEFER" ]; check $? "abgelaufene Geduldsfrist: Marke wird aufgeraeumt"
grep -q "Geduldsfrist abgelaufen" "$LOGF"; check $? "abgelaufene Geduldsfrist: steht im Log"

# Fall 6: Nachziehen, sobald der Graph fertig ist
printf 'x' > "$GRAPH/edges"
echo "$(date +%s)" > "$DEFER"
out="$(STUB_GH_RUNNING=1 mit_funktionen '_deploy_deferred_graphhopper'; cat "$LOGF")"
grep -q "DEPLOY" "$LOGF"; check $? "fertiger Graph: der zurueckgestellte Deploy wird nachgeholt"
[ ! -e "$DEFER" ]; check $? "nachgeholt: Marke wird entfernt"

# Fall 7: noch im Import — nicht nachziehen
rm -f "$GRAPH/edges"; echo "$(date +%s)" > "$DEFER"
STUB_GH_RUNNING=1 mit_funktionen '_deploy_deferred_graphhopper'
! grep -q "DEPLOY" "$LOGF"; check $? "noch im Import: es wird NICHT nachgezogen"
[ -s "$DEFER" ]; check $? "noch im Import: Marke bleibt liegen"

# Fall 8: keine Marke — nichts zu tun (und keine Logzeile je Zyklus)
rm -f "$DEFER"; printf 'x' > "$GRAPH/edges"
STUB_GH_RUNNING=1 mit_funktionen '_deploy_deferred_graphhopper'
[ ! -s "$LOGF" ]; check $? "ohne Marke bleibt der Zyklus stumm"

# Fall 9: Nachziehen scheitert — Marke bleibt, damit es erneut versucht wird
echo "$(date +%s)" > "$DEFER"
STUB_DEPLOY_FAILS=1 STUB_GH_RUNNING=1 mit_funktionen '_deploy_deferred_graphhopper'
[ -s "$DEFER" ]; check $? "fehlgeschlagenes Nachziehen: Marke bleibt fuer den naechsten Zyklus"
grep -q "WARNUNG" "$LOGF"; check $? "fehlgeschlagenes Nachziehen: Warnung im Log"

echo
echo "── Teil 2: die Verdrahtung in update-images.sh ─────────────────────────"

export PATH="$PATH_OHNE_STUB"
if ! docker info >/dev/null 2>&1; then
    echo "SKIP — Docker-Daemon nicht erreichbar, Teil 2 uebersprungen."
    exit $FAILED
fi

# -i ist zwingend: ohne offenes stdin liest `bash -s` das Here-Document gar
# nicht und der Container endet sofort mit 0 — der Test galt dann als
# bestanden, ohne eine einzige Zusicherung geprueft zu haben.
docker run --rm \
    -v "${UPDATER_DIR}/region-hook.sh:/region-hook.sh:ro" \
    -v "${UPDATER_DIR}/graphhopper-deploy.sh:/graphhopper-deploy.sh:ro" \
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
exit 1
EOF

# docker-Stub: protokolliert, meldet `config --services` und unterscheidet beim
# `ps` nach Dienst — sonst waere der graphhopper-Container von dem des Backends
# nicht zu trennen und die Import-Erkennung liefe ins Leere.
cat > "$BIN/docker" <<'EOF'
#!/usr/bin/env bash
echo "docker $*" >> "$DOCKER_CALLS"
case "${1:-}" in
  compose)
      sub=""
      for a in "$@"; do case "$a" in version|config|pull|up) sub="$a" ;; esac; done
      case "$sub" in
        config) printf 'backend\nfrontend\ncaddy\ngraphhopper\ndb\nupdater\n' ;;
      esac
      exit 0 ;;
  ps)
      if printf '%s\n' "$@" | grep -q 'service=graphhopper'; then
          [ -n "${STUB_GH_RUNNING:-}" ] && echo "ghcid000000"
      else
          echo "backendcid00"
      fi
      exit 0 ;;
  image) echo "sha256:fakeimageid"; exit 0 ;;
  inspect)
      fmt=""; prev=""
      for a in "$@"; do [ "$prev" = "--format" ] && fmt="$a"; prev="$a"; done
      case "$fmt" in
        *Health*)       echo "healthy" ;;
        *RestartCount*) echo "0" ;;
        *State.Status*) echo "running" ;;
        *.Image*)       echo "sha256:fakebackendimage" ;;
        *GIT_SHA*|*Config.Env*) echo "GIT_SHA=1111111111111111111111111111111111111111" ;;
      esac
      exit 0 ;;
  *) exit 0 ;;
esac
EOF
chmod +x "$BIN"/*
export PATH="$BIN:$PATH"

export STACK_FILE_PATH=/stack/docker-compose.yml
export DOCKER_CALLS=/update_status/docker_calls.txt
# Ohne das griffe die Signaturpruefung nach cosign, das es hier nicht gibt —
# do_update() brach dann VOR dem Deploy ab und der Test prueefte nichts.
export UPDATE_VERIFY_SIGNATURES=false
export STUB_GH_RUNNING=1

starte_updater() {
    rm -rf /update_status /stack; mkdir -p /update_status /stack
    echo "services: {}" > /stack/docker-compose.yml
    "$@"   # Vorbereitung des Zustands, nachdem /update_status frisch ist
    bash /update-images.sh > /update_status/stdout.log 2>&1 &
    pid=$!
    sleep 8
    kill "$pid" 2>/dev/null; wait "$pid" 2>/dev/null
}

echo "── Fall A: Import laeuft, Trigger gesetzt ──────────────────────────────"
# /data/graph existiert, aber ohne `edges` → GraphHopper baut.
mkdir -p /data/graph; rm -f /data/graph/edges
starte_updater bash -c ': > /update_status/trigger'

grep -q "baut gerade den Routing-Graphen" /update_status/update.log 2>/dev/null
check $? "das Log nennt den zurueckgestellten Dienst"
grep -E "compose.*pull" "$DOCKER_CALLS" | grep -q graphhopper
check $? "gezogen wird graphhopper trotzdem (Pull fasst keinen Container an)"
grep -E "compose.*up -d --no-build" "$DOCKER_CALLS" | grep -q backend
check $? "die uebrigen Dienste werden deployt"
! grep -E "compose.*up -d --no-build" "$DOCKER_CALLS" | grep -q graphhopper
check $? "graphhopper wird NICHT getauscht, solange er baut"
[ -s /update_status/graphhopper_deferred ]
check $? "die Marke fuers Nachziehen liegt im geteilten Volume"

echo "── Fall B: Graph fertig, Marke liegt vor ───────────────────────────────"
starte_updater bash -c 'printf x > /data/graph/edges; date +%s > /update_status/graphhopper_deferred'

grep -q "nachgeholt" /update_status/update.log 2>/dev/null
check $? "der zurueckgestellte Deploy wird nachgeholt"
grep -E "compose.*up -d --no-build graphhopper" "$DOCKER_CALLS" >/dev/null
check $? "und zwar genau fuer graphhopper"
[ ! -e /update_status/graphhopper_deferred ]
check $? "die Marke ist danach weg"

echo
[ "$FAILED" = 0 ] && echo "ALLE TESTS GRUEN" || echo "TESTS FEHLGESCHLAGEN"
exit "$FAILED"
INNER
rc=$?
[ "$rc" = 0 ] || FAILED=1
exit $FAILED
