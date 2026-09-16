#!/usr/bin/env bash
# Test fuer die Terminierung in docker/updater/region-hook.sh.
#
# Der Hook entscheidet, OB switch-region.sh anlaeuft — die Terminierung sitzt
# genau dort. Anders als test_update_lock_precedence.sh braucht dieser Test
# keinen Docker-Daemon: Die Pfade im Hook sind ueberschreibbar, und
# switch-region.sh wird durch einen Stub ersetzt, der nur seinen Aufruf
# protokolliert. Damit ist die Zeitlogik in Sekunden pruefbar statt in Minuten.
set -uo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
HOOK="$HERE/../region-hook.sh"
FAILED=0
ROOT="$(mktemp -d)"; trap 'rm -rf "$ROOT"' EXIT

ok()   { echo "ok   — $1"; }
bad()  { echo "FAIL — $1"; FAILED=1; }
check(){ if [ "$1" = 0 ]; then ok "$2"; else bad "$2"; fi; }

# Der Hook setzt `log()` als gegeben voraus (beide Updater-Skripte definieren
# sie vor dem `source`). Hier schreibt sie in eine Datei, damit der Test die
# Meldungen pruefen kann.
log() { echo "$*" >> "$LOG_FILE"; }

# Legt eine frische Ablage an: Statusverzeichnis, Stub, leere Protokolle.
setup_case() {
    # Getrennte `local`-Anweisungen: In einer einzigen wuerde "$ROOT/$name"
    # expandiert, bevor `name` zugewiesen ist.
    local name="$1"
    local d="$ROOT/$name"
    mkdir -p "$d/status"
    cat > "$d/switch-stub.sh" <<'STUB'
#!/usr/bin/env bash
echo "gestartet" >> "$SWITCH_CALLS"
exit "${STUB_SWITCH_RC:-0}"
STUB
    chmod +x "$d/switch-stub.sh"
    : > "$d/switch_calls.txt"
    : > "$d/log.txt"
    echo "$d"
}

# Laedt den Hook mit den Pfaden dieser Ablage und ruft ihn einmal auf.
# Der Hook wird je Fall neu eingelesen, damit die ueberschriebenen Pfade
# wirklich greifen (die Variablen sind `${VAR:-default}`, also klebrig).
run_hook() {
    local d="$1"
    (
        export SWITCH_CALLS="$d/switch_calls.txt"
        LOG_FILE="$d/log.txt"
        REGION_STATUS_DIR="$d/status"
        REGION_REQUEST_FILE="$d/status/region_request.json"
        REGION_LOCK_FILE="$d/status/region.lock"
        REGION_CANCEL_FILE="$d/status/region.cancel"
        SWITCH_REGION_SCRIPT="$d/switch-stub.sh"
        # shellcheck source=/dev/null
        . "$HOOK"
        run_region_switch_if_requested
        echo $? > "$d/rc"
    )
}

started()     { [ -s "$1/switch_calls.txt" ]; }
not_started() { [ ! -s "$1/switch_calls.txt" ]; }

# Eine Anforderung mit optionalem Termin (Epoch-Sekunden als String, so wie das
# Backend sie schreibt).
write_request() {
    local d="$1"
    local due="${2:-}"
    if [ -n "$due" ]; then
        printf '{"url": "https://download.geofabrik.de/europe/germany/berlin-latest.osm.pbf", "filename": "berlin-latest.osm.pbf", "java_opts": "-Xmx3g", "pause_routing": "1", "scheduled_for": "2099-01-01T03:00:00+00:00", "scheduled_for_epoch": "%s", "requested_by": "a@b.c"}' \
            "$due" > "$d/status/region_request.json"
    else
        printf '{"url": "https://download.geofabrik.de/europe/germany/berlin-latest.osm.pbf", "filename": "berlin-latest.osm.pbf", "java_opts": "-Xmx3g", "requested_by": "a@b.c"}' \
            > "$d/status/region_request.json"
    fi
}

NOW="$(date -u +%s)"

echo "── Fall 1: Anforderung ohne Termin laeuft sofort ───────────────────────"
# Der Normalfall — er darf sich durch die Terminierung nicht veraendert haben.
D="$(setup_case case1)"; write_request "$D"
run_hook "$D"
[ "$(cat "$D/rc")" = 0 ]; check $? "Rueckgabe 0 (Aufrufer springt in die naechste Runde)"
started "$D"; check $? "switch-region.sh wurde gestartet"

echo "── Fall 2: Termin in der Zukunft — Anforderung bleibt liegen ───────────"
D="$(setup_case case2)"; write_request "$D" "$(( NOW + 3600 ))"
run_hook "$D"
[ "$(cat "$D/rc")" = 1 ]; check $? "Rueckgabe 1 (Aufrufer macht mit dem Update-Check weiter)"
not_started "$D"; check $? "switch-region.sh NICHT gestartet"
[ -f "$D/status/region_request.json" ]; check $? "Anforderung liegt weiterhin bereit"
[ ! -s "$D/log.txt" ]; check $? "keine Logzeile je Durchlauf — sonst ersaeuft region.log"

echo "── Fall 3: Termin erreicht — Anforderung laeuft an ─────────────────────"
D="$(setup_case case3)"; write_request "$D" "$(( NOW - 1 ))"
run_hook "$D"
[ "$(cat "$D/rc")" = 0 ]; check $? "Rueckgabe 0"
started "$D"; check $? "switch-region.sh wurde gestartet"

echo "── Fall 4: genau jetzt faellig laeuft an (>=, nicht >) ─────────────────"
# Die Grenze selbst: Ein auf 03:00 gelegter Wechsel muss um 03:00 laufen, nicht
# erst in der Sekunde danach.
D="$(setup_case case4)"; write_request "$D" "$(date -u +%s)"
run_hook "$D"
started "$D"; check $? "switch-region.sh wurde gestartet"

echo "── Fall 5: Abbruch sticht den Termin ───────────────────────────────────"
# Wird ein geplanter Wechsel abbestellt, muss switch-region.sh trotzdem
# anlaufen: Nur dort wird die Anforderung aufgeraeumt und dem Panel als
# abgebrochen gemeldet. Ohne das laege sie bis zu ihrem Termin da und ginge
# dann trotzdem los.
D="$(setup_case case5)"; write_request "$D" "$(( NOW + 3600 ))"
: > "$D/status/region.cancel"
run_hook "$D"
[ "$(cat "$D/rc")" = 0 ]; check $? "Rueckgabe 0"
started "$D"; check $? "switch-region.sh laeuft an und raeumt auf"

echo "── Fall 6: laufender Wechsel wird nicht doppelt gestartet ──────────────"
D="$(setup_case case6)"; write_request "$D"
: > "$D/status/region.lock"
run_hook "$D"
[ "$(cat "$D/rc")" = 1 ]; check $? "Rueckgabe 1"
not_started "$D"; check $? "switch-region.sh NICHT gestartet"

echo "── Fall 7: unlesbarer Termin laeuft nicht ins Blaue ────────────────────"
# Steht dort Unsinn, greift der Regex nicht und die Anforderung gilt als
# unterminiert — sie laeuft sofort. Das ist die bewusste Wahl: Ein Wechsel, den
# jemand angefordert hat, soll stattfinden; verloren ginge sonst nur, dass er
# spaeter stattfindet.
D="$(setup_case case7)"
printf '{"url": "https://download.geofabrik.de/europe/germany/berlin-latest.osm.pbf", "filename": "berlin-latest.osm.pbf", "java_opts": "-Xmx3g", "scheduled_for_epoch": "bald", "requested_by": "a@b.c"}' \
    > "$D/status/region_request.json"
run_hook "$D"
started "$D"; check $? "switch-region.sh wurde gestartet"

echo "── Fall 8: keine Anforderung, nichts passiert ──────────────────────────"
D="$(setup_case case8)"
run_hook "$D"
[ "$(cat "$D/rc")" = 1 ]; check $? "Rueckgabe 1"
not_started "$D"; check $? "switch-region.sh NICHT gestartet"

echo
if [ "$FAILED" = 0 ]; then
    echo "ALLE TESTS GRUEN"
else
    echo "TESTS FEHLGESCHLAGEN"
fi
exit "$FAILED"
