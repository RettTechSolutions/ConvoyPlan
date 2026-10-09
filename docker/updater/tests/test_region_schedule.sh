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
    mkdir -p "$d/status" "$d/graph" "$d/osm"
    # Der Normalfall: fertiger Graph, kein Download.
    : > "$d/graph/.graph_fingerprint"
    : > "$d/graph/edges"
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
        REGION_GRAPH_DIR="$d/graph"
        REGION_OSM_DIR="$d/osm"
        REGION_WAIT_MARK="$d/status/region_wait_graph"
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

# ── Graph-Aufbau: ein faelliger Wechsel wartet ───────────────────────────────
# GraphHopper baut nach einem Update selbst. Ein Wechsel, der jetzt anliefe,
# importierte daneben und tauschte am Ende das Verzeichnis unter dem laufenden
# Import weg. Geplant werden darf er (das Backend lehnt nur SOFORTIGE ab), er
# laeuft aber erst, wenn Termin UND Bau durch sind.

# Import laeuft: Fingerprint ohne edges, Alter in Sekunden.
importiert() { rm -f "$1/graph/edges"; touch -d "@$(( NOW - $2 ))" "$1/graph/.graph_fingerprint"; }

echo "── Fall 9: faelliger Wechsel wartet auf laufenden Import ───────────────"
D="$(setup_case case9)"; write_request "$D" "$(( NOW - 60 ))"
importiert "$D" 600
run_hook "$D"
[ "$(cat "$D/rc")" = 1 ]; check $? "Rueckgabe 1 (Update-Check laeuft weiter)"
not_started "$D"; check $? "switch-region.sh NICHT gestartet"
[ -f "$D/status/region_request.json" ]; check $? "Anforderung liegt weiterhin bereit"
grep -q "baut aber gerade seinen Graphen" "$D/log.txt"; check $? "Grund steht im Log"
run_hook "$D"
[ "$(grep -c "baut aber gerade" "$D/log.txt")" = 1 ]; check $? "nur EINE Logzeile, nicht je Durchlauf"

echo "── Fall 10: nach dem Import laeuft der Wechsel an ──────────────────────"
: > "$D/graph/edges"
run_hook "$D"
started "$D"; check $? "switch-region.sh wurde gestartet"
[ ! -f "$D/status/region_wait_graph" ]; check $? "Wartemarke aufgeraeumt"

echo "── Fall 11: auch ein Wechsel ohne Termin wartet ────────────────────────"
# Das Backend lehnt ihn ab, aber eine Anforderung, die unmittelbar vor dem
# Import-Beginn kam, liegt trotzdem da — die Sperre sitzt deshalb auch hier.
D="$(setup_case case11)"; write_request "$D"
importiert "$D" 60
run_hook "$D"
not_started "$D"; check $? "switch-region.sh NICHT gestartet"

echo "── Fall 12: laufender Download haelt den Wechsel an ────────────────────"
D="$(setup_case case12)"; write_request "$D" "$(( NOW - 60 ))"
: > "$D/osm/dach-latest.osm.pbf.tmp"
run_hook "$D"
not_started "$D"; check $? "switch-region.sh NICHT gestartet"

echo "── Fall 13: liegengebliebener Download haelt nichts an ─────────────────"
D="$(setup_case case13)"; write_request "$D" "$(( NOW - 60 ))"
touch -d "@$(( NOW - 3600 ))" "$D/osm/dach-latest.osm.pbf.tmp"
run_hook "$D"
started "$D"; check $? "switch-region.sh wurde gestartet"

echo "── Fall 14: haengender Import haelt nichts an ──────────────────────────"
# Ueber der Frist: Dann kann ein Wechsel auf eine kleinere Region der Ausweg sein.
D="$(setup_case case14)"; write_request "$D" "$(( NOW - 60 ))"
importiert "$D" $(( 14400 + 60 ))
run_hook "$D"
started "$D"; check $? "switch-region.sh wurde gestartet"

echo "── Fall 15: Abbruch sticht den laufenden Import ────────────────────────"
# switch-region.sh raeumt dann nur auf, es importiert nichts.
D="$(setup_case case15)"; write_request "$D" "$(( NOW + 3600 ))"
importiert "$D" 60
: > "$D/status/region.cancel"
run_hook "$D"
started "$D"; check $? "switch-region.sh laeuft an und raeumt auf"

echo "── Fall 16: ohne Graph-Volume wie bisher ───────────────────────────────"
# Altinstallation ohne die Mounts: lieber wechseln als ewig warten.
D="$(setup_case case16)"; write_request "$D"
rm -rf "$D/graph" "$D/osm"
run_hook "$D"
started "$D"; check $? "switch-region.sh wurde gestartet"

echo
if [ "$FAILED" = 0 ]; then
    echo "ALLE TESTS GRUEN"
else
    echo "TESTS FEHLGESCHLAGEN"
fi
exit "$FAILED"
