#!/usr/bin/env bash
# Prueft die Schlafschleife von docker/updater/update.sh.
#
# Hintergrund: Der Updater schlaeft zwischen zwei Ziel-Checks bis zu INTERVAL
# (Betriebs-Default 300 s) und wachte frueh nur fuer den manuellen
# Update-Trigger auf. Eine Regionsanforderung lag deshalb bis zu fuenf Minuten
# unbearbeitet im Volume — und weil es fuer sie noch keinen Status gab, sah der
# Operator im Panel nicht, dass ueberhaupt etwas laeuft.
#
# Der heikle Teil des Fixes ist nicht das Aufwachen, sondern der RUECKGABEWERT:
# Die Aufrufer behandeln 0 als "manueller Update-Trigger" und leeren daraufhin
# DEPLOYED, was ein erneutes Deployment erzwingt — bei tag-basierten Kanaelen
# sogar ein bewusstes Downgrade. Ein Regionswechsel darf das nicht ausloesen,
# also meldet er 2.
#
# Der Test schneidet die ECHTE Funktion aus update.sh heraus und fuehrt sie
# aus, statt sie nachzubauen — ein Nachbau pruefte nur die Kopie.
set -uo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
UPDATE_SH="$HERE/../update.sh"
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

FN="$TMP/fn.sh"
sed -n '/^wait_or_trigger() {/,/^}/p' "$UPDATE_SH" > "$FN"
# Nur pruefen, dass ueberhaupt eine vollstaendige Funktion herausgeschnitten
# wurde. Bewusst KEIN grep auf den Inhalt: Sonst schluege bei einer Regression
# diese Strukturpruefung an statt der Verhaltenspruefung weiter unten, und die
# Meldung sagte "nicht geschnitten" statt "weckt nicht auf".
if ! grep -q '^wait_or_trigger() {' "$FN" || ! grep -q '^}' "$FN"; then
    echo "FAIL — wait_or_trigger nicht vollstaendig aus update.sh geschnitten"
    exit 1
fi

# Laeuft die Funktion in einer Subshell und gibt "<rc>|<Schlafrunden>".
#
# `sleep` ist hier eine Shell-Funktion und ueberdeckt das Programm: Der Test
# zaehlt damit RUNDEN statt Sekunden. Das ist nicht nur schneller, sondern der
# einzige Weg zu einer verlaesslichen Aussage — eine Zeitmessung waere auf
# einem ausgelasteten CI-Runner flaky, und ein flaky Test, der "weckt frueh"
# behauptet, ist schlimmer als keiner.
run_fn() {  # $1, $2 = Dateien, die vorab angelegt werden (leer = keine)
    ( set +e
      export TRIGGER_FILE="$TMP/trigger" REGION_REQUEST_FILE="$TMP/region_request.json"
      rm -f "$TRIGGER_FILE" "$REGION_REQUEST_FILE"
      [ -n "${1:-}" ] && : > "$1"
      [ -n "${2:-}" ] && : > "$2"
      INTERVAL=6
      TRIGGER_POLL=1
      runden=0
      sleep() { runden=$((runden + 1)); }
      # shellcheck source=/dev/null
      . "$FN"
      wait_or_trigger
      rc=$?
      echo "${rc}|${runden}" )
}

# ── Fall 1: nichts liegt an -> volles Intervall, Rueckgabewert 1 ────────────
r="$(run_fn)"
check "ohne Anlass laeuft das Intervall ab" "${r%%|*}" "1"
check "und zwar ueber alle sechs Runden" "${r##*|}" "6"

# ── Fall 2: Update-Trigger -> 0, frueh ─────────────────────────────────────
r="$(run_fn "$TMP/trigger")"
check "Update-Trigger meldet 0" "${r%%|*}" "0"
check "Update-Trigger weckt nach der ersten Runde" "${r##*|}" "1"

# ── Fall 3: Regionsanforderung -> 2, frueh ─────────────────────────────────
# Der eigentliche Fix. Die 2 ist kein Schoenheitsfehler: Mit 0 leerten die
# Aufrufer DEPLOYED und stiessen ein ungewolltes Re-Deployment an.
r="$(run_fn "" "$TMP/region_request.json")"
check "Regionsanforderung meldet 2, nicht 0" "${r%%|*}" "2"
check "Regionsanforderung weckt nach der ersten Runde" "${r##*|}" "1"

# ── Fall 4: beides gleichzeitig -> der Update-Trigger gewinnt ──────────────
# Er wird zuerst geprueft; die Schleife dreht sich danach ohnehin weiter und
# greift die Anforderung im naechsten Durchlauf auf.
r="$(run_fn "$TMP/trigger" "$TMP/region_request.json")"
check "bei beidem gewinnt der Update-Trigger" "${r%%|*}" "0"

exit $FAILED
