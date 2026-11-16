#!/usr/bin/env bash
# Prueft den Schritt `paths` im Job `changes` von ci.yml: welche Pruefungen und
# welche Image-Scans ein Lauf bekommt.
#
# Warum es diesen Test gibt: Seit der Container-Scan nur noch die Images baut,
# deren Kontext sich geaendert hat, entscheidet dieser Schritt darueber, ob ein
# Image ueberhaupt gescannt wird. Ein Fehler hier faellt nicht auf — der
# Pflicht-Check "Docker – Build check" wird gruen, weil nichts zu bauen war.
# Deshalb zweiseitig: was gescannt werden muss, und was nicht.
#
# Der Schritt wird aus ci.yml herausgeschnitten, nicht nachgebaut, und in einem
# Wegwerf-Repo mit echtem `git diff` ausgefuehrt.
set -uo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
CI_YML="$HERE/../ci.yml"
FAILED=0

ok()  { echo "ok   — $1"; }
bad() { echo "FAIL — $1"; FAILED=1; }

WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

awk '
  /^      - id: paths$/          { drin=1; next }
  drin && /^        run: \|/     { lesen=1; next }
  lesen && /^      - |^  [a-z]/  { exit }
  lesen                          { sub(/^          /, ""); print }
' "$CI_YML" > "$WORK/schritt.sh"

if [ ! -s "$WORK/schritt.sh" ]; then
    bad "Schritt 'paths' in ci.yml nicht gefunden — Test und Workflow sind auseinandergelaufen"
    exit 1
fi
ok "Schritt 'paths' aus ci.yml gelesen ($(wc -l < "$WORK/schritt.sh") Zeilen)"

REPO="$WORK/repo"
git init -q "$REPO"
git -C "$REPO" -c user.name=t -c user.email=t@t commit -q --allow-empty -m basis
BASIS="$(git -C "$REPO" rev-parse HEAD)"

# aendern <datei>…  → Commit auf der Basis, gibt die SHA aus
aendern() {
    git -C "$REPO" checkout -q "$BASIS"
    for f in "$@"; do
        mkdir -p "$REPO/$(dirname "$f")"
        echo x >> "$REPO/$f"
        git -C "$REPO" add "$f"
    done
    git -C "$REPO" -c user.name=t -c user.email=t@t commit -q -m aenderung
    git -C "$REPO" rev-parse HEAD
}

# lauf <event> <head> [schedule]  → Ausgaben in $WORK/out
lauf() {
    : > "$WORK/out"
    mkdir -p "$WORK/tmp"
    (cd "$REPO" && EVENT="$1" PR_BASE="$BASIS" PR_HEAD="$2" QUEUE_BASE="" \
        SCHEDULE="${3:-}" GITHUB_OUTPUT="$WORK/out" RUNNER_TEMP="$WORK/tmp" \
        bash "$WORK/schritt.sh" > /dev/null 2>&1)
}

wert() { sed -n "s/^$1=//p" "$WORK/out"; }

# Namen der gescannten Images, sortiert und mit Leerzeichen getrennt
images() {
    python3 -c '
import json, sys
print(" ".join(sorted(e["name"] for e in json.loads(sys.argv[1]))))
' "$(wert images)"
}

pruefe() {  # pruefe <fall> <erwartete images> [code] [medien]
    local fall="$1" soll="$2" ist
    if ! ist="$(images 2>&1)"; then
        bad "$fall: images ist kein gueltiges JSON ($(wert images))"
        return
    fi
    if [ "$ist" = "$soll" ]; then ok "$fall: gescannt '$ist'"
    else bad "$fall: gescannt '$ist', erwartet '$soll'"; fi
    if [ -n "${3:-}" ]; then
        [ "$(wert code)" = "$3" ] && ok "$fall: code=$3" || bad "$fall: code=$(wert code), erwartet $3"
    fi
    if [ -n "${4:-}" ]; then
        [ "$(wert medien)" = "$4" ] && ok "$fall: medien=$4" || bad "$fall: medien=$(wert medien), erwartet $4"
    fi
}

ALLE="backend frontend graphhopper medien osmium updater"

lauf pull_request "$(aendern docs/a.md README.md)"
pruefe "Nur Doku" "" false false

lauf pull_request "$(aendern backend/app/x.py)"
pruefe "Backend" "backend" true false

lauf pull_request "$(aendern frontend/src/x.ts wiki/y.md)"
pruefe "Frontend und Wiki" "frontend" true

lauf pull_request "$(aendern docker/medien/Dockerfile)"
pruefe "Medien" "medien" true true

lauf pull_request "$(aendern docker/updater/x.sh docker/osmium/Dockerfile graphhopper/entrypoint.sh)"
pruefe "Updater, osmium, GraphHopper" "graphhopper osmium updater"

# Nicht nur der Praefix: docker/updater-alt/ ist nicht docker/updater/.
lauf pull_request "$(aendern docker/updater-alt/x.sh backendx/y.py)"
pruefe "Aehnlich benannte Ordner" ""

lauf pull_request "$(aendern .github/workflows/ci.yml)"
pruefe "Workflow geaendert" "$ALLE"

lauf pull_request "$(aendern .trivyignore)"
pruefe ".trivyignore geaendert" "$ALLE"

lauf pull_request "$(aendern .github/actions/docker-spiegel/action.yml)"
pruefe "Docker-Spiegel geaendert" "$ALLE"

# Scheitert der Vergleich, wird alles gescannt — nie nichts.
lauf pull_request "0000000000000000000000000000000000000000"
pruefe "Vergleich gescheitert" "$ALLE" true

# Die Cron-Zeilen stehen hier wie in ci.yml; aendert sie jemand dort, muss
# dieser Fall rot werden statt still den Wochenscan abzuschalten.
WOCHE="$(awk '/^    - cron: / { gsub(/"/, ""); sub(/^    - cron: /, ""); print; exit }' "$CI_YML")"
TAG="$(awk '/^    - cron: / { n++; if (n == 2) { gsub(/"/, ""); sub(/^    - cron: /, ""); print; exit } }' "$CI_YML")"
lauf schedule "" "$WOCHE"
pruefe "Woechentlicher Lauf ($WOCHE)" "$ALLE"
lauf schedule "" "$TAG"
pruefe "Taeglicher Lauf ($TAG)" ""

lauf workflow_dispatch ""
pruefe "Von Hand gestartet" "$ALLE" true

exit "$FAILED"
